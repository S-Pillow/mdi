"""
MDI async job processing loop.

Called via asyncio.create_task() from the submit endpoint, or called directly
in tests with mocked VT and injected file paths.

Processing flow for each eligible item:
  0. Pre-enrichment pass (MDI-11): RDAP/WHOIS before VT.
     a. Extract registered domain from each item's normalized input.
     b. Check per-job domain cache — enrich once per unique registered domain.
     c. Merge enrichment fields (created_at, age_bucket, registrar, epp_status,
        nameservers, domain_hold) into the in-memory result.
     d. If live enrichment confirms clientHold/serverHold:
        - Mark item HOLD_SKIPPED.
        - Run triage_rules.decide(domain_hold_has_hold=True).
        - Increment held_skipped counter.
        - Exclude from VT queue.
     e. Enrichment failures are non-fatal: item proceeds to VT with UNKNOWN fields.
  1. Check mid-run remaining quota (soft check; race with VT Bulk Check is accepted MVP risk).
  2. Call vt_service.fetch_report() — all HTTP mocked in tests via _vt_request patch.
  3. Increment shared quota file by calls_made.
  4. Build TriageInput from VT result + item fields.
  5. Call triage_rules.decide() — single authoritative triage decision.
  6. Update in-memory job state.
  7. Post-VT live-check pass (MDI-12): SSRF-safe HEAD probe for flagged/suspicious items.
     a. Skip held, error, quota-blocked, clean, and no-VT-data items.
     b. Call live_check.live_check_item() — all HTTP mocked in tests.
     c. Set result.live_status from LiveCheckResult.
     d. Re-run triage_rules.decide() with updated live_status.
     e. Live-check failures are non-fatal: original VT triage is preserved on error.

On completion, append a metadata-only record to the usage JSONL.
Usage JSONL records NEVER contain raw domains, URLs, or item-level result data.
Enrichment and live-check counts are metadata-only — no raw values.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Dict, Optional

from models import (
    AgeBucket,
    DomainHold,
    DomainHoldType,
    DomainStatusSource,
    Freshness,
    InputType,
    LiveStatus,
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
    VtModeUsed,
)
from services import (
    auto_rescan,
    domain_enrichment,
    job_persistence,
    job_store,
    live_check,
    quota_writer,
    triage_rules,
    vt_service,
)
from services.domain_enrichment import EnrichmentResult
from services.live_check import LiveCheckResult

logger = logging.getLogger("mdi.job_processor")


def _make_held_result(
    job: job_store.InMemoryJob,
    normalized: str,
    position: int,
    original: str,
    input_type: InputType,
) -> MdiResultItem:
    """Build a fully-populated hold-skipped result item via the rules engine."""
    import models as _m

    inp = triage_rules.TriageInput(domain_hold_has_hold=True)
    dec = triage_rules.decide(inp)

    return MdiResultItem(
        input_original=original,
        input_normalized=normalized,
        input_type=input_type,
        position=position,
        processing_status=MdiProcessingStatus.HOLD_SKIPPED,
        domain_hold=DomainHold(
            has_hold=True,
            hold_types=[DomainHoldType.CLIENT_HOLD],
            source=_m.DomainStatusSource.UNKNOWN,
        ),
        vt_mode_used=VtModeUsed.SKIPPED_HOLD,
        triage_bucket=dec.triage_bucket,
        triage_confidence=dec.triage_confidence,
        recommended_action=dec.recommended_action,
        evidence_status=dec.evidence_status,
        triage_reason=dec.triage_reason,
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
        # MDI-11: enrich all items with RDAP/WHOIS before VT processing
        await _enrich_items(job)
        await _run_items(job, usage_file=usage_file)
        # MDI-12: live HTTP check for flagged/suspicious items after VT
        await _live_check_items(job)
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


# ── Pre-enrichment pass (MDI-11) ───────────────────────────────────────────────

def _should_skip_enrichment(result: MdiResultItem) -> bool:
    """
    Return True if this item should skip RDAP/WHOIS enrichment.

    Skip when the uploaded file already confirmed a hold — no need to re-check.
    Items already HOLD_SKIPPED at submit time are also skipped.
    """
    if result.processing_status == MdiProcessingStatus.HOLD_SKIPPED:
        return True
    if (
        result.domain_hold is not None
        and result.domain_hold.source == DomainStatusSource.UPLOADED_FILE
        and result.domain_hold.has_hold
    ):
        return True
    return False


def _merge_enrichment_into_result(
    result: MdiResultItem,
    enrichment: EnrichmentResult,
) -> dict:
    """
    Build a model_copy update dict that merges enrichment fields into the result.

    Precedence rules:
      - Enrichment error (both RDAP and WHOIS failed): only the error is recorded;
        no data fields are merged — item proceeds to VT with UNKNOWN enrichment fields.
      - Uploaded confirmed hold (source=UPLOADED_FILE, has_hold=True): already
        handled by _should_skip_enrichment — this function is not called.
      - Existing non-None / non-default field: PRESERVE (do not overwrite).
      - Field is None / empty / UNKNOWN: replace with enrichment value.

    Returns an update dict suitable for result.model_copy(update=...).
    """
    updates: dict = {}

    # If enrichment completely failed, only record the error — do not merge
    # data fields. Item proceeds to VT with UNKNOWN age_bucket and no hold data.
    if enrichment.error is not None and enrichment.source == DomainStatusSource.UNKNOWN:
        existing_errors = list(result.errors or [])
        existing_errors.append(enrichment.error)
        updates["errors"] = existing_errors
        return updates

    # created_at: only set if currently None
    if result.created_at is None and enrichment.created_at is not None:
        updates["created_at"] = enrichment.created_at

    # age_bucket: only set if currently UNKNOWN
    if result.age_bucket == AgeBucket.UNKNOWN and enrichment.age_bucket != AgeBucket.UNKNOWN:
        updates["age_bucket"] = enrichment.age_bucket

    # registrar: only set if currently None
    if result.registrar is None and enrichment.registrar:
        updates["registrar"] = enrichment.registrar

    # epp_status: only set if currently empty
    if not result.epp_status and enrichment.epp_status:
        updates["epp_status"] = enrichment.epp_status

    # nameservers: only set if currently empty
    if not result.nameservers and enrichment.nameservers:
        updates["nameservers"] = enrichment.nameservers

    # domain_hold: only set if not already from uploaded file
    if (
        result.domain_hold is None
        or result.domain_hold.source == DomainStatusSource.NOT_CHECKED
    ):
        updates["domain_hold"] = enrichment.domain_hold

    # Append enrichment errors (non-fatal) to existing error list
    if enrichment.error is not None:
        existing_errors = list(result.errors or [])
        existing_errors.append(enrichment.error)
        updates["errors"] = existing_errors

    return updates


async def _enrich_items(job: job_store.InMemoryJob) -> None:
    """
    Pre-enrichment pass: run RDAP/WHOIS for all eligible items before VT.

    Uses a per-job registered-domain cache to avoid redundant lookups when
    multiple items share the same registered domain (e.g., URL variants).

    Updates job enrichment counters (counts only — no raw domain values are
    stored in these counters or in the usage history record).
    """
    domain_cache: Dict[str, EnrichmentResult] = {}

    for normalized in job.item_order:
        result = job.results.get(normalized)
        if result is None:
            continue

        # Uploaded confirmed hold — skip enrichment
        if _should_skip_enrichment(result):
            job.enrichment_skipped_uploaded_hold_count += 1
            continue

        # Extract registered domain (None for IPs and invalid inputs)
        reg_domain = domain_enrichment.extract_registered_domain(
            result.input_normalized, result.input_type
        )
        if reg_domain is None:
            continue

        # Per-job cache — enrich once per unique registered domain
        if reg_domain in domain_cache:
            enrichment = domain_cache[reg_domain]
        else:
            enrichment = await domain_enrichment.enrich_domain(reg_domain)
            domain_cache[reg_domain] = enrichment

        # Merge enrichment fields into result
        updates = _merge_enrichment_into_result(result, enrichment)
        if updates:
            job.results[normalized] = result.model_copy(update=updates)
            result = job.results[normalized]

        # Track enrichment stats (counts only)
        if enrichment.error is not None and not enrichment.whois_fallback_used:
            job.rdap_failed_count += 1
        elif enrichment.error is not None and enrichment.whois_fallback_used:
            job.rdap_failed_count += 1
        elif enrichment.whois_fallback_used:
            job.whois_fallback_count += 1
            job.rdap_enriched_count += 1
        else:
            job.rdap_enriched_count += 1

        # If live enrichment confirms hold → mark HOLD_SKIPPED before VT
        if result.domain_hold is not None and result.domain_hold.has_hold:
            job.hold_detected_by_enrichment_count += 1
            inp = triage_rules.TriageInput(domain_hold_has_hold=True)
            dec = triage_rules.decide(inp)
            job.results[normalized] = job.results[normalized].model_copy(update={
                "processing_status": MdiProcessingStatus.HOLD_SKIPPED,
                "vt_mode_used": VtModeUsed.SKIPPED_HOLD,
                "triage_bucket": dec.triage_bucket,
                "triage_confidence": dec.triage_confidence,
                "recommended_action": dec.recommended_action,
                "evidence_status": dec.evidence_status,
                "triage_reason": dec.triage_reason,
            })
            job.held_skipped += 1


# ── VT processing loop ────────────────────────────────────────────────────────

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
            quota_err = MdiError(
                code="quota_exhausted",
                message="VT daily quota exhausted before this item was processed.",
                source="job_processor",
                retriable=True,
            )
            dec = triage_rules.decide(triage_rules.TriageInput(
                domain_hold_has_hold=False,
                processing_status=MdiProcessingStatus.ERROR,
                errors=[quota_err],
                age_bucket=result.age_bucket,
                live_status=result.live_status,
            ))
            job.results[normalized] = result.model_copy(update={
                "processing_status": MdiProcessingStatus.ERROR,
                "vt_mode_used": VtModeUsed.SKIPPED_QUOTA,
                "triage_bucket": dec.triage_bucket,
                "triage_confidence": dec.triage_confidence,
                "recommended_action": dec.recommended_action,
                "evidence_status": dec.evidence_status,
                "triage_reason": dec.triage_reason,
                "errors": [quota_err],
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

        # Build triage input from VT result + existing item fields (age, live status).
        # Preserve any enrichment errors accumulated by the pre-enrichment pass.
        vt_error = [vt_result.error] if vt_result.error else []
        enrichment_errors = list(result.errors or [])
        errors = enrichment_errors + vt_error
        processing_status = MdiProcessingStatus.ERROR if vt_result.error else MdiProcessingStatus.DONE

        inp = triage_rules.TriageInput(
            domain_hold_has_hold=False,
            processing_status=processing_status,
            vt_hits=vt_result.vt_malicious,
            vt_suspicious=vt_result.vt_suspicious,
            vt_total_engines=vt_result.vt_total_engines,
            freshness=vt_result.freshness,
            live_status=result.live_status,           # NOT_CHECKED until MDI-12
            age_bucket=result.age_bucket,             # Populated by MDI-11 enrichment
            errors=errors,
            stale_threshold_days=job.stale_threshold_days,
        )
        dec = triage_rules.decide(inp)

        job.results[normalized] = result.model_copy(update={
            "processing_status": processing_status,
            "vt_mode_used": vt_result.vt_mode_used,
            "vt_hits": vt_result.vt_malicious,
            "vt_suspicious": vt_result.vt_suspicious,
            "vt_total_engines": vt_result.vt_total_engines,
            "vt_ratio": vt_result.vt_ratio,
            "vt_scan_date": vt_result.vt_scan_date,
            "freshness": vt_result.freshness,
            "triage_bucket": dec.triage_bucket,
            "triage_confidence": dec.triage_confidence,
            "recommended_action": dec.recommended_action,
            "evidence_status": dec.evidence_status,
            "triage_reason": dec.triage_reason,
            "errors": errors,
            # MDI-14: persist engine-level detections (malicious/suspicious only)
            "vt_engine_results": vt_result.engine_detections,
        })
        job.processed += 1

        await auto_rescan.maybe_auto_rescan_item(
            job, normalized, usage_file=usage_file,
        )


# ── MDI-12 live-check pass ─────────────────────────────────────────────────────


def _should_live_check(result: MdiResultItem) -> bool:
    """
    Return True when an item should receive a live HTTP check.

    Eligibility requirements (all must be true):
      - Not held/HOLD_SKIPPED.
      - Not ERROR (includes quota-blocked items whose processing_status=ERROR).
      - VT ran (vt_total_engines > 0).
      - At least one VT hit (malicious) or suspicious vote.

    This ensures live checks run only for flagged/suspicious items.
    Clean items (zero hits, zero suspicious) are skipped.
    """
    if result.processing_status == MdiProcessingStatus.HOLD_SKIPPED:
        return False
    if result.processing_status == MdiProcessingStatus.ERROR:
        return False
    if not (result.vt_total_engines or 0):
        return False
    return (result.vt_hits or 0) > 0 or (result.vt_suspicious or 0) > 0


async def _live_check_items(job: job_store.InMemoryJob) -> None:
    """
    Run SSRF-safe live HTTP checks for flagged/suspicious items after VT.

    For each eligible item:
      1. Check eligibility via _should_live_check().
      2. Call live_check.live_check_item() — all HTTP mocked in tests.
      3. Set result.live_status from the LiveCheckResult.
      4. Append any structured error to result.errors (non-fatal).
      5. Re-run triage_rules.decide() with updated live_status.

    Live-check errors are non-fatal: VT triage fields are preserved, only
    live_status is updated and any error is appended to result.errors.

    Counters updated on job:
      - live_check_count: items that received a live check attempt.
      - live_check_skipped_count: items skipped by eligibility rules.
      - live_check_error_count: items where live_check returned an error.
    """
    for normalized in job.item_order:
        result = job.results.get(normalized)
        if result is None:
            continue

        if not _should_live_check(result):
            job.live_check_skipped_count += 1
            continue

        # Attempt live check — never raises (live_check_item catches all exceptions)
        try:
            lc_result: LiveCheckResult = await live_check.live_check_item(
                result.input_normalized,
                result.input_type,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "live_check: unexpected exception for item at position %s: %s",
                result.position, exc,
            )
            job.live_check_error_count += 1
            continue

        job.live_check_count += 1

        # Collect existing errors; append live-check error if any
        updated_errors = list(result.errors or [])
        if lc_result.error is not None:
            updated_errors.append(lc_result.error)
            job.live_check_error_count += 1

        # Re-run triage with updated live_status (preserves all VT + enrichment fields)
        inp = triage_rules.TriageInput(
            domain_hold_has_hold=False,
            processing_status=result.processing_status,
            vt_hits=result.vt_hits or 0,
            vt_suspicious=result.vt_suspicious or 0,
            vt_total_engines=result.vt_total_engines or 0,
            freshness=result.freshness or Freshness.UNKNOWN,
            live_status=lc_result.live_status,
            age_bucket=result.age_bucket or AgeBucket.UNKNOWN,
            errors=updated_errors,
            stale_threshold_days=job.stale_threshold_days,
        )
        dec = triage_rules.decide(inp)

        job.results[normalized] = result.model_copy(update={
            "live_status": lc_result.live_status,
            "triage_bucket": dec.triage_bucket,
            "triage_confidence": dec.triage_confidence,
            "recommended_action": dec.recommended_action,
            "evidence_status": dec.evidence_status,
            "triage_reason": dec.triage_reason,
            "errors": updated_errors,
            # MDI-14: propagate live-check HTTP details for drawer display
            "http_status_code": lc_result.http_status_code,
            "redirect_count": lc_result.redirect_count,
        })


# ── Persistence helpers ────────────────────────────────────────────────────────

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
            "auto_rescan_stale": job.auto_rescan_stale,
            "max_auto_rescans": job.max_auto_rescans,
            "auto_rescan_enabled": job.auto_rescan_stale,
            "auto_rescan_attempted_count": job.auto_rescan_attempted_count,
            "auto_rescan_completed_count": job.auto_rescan_completed_count,
            "auto_rescan_failed_count": job.auto_rescan_failed_count,
            "auto_rescan_skipped_count": job.auto_rescan_skipped_count,
            "auto_rescan_quota_blocked_count": job.auto_rescan_quota_blocked_count,
        },
        status=job.status,
        rdap_enriched_count=job.rdap_enriched_count,
        rdap_failed_count=job.rdap_failed_count,
        whois_fallback_count=job.whois_fallback_count,
        hold_detected_by_enrichment_count=job.hold_detected_by_enrichment_count,
        enrichment_skipped_uploaded_hold_count=job.enrichment_skipped_uploaded_hold_count,
        live_check_count=job.live_check_count,
        live_check_skipped_count=job.live_check_skipped_count,
        live_check_error_count=job.live_check_error_count,
        auto_rescan_enabled=job.auto_rescan_stale,
        auto_rescan_attempted_count=job.auto_rescan_attempted_count,
        auto_rescan_completed_count=job.auto_rescan_completed_count,
        auto_rescan_failed_count=job.auto_rescan_failed_count,
        auto_rescan_skipped_count=job.auto_rescan_skipped_count,
        auto_rescan_quota_blocked_count=job.auto_rescan_quota_blocked_count,
    )
    quota_writer.append_usage_history(record, history_file)

    if job.lookups_used > 0:
        quota_writer.update_daily_history(job.lookups_used, daily_file)
