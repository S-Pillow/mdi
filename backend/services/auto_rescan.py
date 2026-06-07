"""
MDI-15A auto-rescan service — stale flagged URL-mode items during initial job processing.

Runs inline after the first VT report and initial triage, before the live-check pass.
Reuses MDI-15 scan plumbing (request_new_scan, reprocess_item_after_vt).
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from models import (
    Freshness,
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
)
from services import job_actions, job_store, quota_writer, vt_service
from services.job_store import InMemoryJob
from services.quota_writer import QuotaLockTimeout, read_remaining_quota

logger = logging.getLogger("mdi.auto_rescan")

_STALE_FRESHNESS = frozenset({Freshness.STALE, Freshness.VERY_STALE})
_MIN_SCAN_QUOTA = 2


def _is_held(result: MdiResultItem) -> bool:
    if result.processing_status == MdiProcessingStatus.HOLD_SKIPPED:
        return True
    hold = result.domain_hold
    return bool(hold and hold.has_hold)


def evaluate_auto_rescan_eligibility(
    job: InMemoryJob,
    result: MdiResultItem,
    *,
    remaining_quota: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Return (eligible, skip_reason).

    skip_reason is a machine-readable code when eligible is False.
    """
    if not job.auto_rescan_stale:
        return False, None
    if job.max_auto_rescans <= 0:
        return False, "auto_rescan_job_limit"
    if _is_held(result):
        return False, "auto_rescan_held"
    if result.processing_status == MdiProcessingStatus.ERROR:
        return False, "auto_rescan_no_vt_data"
    if not (result.vt_total_engines or 0):
        return False, "auto_rescan_no_vt_data"
    if not ((result.vt_hits or 0) > 0 or (result.vt_suspicious or 0) > 0):
        return False, "auto_rescan_not_flagged"
    if result.freshness not in _STALE_FRESHNESS:
        return False, "auto_rescan_not_stale"
    if not vt_service.scan_supported_for_item(result.input_type, job.use_domain_reports):
        return False, "auto_rescan_domain_report_mode"
    if job.auto_rescan_attempted_count >= job.max_auto_rescans:
        return False, "auto_rescan_job_limit"
    if result.input_normalized in job.auto_rescanned_items:
        return False, "auto_rescan_job_limit"
    remaining = remaining_quota if remaining_quota is not None else read_remaining_quota()
    if remaining < _MIN_SCAN_QUOTA:
        return False, "auto_rescan_quota_blocked"
    return True, None


async def maybe_auto_rescan_item(
    job: InMemoryJob,
    normalized: str,
    *,
    usage_file=None,
) -> None:
    """
    Attempt auto-rescan for one item after initial VT + triage.

    Mutates job.results[normalized] and job-level auto-rescan counters.
    """
    result = job.results.get(normalized)
    if result is None:
        return

    try:
        remaining = read_remaining_quota(usage_file)
    except QuotaLockTimeout:
        job.auto_rescan_skipped_count += 1
        job.auto_rescan_quota_blocked_count += 1
        err = MdiError(
            code="quota_lock_timeout",
            message="Auto-rescan skipped: shared quota lock unavailable.",
            source="auto_rescan",
            retriable=True,
        )
        errors = list(result.errors or [])
        errors.append(err)
        job.results[normalized] = result.model_copy(update={"errors": errors})
        return

    eligible, skip_reason = evaluate_auto_rescan_eligibility(
        job, result, remaining_quota=remaining,
    )
    if not eligible:
        if skip_reason and job.auto_rescan_stale:
            job.auto_rescan_skipped_count += 1
            if skip_reason == "auto_rescan_quota_blocked":
                job.auto_rescan_quota_blocked_count += 1
                err = MdiError(
                    code="auto_rescan_quota_blocked",
                    message="Auto-rescan skipped: insufficient VT quota remaining.",
                    source="auto_rescan",
                    retriable=True,
                )
                errors = list(result.errors or [])
                errors.append(err)
                job.results[normalized] = result.model_copy(update={"errors": errors})
        return

    job.auto_rescan_attempted_count += 1
    job.auto_rescanned_items.add(normalized)

    vt_result = await vt_service.request_new_scan(
        normalized,
        result.input_type,
        use_domain_reports=job.use_domain_reports,
        stale_threshold_days=job.stale_threshold_days,
    )

    if vt_result.calls_made > 0:
        try:
            await quota_writer.increment_quota(vt_result.calls_made, usage_file)
            job.lookups_used += vt_result.calls_made
        except QuotaLockTimeout:
            logger.warning("auto_rescan quota lock timeout for job %s", job.job_id)
        except Exception as exc:
            logger.error("auto_rescan quota increment failed for job %s: %s", job.job_id, exc)

    if vt_result.error:
        job.auto_rescan_failed_count += 1
        updated = await job_actions.reprocess_item_after_vt(
            job, result, vt_result, rerun_live_check=False,
        )
        job.results[normalized] = updated
        return

    job.auto_rescan_completed_count += 1
    updated = await job_actions.reprocess_item_after_vt(
        job, result, vt_result, rerun_live_check=False,
    )
    job.results[normalized] = updated
