"""
MDI API router — /api/mdi/* endpoints.

MDI-03 endpoints:
  GET /api/mdi/health              — service liveness check
  GET /api/mdi/usage               — read shared VT quota state (read-only)
  GET /api/mdi/schema-summary      — enum/field summary for development verification

MDI-04 endpoints:
  POST /api/mdi/jobs/parse-preview — parse raw pasted text, no external calls

MDI-05 endpoints:
  POST /api/mdi/jobs/upload-preview — parse CSV/XLSX upload with hold detection

MDI-06 endpoints:
  POST /api/mdi/jobs/submit         — submit VT job; returns job_id
  GET  /api/mdi/jobs/{job_id}       — poll job status and results

MDI-07 endpoints:
  POST /api/mdi/jobs/estimate       — quota and runtime estimate preview; no VT calls, no job created

MDI-08 endpoints:
  GET  /api/mdi/jobs/latest         — recover latest completed job; reads mdi_latest_job.json if memory empty

MDI-15 endpoints:
  POST /api/mdi/jobs/{job_id}/refresh  — manual VT report refresh (GET only)
  POST /api/mdi/jobs/{job_id}/scan     — manual VT new-scan request (POST + poll)

MDI-16 endpoints:
  POST /api/mdi/jobs/{job_id}/export  — CSV or JSON evidence download; no quota, no persistence

MDI-17 endpoints:
  GET  /api/mdi/dashboard             — read-only operational dashboard; metadata-only

MDI-26 endpoints:
  GET  /api/mdi/version               — deploy build identity (read-only)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from models import (
    AgeBucket,
    DomainHold,
    DomainHoldType,
    DomainStatusSource,
    DashboardResponse,
    HealthResponse,
    VersionResponse,
    DuplicateItemResponse,
    EstimateRequest,
    EstimateResponse,
    ExportFormat,
    ExportRequest,
    ExportScope,
    EvidenceStatus,
    Freshness,
    InputType,
    JobActionAcceptedResponse,
    JobActionEstimateResponse,
    JobActionRequest,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
    LiveStatus,
    MdiError,
    MdiJobOptions,
    MdiJobStatus,
    MdiProcessingStatus,
    MdiResultItem,
    ParsePreviewRequest,
    ParsePreviewResponse,
    RecommendedAction,
    RefreshScanScope,
    RejectedItemResponse,
    TriageBucket,
    TriageConfidence,
    UploadPreviewResponse,
    UploadedInputItem,
    VtModeUsed,
)
from services.age_bucket import parse_date_string
from services.build_info import APP_VERSION, load_build_info
from services.vt_quota import get_usage_summary
from services.input_parser import parse_raw_input
from services.upload_parser import parse_upload
from services.job_store import (
    InMemoryJob, create_job, get_job,
    get_latest_completed_job_sync, register_recovered_job,
)
from services import dashboard, export_service, job_actions, job_persistence, job_processor, vt_service
from services.job_store import InMemoryJob
from services.quota_lock import QuotaLockTimeout
from services.quota_writer import read_remaining_quota
from services.estimate import estimate_job, partition_upload_items, upload_item_has_hold

router = APIRouter(prefix="/api/mdi")


# ── Health ─────────────────────────────────────────────────────────────────────

@router.get("/health", tags=["Health"], response_model=HealthResponse)
async def health() -> HealthResponse:
    """Service liveness check. No external calls."""
    return HealthResponse(
        status="ok",
        service="mdi",
        version=APP_VERSION,
        build_info=load_build_info(),
    )


@router.get("/version", tags=["Health"], response_model=VersionResponse)
async def version() -> VersionResponse:
    """Deploy build identity for production audits. No external calls."""
    return VersionResponse(build_info=load_build_info())


# ── Usage ──────────────────────────────────────────────────────────────────────

@router.get("/usage", tags=["Quota"])
async def usage() -> Dict[str, Any]:
    """
    Read current shared VT quota state from the filesystem.

    Reads /var/lib/dns-tool/vt_usage.json (or VT_USAGE_FILE env var).
    Does NOT mutate any file.  Both MDI and VirusTotal Bulk Check read the
    same file, so the counter reflects combined usage from both tools.

    Returns:
      date_utc           — UTC date the counter applies to
      daily_lookups_used — API calls consumed today across both tools
      daily_limit        — maximum daily lookups (500)
      remaining          — lookups still available
      rate_limit_per_min — VT free-tier rate limit (4/min)
      source             — resolved file path
      shared_with        — list of tool names sharing this counter
      mutated            — always false for this endpoint
      error              — null on success; error description if file is missing/malformed
    """
    return get_usage_summary()


# ── Parse preview ─────────────────────────────────────────────────────────────

@router.post("/jobs/parse-preview", tags=["Input"], response_model=ParsePreviewResponse)
async def parse_preview(req: ParsePreviewRequest) -> ParsePreviewResponse:
    """
    Parse raw pasted input and return normalized items without running any checks.

    No external calls are made.  No VT, WHOIS, DNS, or URL activity lookups.
    No quota is consumed.  No job is created.  No runtime files are written.

    Use this endpoint to preview what MDI will accept before submitting a real job.
    """
    result = parse_raw_input(
        req.raw_input,
        default_scheme=req.default_scheme,
        max_items=req.max_items,
    )
    return ParsePreviewResponse(
        accepted_count=len(result.accepted),
        rejected_count=len(result.rejected),
        duplicate_count=len(result.duplicates),
        items=result.accepted,
        rejected=[
            RejectedItemResponse(
                input_original=r.input_original,
                position=r.position,
                error=r.error,
            )
            for r in result.rejected
        ],
        duplicates=[
            DuplicateItemResponse(
                input_original=d.input_original,
                position=d.position,
                duplicate_of=d.duplicate_of,
            )
            for d in result.duplicates
        ],
        external_calls_made=False,
        quota_consumed=False,
    )


# ── Upload preview ─────────────────────────────────────────────────────────────

@router.post("/jobs/upload-preview", tags=["Input"], response_model=UploadPreviewResponse)
async def upload_preview(
    file: UploadFile = File(..., description="CSV or XLSX file to parse."),
    default_scheme: str = Form("http", pattern=r"^https?$"),
    max_items: int = Form(500, ge=1, le=500),
) -> UploadPreviewResponse:
    """
    Parse a CSV or XLSX file upload and return normalized items with hold detection.

    Extracts domain, create date, EPP/domain status, registrar, and nameservers
    when the corresponding columns are present.  clientHold and serverHold are
    detected offline from the uploaded status column — no WHOIS/RDAP calls are made.

    No external calls are made.  No VT, WHOIS, DNS, or URL activity lookups.
    No quota is consumed.  No job is created.  Uploaded file bytes are not persisted.
    """
    file_bytes = await file.read()
    filename = file.filename or "upload.csv"

    result = parse_upload(
        file_bytes,
        filename,
        default_scheme=default_scheme,
        max_items=max_items,
    )
    held_items = [item for item in result.accepted if item.domain_hold.has_hold]
    held_skipped_count = len(held_items)

    return UploadPreviewResponse(
        accepted_count=len(result.accepted),
        rejected_count=len(result.rejected),
        duplicate_count=len(result.duplicates),
        held_count=held_skipped_count,
        held_skipped_count=held_skipped_count,
        items=result.accepted,
        rejected=result.rejected,
        duplicates=result.duplicates,
        held_items=held_items,
        columns_detected=result.columns_detected,
        missing_optional_columns=result.missing_optional_columns,
        header_row=result.header_row,
        source_sheet=result.source_sheet,
        external_calls_made=False,
        quota_consumed=False,
    )


# ── Estimate endpoint ──────────────────────────────────────────────────────────

@router.post("/jobs/estimate", tags=["Jobs"], response_model=EstimateResponse)
async def estimate(req: EstimateRequest) -> EstimateResponse:
    """
    Return a quota and runtime estimate for pasted or upload-validated input.

    Paste mode parses raw_input. Upload mode uses pre-validated items from
    upload-preview (held domains excluded from VT estimate).

    No external calls. No quota consumed. No job created. No runtime writes.
    """
    if req.items:
        accepted = list(req.items)
        rejected: list = []
        duplicates: list = []
        eligible_items, held_skipped_count = partition_upload_items(accepted)
    else:
        parse_result = parse_raw_input(
            req.raw_input or "",
            default_scheme=req.default_scheme,
            max_items=req.max_items,
        )
        accepted = parse_result.accepted
        rejected = parse_result.rejected
        duplicates = parse_result.duplicates
        eligible_items = accepted
        held_skipped_count = 0

    est = estimate_job(
        eligible_items,
        req.use_domain_reports,
        auto_rescan_stale=req.auto_rescan_stale,
        max_auto_rescans=req.max_auto_rescans,
    )
    try:
        remaining = read_remaining_quota()
    except QuotaLockTimeout:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "quota_lock_timeout",
                "message": "Shared quota lock unavailable; try again shortly.",
            },
        )
    calls_max = est["estimated_vt_calls_max"]
    total_max = est["total_estimated_vt_calls_max"]
    headroom = remaining - total_max

    return EstimateResponse(
        accepted_count=len(accepted),
        rejected_count=len(rejected),
        duplicate_count=len(duplicates),
        eligible_vt_count=len(eligible_items),
        held_skipped_count=held_skipped_count,
        domain_count=est["domain_count"],
        url_count=est["url_count"],
        domain_report_mode_count=est["domain_report_mode_count"],
        url_report_mode_count=est["url_report_mode_count"],
        estimated_vt_calls_min=est["estimated_vt_calls_min"],
        estimated_vt_calls_max=calls_max,
        auto_rescan_estimated_quota_min=est["auto_rescan_estimated_quota_min"],
        auto_rescan_estimated_quota_max=est["auto_rescan_estimated_quota_max"],
        auto_rescan_domain_eligible_max=est["auto_rescan_domain_eligible_max"],
        auto_rescan_url_eligible_max=est["auto_rescan_url_eligible_max"],
        total_estimated_vt_calls_max=total_max,
        auto_rescan_estimated_duration_seconds_min=est["auto_rescan_estimated_duration_seconds_min"],
        auto_rescan_estimated_duration_seconds_max=est["auto_rescan_estimated_duration_seconds_max"],
        auto_rescan_note=est["auto_rescan_note"],
        estimated_enrichment_lookups=est["estimated_enrichment_lookups"],
        estimated_enrichment_duration_seconds_min=est["estimated_enrichment_duration_seconds_min"],
        estimated_enrichment_duration_seconds_max=est["estimated_enrichment_duration_seconds_max"],
        quota_remaining_now=remaining,
        will_exceed_quota=total_max > remaining,
        quota_headroom=headroom,
        estimated_duration_seconds_min=est["estimated_duration_seconds_min"],
        estimated_duration_seconds_max=(
            est["estimated_duration_seconds_max"]
            + est["auto_rescan_estimated_duration_seconds_max"]
        ),
        rate_limit_note=est["rate_limit_note"],
        job_state_note=est["job_state_note"],
        enrichment_note=est["enrichment_note"],
        enrichment_warning=est["enrichment_warning"],
        url_submit_note=est["url_submit_note"],
        estimated_live_check_count=est["estimated_live_check_count"],
        live_check_note=est["live_check_note"],
        external_calls_made=False,
        quota_consumed=False,
        mutated=False,
        rejected=[
            RejectedItemResponse(
                input_original=r.input_original,
                position=r.position,
                error=r.error,
            )
            for r in rejected
        ],
        duplicates=[
            DuplicateItemResponse(
                input_original=d.input_original,
                position=d.position,
                duplicate_of=d.duplicate_of,
            )
            for d in duplicates
        ],
    )


# ── Job submit ─────────────────────────────────────────────────────────────────

def _estimate_requests(
    items: list,
    use_domain_reports: bool,
    *,
    auto_rescan_stale: bool = False,
    max_auto_rescans: int = 3,
) -> int:
    """
    Conservative (max) VT API call estimate for the submit flow.
    Delegates to the shared estimate_job helper to guarantee parity with
    the /estimate endpoint.
    """
    return estimate_job(
        items,
        use_domain_reports,
        auto_rescan_stale=auto_rescan_stale,
        max_auto_rescans=max_auto_rescans,
    )["total_estimated_vt_calls_max"]


def _upload_created_at_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    parsed = parse_date_string(raw)
    if parsed is None:
        return None
    return datetime.combine(parsed, datetime.min.time())


def _result_from_upload_item(item: UploadedInputItem, *, held: bool) -> MdiResultItem:
    """Build an initial MdiResultItem preserving upload metadata."""
    created_dt = _upload_created_at_dt(item.created_at)
    common = dict(
        input_original=item.input_original,
        input_normalized=item.input_normalized,
        input_type=item.input_type,
        position=item.position,
        registrar=item.registrar,
        epp_status=list(item.epp_status or []),
        nameservers=list(item.assigned_nameservers or []),
        age_bucket=item.age_bucket,
        domain_hold=item.domain_hold,
    )
    if created_dt is not None:
        common["created_at"] = created_dt
    if held:
        return MdiResultItem(
            **common,
            processing_status=MdiProcessingStatus.HOLD_SKIPPED,
            vt_mode_used=VtModeUsed.SKIPPED_HOLD,
            triage_bucket=item.triage_bucket,
            triage_confidence=item.triage_confidence,
            recommended_action=item.recommended_action,
            evidence_status=EvidenceStatus.SKIPPED_HOLD,
            live_status=LiveStatus.NOT_CHECKED,
        )
    return MdiResultItem(
        **common,
        processing_status=MdiProcessingStatus.PENDING,
    )


def _make_pending_result(item, input_type: InputType) -> MdiResultItem:
    if isinstance(item, UploadedInputItem):
        return _result_from_upload_item(item, held=False)
    return MdiResultItem(
        input_original=item.input_original,
        input_normalized=item.input_normalized,
        input_type=input_type,
        position=item.position,
        processing_status=MdiProcessingStatus.PENDING,
    )


def _make_hold_skipped_result(item, input_type: InputType) -> MdiResultItem:
    if isinstance(item, UploadedInputItem):
        return _result_from_upload_item(item, held=True)
    return MdiResultItem(
        input_original=item.input_original,
        input_normalized=item.input_normalized,
        input_type=input_type,
        position=item.position,
        processing_status=MdiProcessingStatus.HOLD_SKIPPED,
        domain_hold=DomainHold(
            has_hold=True,
            hold_types=[DomainHoldType.CLIENT_HOLD],
            source=DomainStatusSource.UNKNOWN,
        ),
        vt_mode_used=VtModeUsed.SKIPPED_HOLD,
        triage_bucket=TriageBucket.HELD,
        triage_confidence=TriageConfidence.HIGH,
        recommended_action=RecommendedAction.ACTION_ALREADY_TAKEN,
        evidence_status=EvidenceStatus.SKIPPED_HOLD,
        live_status=LiveStatus.NOT_CHECKED,
    )


@router.post("/jobs/submit", tags=["Jobs"], response_model=JobSubmitResponse)
async def submit_job(req: JobSubmitRequest) -> JobSubmitResponse:
    """
    Submit a VT-check job from pasted text or upload-validated items.

    Upload mode uses items from upload-preview; held domains skip VT/live checks.
    Paste mode parses raw_input; hold status is unknown until enrichment runs.

    No external calls during submission; VT calls happen in the background task.
    """
    if req.items:
        accepted = list(req.items)
        rejected_count = 0
        eligible_items, held_skipped_count = partition_upload_items(accepted)
        held_items = [i for i in accepted if upload_item_has_hold(i)]
    else:
        if not req.raw_input or not req.raw_input.strip():
            raise HTTPException(
                status_code=422,
                detail="raw_input is required. At least one domain or URL must be provided.",
            )
        parse_result = parse_raw_input(
            req.raw_input or "",
            default_scheme=req.default_scheme,
            max_items=req.max_items,
        )
        accepted = parse_result.accepted
        rejected_count = len(parse_result.rejected)
        held_items = []
        eligible_items = accepted

    held_skipped_count = len(held_items)
    estimated = _estimate_requests(
        eligible_items,
        req.use_domain_reports,
        auto_rescan_stale=req.auto_rescan_stale,
        max_auto_rescans=req.max_auto_rescans,
    )
    try:
        remaining = read_remaining_quota()
    except QuotaLockTimeout:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "quota_lock_timeout",
                "message": "Shared quota lock unavailable; try again shortly.",
            },
        )

    if estimated > remaining:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_blocked",
                "message": (
                    f"Estimated {estimated} VT API requests required (including auto-rescan "
                    f"worst-case) but only {remaining} remain today. Reduce input size, "
                    "disable auto-rescan, or wait until tomorrow."
                ),
                "estimated_requests": estimated,
                "quota_remaining": remaining,
            },
        )

    job_id = str(uuid.uuid4())
    job = InMemoryJob(
        job_id=job_id,
        status="queued",
        submitted_at=time.time(),
        total=len(eligible_items),
        processed=0,
        held_skipped=held_skipped_count,
        rejected_count=rejected_count,
        estimated_requests=estimated,
        use_domain_reports=req.use_domain_reports,
        stale_threshold_days=req.stale_threshold_days,
        auto_rescan_stale=req.auto_rescan_stale,
        max_auto_rescans=req.max_auto_rescans,
        input_mode=req.input_mode,
        cloudflare_rank_lookup_enabled=req.cloudflare_rank_lookup_enabled,
    )

    for item in held_items:
        job.results[item.input_normalized] = _make_hold_skipped_result(item, item.input_type)
        job.item_order.append(item.input_normalized)

    for item in eligible_items:
        job.results[item.input_normalized] = _make_pending_result(item, item.input_type)
        job.item_order.append(item.input_normalized)

    await create_job(job)
    asyncio.create_task(job_processor.process_job(job_id))

    return JobSubmitResponse(
        job_id=job_id,
        status="queued",
        total=len(eligible_items),
        queued_count=len(eligible_items),
        held_skipped_count=held_skipped_count,
        rejected_count=rejected_count,
        estimated_requests=estimated,
        quota_remaining_before=remaining,
    )


# ── Job status builder ─────────────────────────────────────────────────────────

def _build_job_status_response(job: InMemoryJob) -> JobStatusResponse:
    queued = sum(
        1 for r in job.results.values()
        if r.processing_status == MdiProcessingStatus.PENDING
    )
    results_ordered = [
        job.results[k] for k in job.item_order if k in job.results
    ]
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        submitted_at=job.submitted_at,
        completed_at=job.completed_at,
        total=job.total,
        processed=job.processed,
        held_skipped=job.held_skipped,
        rejected_count=job.rejected_count,
        queued=queued,
        estimated_requests=job.estimated_requests,
        lookups_used=job.lookups_used,
        quota_blocked_count=job.quota_blocked_count,
        quota_lock_timeout_count=job.quota_lock_timeout_count,
        error_message=job.error_message,
        use_domain_reports=job.use_domain_reports,
        stale_threshold_days=job.stale_threshold_days,
        cloudflare_rank_lookup_enabled=job.cloudflare_rank_lookup_enabled,
        results=results_ordered,
        rdap_enriched_count=job.rdap_enriched_count,
        rdap_failed_count=job.rdap_failed_count,
        whois_fallback_count=job.whois_fallback_count,
        hold_detected_by_enrichment_count=job.hold_detected_by_enrichment_count,
        live_check_count=job.live_check_count,
        live_check_skipped_count=job.live_check_skipped_count,
        live_check_error_count=job.live_check_error_count,
        action_in_progress=job.action_in_progress,
        last_action_type=job.last_action_type,
        last_action_at=job.last_action_at,
        current_phase=job.current_phase,
        current_phase_detail=job.current_phase_detail,
        vt_refresh_count=job.vt_refresh_count,
        vt_scan_requested_count=job.vt_scan_requested_count,
        vt_scan_failed_count=job.vt_scan_failed_count,
        auto_rescan_stale=job.auto_rescan_stale,
        max_auto_rescans=job.max_auto_rescans,
        input_mode=job.input_mode,
        auto_rescan_attempted_count=job.auto_rescan_attempted_count,
        auto_rescan_completed_count=job.auto_rescan_completed_count,
        auto_rescan_failed_count=job.auto_rescan_failed_count,
        auto_rescan_skipped_count=job.auto_rescan_skipped_count,
        auto_rescan_quota_blocked_count=job.auto_rescan_quota_blocked_count,
    )


async def _handle_job_action(
    job_id: str,
    action: str,
    req: JobActionRequest,
) -> JobActionEstimateResponse | JobActionAcceptedResponse:
    """Shared handler for refresh and scan endpoints."""
    job = await job_actions.resolve_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    block_reason = job_actions.validate_job_for_action(job)
    if block_reason:
        raise HTTPException(status_code=409, detail=block_reason)

    if req.scope == RefreshScanScope.SELECTED and not req.positions:
        raise HTTPException(
            status_code=422,
            detail="positions is required when scope is 'selected'.",
        )

    estimate = job_actions.estimate_action(job, action, req)
    if req.estimate_only:
        return estimate

    if action == "scan" and not req.confirm:
        raise HTTPException(
            status_code=422,
            detail="confirm=true is required to start a scan action.",
        )

    if estimate.eligible_count == 0:
        raise HTTPException(status_code=422, detail=estimate.message)

    if estimate.will_exceed_quota:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_blocked",
                "message": estimate.message,
                "estimated_quota_max": estimate.estimated_quota_max,
                "quota_remaining": estimate.quota_remaining,
            },
        )

    if action == "refresh":
        job_actions.start_refresh_action(job_id, req)
    else:
        job_actions.start_scan_action(job_id, req)

    return JobActionAcceptedResponse(
        job_id=job_id,
        action=action,
        status="accepted",
        items_queued=estimate.eligible_count,
        items_skipped=estimate.skipped_count,
        estimated_quota_min=estimate.estimated_quota_min,
        estimated_quota_max=estimate.estimated_quota_max,
        quota_remaining=estimate.quota_remaining,
    )


@router.post(
    "/jobs/{job_id}/refresh",
    tags=["Jobs"],
    response_model=JobActionAcceptedResponse | JobActionEstimateResponse,
)
async def refresh_job(job_id: str, req: JobActionRequest):
    """
    Refresh existing VT reports for selected, stale, or pending-analysis rows (GET only).

    Updates the existing job in-place. No new job_id. Uses saved job options.
    scope=pending (MDI-57B) refreshes all pending-analysis URL rows; no submit.
    """
    return await _handle_job_action(job_id, "refresh", req)


@router.post(
    "/jobs/{job_id}/scan",
    tags=["Jobs"],
    response_model=JobActionAcceptedResponse | JobActionEstimateResponse,
)
async def scan_job(job_id: str, req: JobActionRequest):
    """
    Request new VT scans for selected or stale rows (POST + bounded poll).

    Domain-report mode items are skipped. Requires confirm=true.
    """
    return await _handle_job_action(job_id, "scan", req)


@router.post("/jobs/{job_id}/export", tags=["Jobs"])
async def export_job(job_id: str, req: ExportRequest) -> Response:
    """
    Export job results as CSV, XLSX, or JSON evidence (in-memory download only).

    Allowed only when job status is done or error. No VT/RDAP/live calls.
    No quota consumed. No usage history append. No server-side file write.
    """
    job = await job_actions.resolve_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    block_reason = export_service.validate_job_for_export(job)
    if block_reason:
        raise HTTPException(status_code=422, detail=export_service.export_error_detail(block_reason))

    rows, selection_error = export_service.select_export_rows(job, req)
    if selection_error:
        raise HTTPException(status_code=422, detail=export_service.export_error_detail(selection_error))

    if req.format == ExportFormat.CSV:
        content = export_service.build_csv_export(job, rows, req.scope)
        filename = export_service.build_export_filename("csv", req.scope, req.positions)
        media_type = "text/csv; charset=utf-8"
    elif req.format == ExportFormat.XLSX:
        content = export_service.build_xlsx_export(job, rows, req.scope)
        filename = export_service.build_export_filename("xlsx", req.scope, req.positions)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        content = export_service.build_evidence_json_export(
            job, rows, req.scope, req.positions
        )
        filename = export_service.build_export_filename("json", req.scope, req.positions)
        media_type = "application/json; charset=utf-8"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Latest job recovery ────────────────────────────────────────────────────────

@router.get("/jobs/latest", tags=["Jobs"], response_model=JobStatusResponse)
async def latest_job() -> JobStatusResponse:
    """
    Return the latest completed or errored MDI job for page-refresh/restart recovery.

    Lookup order:
      1. In-memory store — if a completed/error job exists, return it directly.
         No disk read needed while the same process is still running.
      2. Disk — read /var/lib/dns-tool/mdi_latest_job.json (or MDI_LATEST_JOB_FILE).
         If found: register the job back into the in-memory store so subsequent
         GET /api/mdi/jobs/{job_id} calls also work.
      3. Not found — HTTP 404.

    Hard guarantees:
      - No VT calls.
      - No job creation.
      - No quota consumed.
      - No usage history appended.
      - Corrupt or missing recovery file → 404, never a crash.
    """
    # 1. Check in-memory store first
    job = get_latest_completed_job_sync()

    # 2. Fall back to disk recovery
    if job is None:
        job = job_persistence.read_latest_job()
        if job is not None:
            register_recovered_job(job)

    # 3. Nothing available
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="No recovered job found. Submit a new job to begin.",
        )

    return _build_job_status_response(job)


# ── Job status ─────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}", tags=["Jobs"], response_model=JobStatusResponse)
async def job_status(job_id: str) -> JobStatusResponse:
    """
    Return current status and results for an in-memory MDI job.

    Jobs are stored in-memory only. After service restart, all jobs are lost
    (MDI-06 known limitation; job recovery is out of scope).
    """
    job = await job_actions.resolve_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    return _build_job_status_response(job)


# ── Operational dashboard (MDI-17) ─────────────────────────────────────────────

@router.get("/dashboard", tags=["Dashboard"], response_model=DashboardResponse)
async def operational_dashboard(
    source: str = Query(
        "mdi",
        description="Source filter: all (All VT Tools), mdi (MDI Only), vt_bulk_check (VT Bulk Check Only). Default mdi preserves prior behavior.",
    ),
) -> DashboardResponse:
    """
    Return metadata-only operational dashboard for all time windows.

    Reads vt_usage_history.jsonl and optional vt_daily_history.json read-only.
    Current Job window uses in-memory or recovered latest job aggregates only.
    No writes. No external calls. No quota consumed.
    """
    job = get_latest_completed_job_sync()
    if job is None:
        recovered = job_persistence.read_latest_job()
        if recovered is not None:
            register_recovered_job(recovered)
            job = recovered

    summary = dashboard.build_dashboard_summary(current_job=job, source_filter=source)
    return DashboardResponse(**summary)


# ── Schema summary ─────────────────────────────────────────────────────────────

def _enum_values(enum_cls: type) -> List[str]:
    return [e.value for e in enum_cls]  # type: ignore[attr-defined]


@router.get("/schema-summary", tags=["Development"])
async def schema_summary() -> Dict[str, Any]:
    """
    Return a concise summary of MDI enum values and top-level model fields.

    Intended for development verification only — confirms the backend model
    is wired correctly.  No external calls.  No runtime file access.
    """
    return {
        "enums": {
            "InputType": _enum_values(InputType),
            "MdiJobStatus": _enum_values(MdiJobStatus),
            "MdiProcessingStatus": _enum_values(MdiProcessingStatus),
            "DomainHoldType": _enum_values(DomainHoldType),
            "DomainStatusSource": _enum_values(DomainStatusSource),
            "VtModeUsed": _enum_values(VtModeUsed),
            "Freshness": _enum_values(Freshness),
            "LiveStatus": _enum_values(LiveStatus),
            "AgeBucket": _enum_values(AgeBucket),
            "TriageBucket": _enum_values(TriageBucket),
            "TriageConfidence": _enum_values(TriageConfidence),
            "RecommendedAction": _enum_values(RecommendedAction),
            "EvidenceStatus": _enum_values(EvidenceStatus),
        },
        "models": {
            "MdiJobOptions": list(MdiJobOptions.model_fields.keys()),
            "UploadedInputItem_top_fields": [
                "input_original", "input_normalized", "input_type", "position",
                "created_at", "registrar", "epp_status", "assigned_nameservers",
                "domain_hold", "domain_status_source", "age_bucket",
                "triage_bucket", "recommended_action", "triage_confidence",
                "evidence_status", "vt_mode_used", "live_status",
            ],
            "MdiResultItem_top_fields": [
                "input_original",
                "input_normalized",
                "input_type",
                "position",
                "processing_status",
                "domain_hold",
                "registrar",
                "created_at",
                "age_bucket",
                "epp_status",
                "vt_mode_used",
                "vt_hits",
                "vt_suspicious",
                "vt_total_engines",
                "vt_ratio",
                "vt_scan_date",
                "freshness",
                "live_status",
                "triage_bucket",
                "triage_reason",
                "triage_confidence",
                "recommended_action",
                "evidence_status",
                "errors",
            ],
        },
        "constants": {
            "DAILY_LOOKUPS_LIMIT": 500,
            "RATE_LIMIT_PER_MIN": 4,
            "MAX_AUTO_RESCANS_PER_RUN": 25,
            "AUTO_RESCAN_THRESHOLD_DAYS": 7,
            "STALE_THRESHOLD_DAYS": vt_service.DEFAULT_STALE_THRESHOLD_DAYS,
        },
    }
