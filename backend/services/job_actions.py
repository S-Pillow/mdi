"""
MDI-15 job action service — manual VT refresh and rescan lifecycle.

Handles refresh/scan on completed/recovered jobs in-place:
  - No new job_id
  - Saved job options (use_domain_reports, stale_threshold_days)
  - Held-domain skip
  - Downstream triage + conditional live-check rerun
  - mdi_latest_job.json persistence
  - Aggregate-only usage history per action batch

All VT and live-check calls go through mockable service layers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models import (
    Freshness,
    InputType,
    JobActionEstimateResponse,
    JobActionRequest,
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
    RefreshScanScope,
    VtModeUsed,
)
from services import job_persistence, job_store, live_check, quota_writer, triage_rules, vt_service
from services.job_store import InMemoryJob, get_job, get_job_sync, register_recovered_job
from services.live_check import LiveCheckResult
from services.quota_writer import QuotaLockTimeout, read_remaining_quota
from services.vt_service import VtLookupResult

logger = logging.getLogger("mdi.job_actions")

_STALE_FRESHNESS = frozenset({Freshness.STALE, Freshness.VERY_STALE})

@dataclass
class EligibilityResult:
    """Outcome of selecting items for a refresh/scan action."""
    eligible: List[MdiResultItem] = field(default_factory=list)
    skipped_count: int = 0
    skipped_reasons: Dict[str, int] = field(default_factory=dict)

    def record_skip(self, reason: str) -> None:
        self.skipped_count += 1
        self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1


def _is_held(result: MdiResultItem) -> bool:
    if result.processing_status == MdiProcessingStatus.HOLD_SKIPPED:
        return True
    hold = result.domain_hold
    return bool(hold and hold.has_hold)


def _result_by_position(job: InMemoryJob, position: int) -> Optional[MdiResultItem]:
    for normalized in job.item_order:
        r = job.results.get(normalized)
        if r and r.position == position:
            return r
    return None


def _vt_mode_for_result(job: InMemoryJob, result: MdiResultItem) -> VtModeUsed:
    _, vt_mode = vt_service._build_vt_target(
        result.input_normalized,
        result.input_type,
        job.use_domain_reports,
    )
    return vt_mode


def _is_stale(result: MdiResultItem) -> bool:
    return result.freshness in _STALE_FRESHNESS


def _should_rerun_live_check(result: MdiResultItem) -> bool:
    if _is_held(result):
        return False
    if result.processing_status == MdiProcessingStatus.ERROR:
        return False
    if not (result.vt_total_engines or 0):
        return False
    return (result.vt_hits or 0) > 0 or (result.vt_suspicious or 0) > 0


def select_eligible_items(
    job: InMemoryJob,
    scope: RefreshScanScope,
    positions: Optional[List[int]],
    action: str,
) -> EligibilityResult:
    """
    Select items eligible for refresh or scan.

    action: "refresh" or "scan"
    """
    out = EligibilityResult()

    if scope == RefreshScanScope.SELECTED:
        if not positions:
            return out
        for pos in positions:
            result = _result_by_position(job, pos)
            if result is None:
                out.record_skip("invalid_position")
                continue
            _evaluate_item(job, result, action, out)
    else:
        for normalized in job.item_order:
            result = job.results.get(normalized)
            if result is None:
                continue
            if not _is_stale(result):
                continue
            _evaluate_item(job, result, action, out)

    return out


def _evaluate_item(
    job: InMemoryJob,
    result: MdiResultItem,
    action: str,
    out: EligibilityResult,
) -> None:
    if not result.input_normalized:
        out.record_skip("missing_input")
        return
    if _is_held(result):
        out.record_skip("held")
        return
    if action == "scan" and not vt_service.scan_supported_for_item(
        result.input_type, job.use_domain_reports
    ):
        out.record_skip("unsupported_item_type")
        return
    out.eligible.append(result)


def _quota_per_item(action: str, job: InMemoryJob, result: MdiResultItem) -> Tuple[int, int]:
    if action == "refresh":
        return 1, 1
    vt_mode = _vt_mode_for_result(job, result)
    return vt_service.scan_quota_estimate_for_mode(vt_mode)


def estimate_action(
    job: InMemoryJob,
    action: str,
    request: JobActionRequest,
) -> JobActionEstimateResponse:
    """Compute quota estimate for a refresh or scan batch."""
    selection = select_eligible_items(job, request.scope, request.positions, action)
    q_min = q_max = 0
    url_scan_eligible_count = 0
    domain_rescan_eligible_count = 0
    for item in selection.eligible:
        cmin, cmax = _quota_per_item(action, job, item)
        q_min += cmin
        q_max += cmax
        if action == "scan":
            if _vt_mode_for_result(job, item) == VtModeUsed.DOMAIN_REPORT:
                domain_rescan_eligible_count += 1
            else:
                url_scan_eligible_count += 1

    try:
        remaining = read_remaining_quota()
    except QuotaLockTimeout:
        return JobActionEstimateResponse(
            job_id=job.job_id,
            action=action,
            scope=request.scope.value if hasattr(request.scope, "value") else str(request.scope),
            eligible_count=len(selection.eligible),
            skipped_count=selection.skipped_count,
            skipped_reasons_summary=selection.skipped_reasons,
            estimated_quota_min=q_min,
            estimated_quota_max=q_max,
            quota_remaining=0,
            will_exceed_quota=True,
            message="Shared quota lock unavailable; try again shortly.",
            url_scan_eligible_count=url_scan_eligible_count,
            domain_rescan_eligible_count=domain_rescan_eligible_count,
        )

    will_exceed = q_max > remaining

    scope_val = request.scope.value if hasattr(request.scope, "value") else str(request.scope)
    if selection.eligible:
        msg = (
            f"{action.capitalize()} will process {len(selection.eligible)} item(s); "
            f"estimated {q_min}–{q_max} VT quota unit(s)."
        )
        if action == "scan" and (url_scan_eligible_count or domain_rescan_eligible_count):
            parts = []
            if url_scan_eligible_count:
                parts.append(f"{url_scan_eligible_count} URL scan(s)")
            if domain_rescan_eligible_count:
                parts.append(f"{domain_rescan_eligible_count} domain rescan(s)")
            msg += f" Includes {' and '.join(parts)}."
    else:
        msg = f"No eligible items for {action}."

    if will_exceed:
        msg += f" Blocked: worst-case estimate ({q_max}) exceeds remaining quota ({remaining})."

    return JobActionEstimateResponse(
        job_id=job.job_id,
        action=action,
        scope=scope_val,
        eligible_count=len(selection.eligible),
        skipped_count=selection.skipped_count,
        skipped_reasons_summary=selection.skipped_reasons,
        estimated_quota_min=q_min,
        estimated_quota_max=q_max,
        quota_remaining=remaining,
        will_exceed_quota=will_exceed,
        message=msg,
        url_scan_eligible_count=url_scan_eligible_count,
        domain_rescan_eligible_count=domain_rescan_eligible_count,
    )


async def resolve_job(job_id: str) -> Optional[InMemoryJob]:
    """Load job from memory or recover from mdi_latest_job.json if job_id matches."""
    job = await get_job(job_id)
    if job is not None:
        return job

    persisted = job_persistence.read_latest_job()
    if persisted is not None and persisted.job_id == job_id:
        register_recovered_job(persisted)
        return get_job_sync(job_id)
    return None


def validate_job_for_action(job: InMemoryJob) -> Optional[str]:
    """Return error message if job cannot accept an action, else None."""
    if job.action_in_progress:
        return "A refresh/scan action is already in progress for this job."
    if job.status in ("queued", "running"):
        return f"Job status '{job.status}' does not allow refresh/scan actions."
    if job.status not in ("done", "error"):
        return f"Job status '{job.status}' does not allow refresh/scan actions."
    return None


async def reprocess_item_after_vt(
    job: InMemoryJob,
    result: MdiResultItem,
    vt_result: VtLookupResult,
    *,
    rerun_live_check: bool = True,
) -> MdiResultItem:
    """
    Apply updated VT data, optionally rerun live check, and recompute triage.

    On VT error: preserve prior VT fields; append structured error only.
    """
    prior_errors = list(result.errors or [])
    non_vt_errors = [e for e in prior_errors if e.source != "vt_service"]

    if vt_result.error:
        new_errors = non_vt_errors + [vt_result.error]
        if vt_result.error.code == "scan_not_supported":
            return result.model_copy(update={"errors": new_errors})
        return result.model_copy(update={"errors": new_errors})

    vt_error: List[MdiError] = []
    processing_status = MdiProcessingStatus.DONE
    errors = non_vt_errors + vt_error

    updated = result.model_copy(update={
        "processing_status": processing_status,
        "vt_mode_used": vt_result.vt_mode_used,
        "vt_hits": vt_result.vt_malicious,
        "vt_suspicious": vt_result.vt_suspicious,
        "vt_total_engines": vt_result.vt_total_engines,
        "vt_ratio": vt_result.vt_ratio,
        "vt_scan_date": vt_result.vt_scan_date,
        "freshness": vt_result.freshness,
        "vt_engine_results": vt_result.engine_detections,
        "errors": errors,
    })

    if rerun_live_check and _should_rerun_live_check(updated):
        try:
            lc_result: LiveCheckResult = await live_check.live_check_item(
                updated.input_normalized,
                updated.input_type,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("live_check during action failed: %s", exc)
            lc_result = LiveCheckResult(live_status=updated.live_status)

        lc_errors = list(updated.errors or [])
        if lc_result.error is not None:
            lc_errors.append(lc_result.error)
            job.live_check_error_count += 1
        job.live_check_count += 1

        inp = triage_rules.TriageInput(
            domain_hold_has_hold=False,
            processing_status=processing_status,
            vt_hits=updated.vt_hits or 0,
            vt_suspicious=updated.vt_suspicious or 0,
            vt_total_engines=updated.vt_total_engines or 0,
            freshness=updated.freshness or Freshness.UNKNOWN,
            live_status=lc_result.live_status,
            age_bucket=updated.age_bucket,
            errors=lc_errors,
            stale_threshold_days=job.stale_threshold_days,
        )
        dec = triage_rules.decide(inp)
        return updated.model_copy(update={
            "live_status": lc_result.live_status,
            "http_status_code": lc_result.http_status_code,
            "redirect_count": lc_result.redirect_count,
            "triage_bucket": dec.triage_bucket,
            "triage_confidence": dec.triage_confidence,
            "recommended_action": dec.recommended_action,
            "evidence_status": dec.evidence_status,
            "triage_reason": dec.triage_reason,
            "errors": lc_errors,
        })

    inp = triage_rules.TriageInput(
        domain_hold_has_hold=False,
        processing_status=processing_status,
        vt_hits=updated.vt_hits or 0,
        vt_suspicious=updated.vt_suspicious or 0,
        vt_total_engines=updated.vt_total_engines or 0,
        freshness=updated.freshness or Freshness.UNKNOWN,
        live_status=updated.live_status,
        age_bucket=updated.age_bucket,
        errors=errors,
        stale_threshold_days=job.stale_threshold_days,
    )
    dec = triage_rules.decide(inp)
    return updated.model_copy(update={
        "triage_bucket": dec.triage_bucket,
        "triage_confidence": dec.triage_confidence,
        "recommended_action": dec.recommended_action,
        "evidence_status": dec.evidence_status,
        "triage_reason": dec.triage_reason,
        "errors": errors,
    })


@dataclass
class ActionStats:
    items_attempted: int = 0
    items_completed: int = 0
    quota_units: int = 0
    errors_count: int = 0
    scan_failed_count: int = 0
    live_check_count: int = 0
    live_check_error_count: int = 0


async def _run_items(
    job: InMemoryJob,
    items: List[MdiResultItem],
    action: str,
    *,
    usage_file: Optional[Path] = None,
    history_file: Optional[Path] = None,
    daily_file: Optional[Path] = None,
    job_file: Optional[Path] = None,
) -> ActionStats:
    stats = ActionStats(items_attempted=len(items))
    lc_before = job.live_check_count
    lce_before = job.live_check_error_count

    for result in items:
        try:
            remaining = read_remaining_quota(usage_file)
        except QuotaLockTimeout:
            logger.warning("Quota lock timeout before %s for job %s", action, job.job_id)
            stats.errors_count += 1
            continue

        if remaining <= 0:
            stats.errors_count += 1
            continue

        if action == "refresh":
            vt_result = await vt_service.refresh_report(
                result.input_normalized,
                result.input_type,
                use_domain_reports=job.use_domain_reports,
                stale_threshold_days=job.stale_threshold_days,
            )
        else:
            job.vt_scan_requested_count += 1
            vt_result = await vt_service.request_new_scan(
                result.input_normalized,
                result.input_type,
                use_domain_reports=job.use_domain_reports,
                stale_threshold_days=job.stale_threshold_days,
            )

        if vt_result.calls_made > 0:
            try:
                await quota_writer.increment_quota(vt_result.calls_made, usage_file)
                job.lookups_used += vt_result.calls_made
                stats.quota_units += vt_result.calls_made
            except QuotaLockTimeout:
                logger.warning("Quota lock timeout incrementing during %s", action)
            except Exception as exc:
                logger.error("quota increment failed during action: %s", exc)

        updated = await reprocess_item_after_vt(job, result, vt_result)
        job.results[result.input_normalized] = updated
        stats.items_completed += 1

        if vt_result.error:
            stats.errors_count += 1
            if action == "scan":
                stats.scan_failed_count += 1
                job.vt_scan_failed_count += 1

    stats.live_check_count = job.live_check_count - lc_before
    stats.live_check_error_count = job.live_check_error_count - lce_before

    job.last_action_at = time.time()
    job.completed_at = job.last_action_at

    try:
        await job_persistence.write_latest_job(job, job_file=job_file)
    except Exception as exc:
        logger.error("persist after action failed: %s", exc)

    return stats


def _append_action_history(
    job: InMemoryJob,
    action: str,
    scope: RefreshScanScope,
    selection: EligibilityResult,
    stats: ActionStats,
    *,
    history_file: Optional[Path] = None,
    daily_file: Optional[Path] = None,
) -> None:
    operation = "refresh" if action == "refresh" else "force_scan"
    rescan_selected = len(selection.eligible) if scope == RefreshScanScope.SELECTED else 0
    rescan_stale = len(selection.eligible) if scope == RefreshScanScope.STALE else 0

    record = quota_writer.build_usage_history_record(
        job_id=job.job_id,
        items_attempted=stats.items_attempted,
        items_completed=stats.items_completed,
        quota_units_consumed=stats.quota_units,
        quota_blocked_count=0,
        errors_count=stats.errors_count,
        held_skipped_count=selection.skipped_reasons.get("held", 0),
        processing_options_summary={
            "use_domain_reports": job.use_domain_reports,
            "stale_threshold_days": job.stale_threshold_days,
        },
        status=job.status,
        live_check_count=stats.live_check_count,
        live_check_skipped_count=0,
        live_check_error_count=stats.live_check_error_count,
        operation=operation,
        skipped_count=selection.skipped_count,
        refresh_count=stats.items_completed if action == "refresh" else 0,
        scan_requested_count=stats.items_attempted if action == "scan" else 0,
        scan_completed_count=(
            stats.items_completed - stats.scan_failed_count if action == "scan" else 0
        ),
        scan_failed_count=stats.scan_failed_count,
        rescan_selected_count=rescan_selected,
        rescan_stale_count=rescan_stale,
    )
    quota_writer.append_usage_history(record, history_file)
    if stats.quota_units > 0:
        quota_writer.update_daily_history(
            stats.quota_units,
            daily_file,
            items_processed=stats.items_completed,
        )


async def run_refresh_action(job_id: str, request: JobActionRequest) -> None:
    """Background task: refresh selected or stale items."""
    job = await resolve_job(job_id)
    if job is None:
        return

    selection = select_eligible_items(job, request.scope, request.positions, "refresh")
    job.action_in_progress = True
    job.last_action_type = "refresh"
    try:
        stats = await _run_items(job, selection.eligible, "refresh")
        job.vt_refresh_count += stats.items_completed
        _append_action_history(job, "refresh", request.scope, selection, stats)
    finally:
        job.action_in_progress = False


async def run_scan_action(job_id: str, request: JobActionRequest) -> None:
    """Background task: request new scan for selected or stale items."""
    job = await resolve_job(job_id)
    if job is None:
        return

    selection = select_eligible_items(job, request.scope, request.positions, "scan")
    job.action_in_progress = True
    job.last_action_type = "scan"
    try:
        stats = await _run_items(job, selection.eligible, "scan")
        _append_action_history(job, "scan", request.scope, selection, stats)
    finally:
        job.action_in_progress = False


def start_refresh_action(job_id: str, request: JobActionRequest) -> None:
    asyncio.create_task(run_refresh_action(job_id, request))


def start_scan_action(job_id: str, request: JobActionRequest) -> None:
    asyncio.create_task(run_scan_action(job_id, request))
