"""
MDI async job processing loop.

Called via asyncio.create_task() from the submit endpoint, or called directly
in tests with mocked VT and injected file paths.

Processing flow for each eligible item:
  1. Check mid-run remaining quota (soft check; race with VT Bulk Check is accepted MVP risk).
  2. Call vt_service.fetch_report() — all HTTP mocked in tests via _vt_request patch.
  3. Increment shared quota file by calls_made.
  4. Parse result into MdiResultItem fields and classify triage.
  5. Update in-memory job state.

On completion, append a metadata-only record to the usage JSONL.
Usage JSONL records NEVER contain raw domains, URLs, or item-level result data.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from models import (
    DomainHold,
    DomainHoldType,
    EvidenceStatus,
    InputType,
    LiveStatus,
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
    RecommendedAction,
    TriageBucket,
    TriageConfidence,
    VtModeUsed,
)
from services import job_persistence, job_store, quota_writer, vt_service

logger = logging.getLogger("mdi.job_processor")


def _make_held_result(job: job_store.InMemoryJob, normalized: str, position: int, original: str, input_type: InputType) -> MdiResultItem:
    """Build a fully-populated hold-skipped result item."""
    return MdiResultItem(
        input_original=original,
        input_normalized=normalized,
        input_type=input_type,
        position=position,
        processing_status=MdiProcessingStatus.HOLD_SKIPPED,
        domain_hold=DomainHold(
            has_hold=True,
            hold_types=[DomainHoldType.CLIENT_HOLD],
            source=__import__("models").DomainStatusSource.UNKNOWN,
        ),
        vt_mode_used=VtModeUsed.SKIPPED_HOLD,
        triage_bucket=TriageBucket.HELD,
        triage_confidence=TriageConfidence.HIGH,
        recommended_action=RecommendedAction.ACTION_ALREADY_TAKEN,
        evidence_status=EvidenceStatus.SKIPPED_HOLD,
        live_status=LiveStatus.NOT_CHECKED,
    )


async def process_job(
    job_id: str,
    *,
    usage_file: Optional[Path] = None,
    history_file: Optional[Path] = None,
    daily_file: Optional[Path] = None,
    job_file: Optional[Path] = None,
) -> None:
    """
    Process all eligible (non-held) items in an MDI job.

    Injected file paths allow tests to use tmp_path without patching module globals.
    When None, quota_writer uses its own environment-variable-based defaults.

    This function is safe to call directly from tests:
        asyncio.run(process_job(job_id, usage_file=tmp, history_file=tmp2, job_file=tmp3))
    """
    job = job_store.get_job_sync(job_id)
    if job is None:
        logger.error("process_job: job %s not found in store.", job_id)
        return

    job.status = "running"

    try:
        await _run_items(job, usage_file=usage_file)
    except Exception as exc:  # noqa: BLE001
        logger.exception("process_job: unexpected error in job %s: %s", job_id, exc)
        job.status = "error"
        job.error_message = f"Unexpected error: {exc}"
    else:
        job.status = "done"
    finally:
        job.completed_at = time.time()
        # Order matters: metadata-only usage history first, full recovery snapshot second.
        _write_history(job, history_file=history_file, daily_file=daily_file)
        await _write_persistence(job, job_file=job_file)


async def _run_items(job: job_store.InMemoryJob, *, usage_file: Optional[Path]) -> None:
    """Iterate eligible items and run VT checks."""
    for normalized in job.item_order:
        result = job.results.get(normalized)
        if result is None:
            continue
        if result.processing_status == MdiProcessingStatus.HOLD_SKIPPED:
            # Pre-populated held items — already in results, skip VT entirely.
            continue

        # Mid-run quota soft-check (race with VT Bulk Check is accepted MVP risk)
        remaining = quota_writer.read_remaining_quota(usage_file)
        if remaining <= 0:
            job.quota_blocked_count += 1
            job.results[normalized] = result.model_copy(update={
                "processing_status": MdiProcessingStatus.ERROR,
                "vt_mode_used": VtModeUsed.SKIPPED_QUOTA,
                "triage_bucket": TriageBucket.ERROR,
                "triage_confidence": TriageConfidence.UNKNOWN,
                "recommended_action": RecommendedAction.MANUAL_REVIEW,
                "evidence_status": EvidenceStatus.PARTIAL,
                "errors": [MdiError(
                    code="quota_exhausted",
                    message="VT daily quota exhausted before this item was processed.",
                    source="job_processor",
                    retriable=True,
                )],
            })
            job.processed += 1
            continue

        # VT lookup
        vt_result = await vt_service.fetch_report(
            input_normalized=normalized,
            input_type=result.input_type,
            use_domain_reports=job.use_domain_reports,
            stale_threshold_days=job.stale_threshold_days,
        )

        # Increment quota for actual calls made
        if vt_result.calls_made > 0:
            try:
                await quota_writer.increment_quota(vt_result.calls_made, usage_file)
                job.lookups_used += vt_result.calls_made
            except Exception as exc:
                logger.error("Failed to increment quota for job %s: %s", job.job_id, exc)

        # Classify triage
        triage_bucket, triage_conf, recommended_action, evidence_status = vt_service.classify_triage(vt_result)

        # Determine processing_status
        if vt_result.error:
            processing_status = MdiProcessingStatus.ERROR
            errors = [vt_result.error]
        else:
            processing_status = MdiProcessingStatus.DONE
            errors = []

        # Update result
        job.results[normalized] = result.model_copy(update={
            "processing_status": processing_status,
            "vt_mode_used": vt_result.vt_mode_used,
            "vt_hits": vt_result.vt_malicious,
            "vt_suspicious": vt_result.vt_suspicious,
            "vt_total_engines": vt_result.vt_total_engines,
            "vt_ratio": vt_result.vt_ratio,
            "vt_scan_date": vt_result.vt_scan_date,
            "freshness": vt_result.freshness,
            "triage_bucket": triage_bucket,
            "triage_confidence": triage_conf,
            "recommended_action": recommended_action,
            "evidence_status": evidence_status,
            "errors": errors,
        })
        job.processed += 1


async def _write_persistence(
    job: job_store.InMemoryJob,
    *,
    job_file: Optional[Path],
) -> None:
    """Write the latest completed job snapshot for recovery. Failure is logged and swallowed."""
    try:
        await job_persistence.write_latest_job(job, job_file=job_file)
    except Exception as exc:
        logger.error(
            "process_job: failed to persist latest job %s: %s — "
            "job is still valid in memory for this session.",
            job.job_id, exc,
        )


def _write_history(
    job: job_store.InMemoryJob,
    *,
    history_file: Optional[Path],
    daily_file: Optional[Path],
) -> None:
    """Append metadata-only usage record. Called once per job, idempotent."""
    if job.usage_history_written:
        return
    job.usage_history_written = True

    errors_count = sum(
        1 for r in job.results.values()
        if r.processing_status == MdiProcessingStatus.ERROR
    )

    record = quota_writer.build_usage_history_record(
        job_id=job.job_id,
        items_attempted=job.total,
        items_completed=job.processed,
        quota_units_consumed=job.lookups_used,
        quota_blocked_count=job.quota_blocked_count,
        errors_count=errors_count,
        held_skipped_count=job.held_skipped,
        processing_options_summary={
            "use_domain_reports": job.use_domain_reports,
            "stale_threshold_days": job.stale_threshold_days,
        },
        status=job.status,
    )
    quota_writer.append_usage_history(record, history_file)

    if job.lookups_used > 0:
        quota_writer.update_daily_history(job.lookups_used, daily_file)
