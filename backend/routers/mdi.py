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

Future endpoints (not yet implemented):
  GET  /api/mdi/jobs/{job_id}/export
  POST /api/mdi/jobs/{job_id}/rescan
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from models import (
    AgeBucket,
    DomainHold,
    DomainHoldType,
    DomainStatusSource,
    DuplicateItemResponse,
    EvidenceStatus,
    Freshness,
    InputType,
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
    RejectedItemResponse,
    TriageBucket,
    TriageConfidence,
    UploadPreviewResponse,
    VtModeUsed,
)
from services.vt_quota import get_usage_summary
from services.input_parser import parse_raw_input
from services.upload_parser import parse_upload
from services.job_store import InMemoryJob, create_job, get_job
from services import job_processor
from services.quota_writer import read_remaining_quota

router = APIRouter(prefix="/api/mdi")


# ── Health ─────────────────────────────────────────────────────────────────────

@router.get("/health", tags=["Health"])
async def health() -> Dict[str, str]:
    """Service liveness check. No external calls."""
    return {"status": "ok", "service": "mdi", "version": "shell"}


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

    return UploadPreviewResponse(
        accepted_count=len(result.accepted),
        rejected_count=len(result.rejected),
        duplicate_count=len(result.duplicates),
        held_count=len(held_items),
        items=result.accepted,
        rejected=result.rejected,
        duplicates=result.duplicates,
        held_items=held_items,
        columns_detected=result.columns_detected,
        missing_optional_columns=result.missing_optional_columns,
        external_calls_made=False,
        quota_consumed=False,
    )


# ── Job submit ─────────────────────────────────────────────────────────────────

def _estimate_requests(items: list, use_domain_reports: bool) -> int:
    """
    Conservative VT API call estimate:
      - domain report mode:  1 call per domain item
      - URL report mode:     3 calls per item (GET + possible POST submit + GET again)
    """
    total = 0
    for item in items:
        if item.input_type == InputType.DOMAIN and use_domain_reports:
            total += 1
        else:
            total += 3
    return total


def _make_pending_result(item, input_type: InputType) -> MdiResultItem:
    return MdiResultItem(
        input_original=item.input_original,
        input_normalized=item.input_normalized,
        input_type=input_type,
        position=item.position,
        processing_status=MdiProcessingStatus.PENDING,
    )


def _make_hold_skipped_result(item, input_type: InputType) -> MdiResultItem:
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
    Submit a VT-check job from raw pasted input.

    Processing steps:
      1. Parse raw_input via input_parser.
      2. Filter items with confirmed hold (has_hold=True) — they skip VT.
         Items with unknown hold status are eligible for VT.
      3. Estimate VT API quota required (conservative: URL-mode = 3, domain-mode = 1).
      4. If estimated > remaining quota: reject with quota_blocked response (HTTP 429).
      5. Create in-memory job, launch background asyncio task, return job_id.

    No external calls are made during submission; VT calls happen in the background task.
    """
    if not req.raw_input:
        raise HTTPException(
            status_code=422,
            detail="raw_input is required. At least one domain or URL must be provided.",
        )

    parse_result = parse_raw_input(
        req.raw_input,
        default_scheme=req.default_scheme,
        max_items=req.max_items,
    )

    accepted = parse_result.accepted
    rejected_count = len(parse_result.rejected)

    # Separate confirmed-held from eligible
    held_items = [i for i in accepted if getattr(i, "domain_hold", None) and i.domain_hold.has_hold]  # type: ignore[attr-defined]
    eligible_items = [i for i in accepted if i not in held_items]

    # For MdiInputItem from parse_raw_input, hold status is NOT_CHECKED (no hold data yet).
    # So all items from raw paste are eligible for VT (none are confirmed held at submit time).
    # held_items will be empty for paste input; held filtering in MDI-06 is via the pre-populated
    # held results pattern (from upload). For paste input, all accepted items go to VT queue.
    # NOTE: If a future endpoint provides pre-populated UploadedInputItem with has_hold=True,
    # those will be correctly filtered here.
    held_items = []
    eligible_items = accepted

    held_skipped_count = len(held_items)
    estimated = _estimate_requests(eligible_items, req.use_domain_reports)
    remaining = read_remaining_quota()

    if estimated > remaining:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_blocked",
                "message": (
                    f"Estimated {estimated} VT API requests required but only "
                    f"{remaining} remain today. Reduce input size or wait until tomorrow."
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
    )

    # Pre-populate results: held items first, then pending eligible items
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


# ── Job status ─────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}", tags=["Jobs"], response_model=JobStatusResponse)
async def job_status(job_id: str) -> JobStatusResponse:
    """
    Return current status and results for an in-memory MDI job.

    Jobs are stored in-memory only. After service restart, all jobs are lost
    (MDI-06 known limitation; job recovery is out of scope).
    """
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    queued = sum(
        1 for r in job.results.values()
        if r.processing_status == MdiProcessingStatus.PENDING
    )
    results_ordered = [
        job.results[k]
        for k in job.item_order
        if k in job.results
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
        error_message=job.error_message,
        use_domain_reports=job.use_domain_reports,
        stale_threshold_days=job.stale_threshold_days,
        results=results_ordered,
    )


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
            "STALE_THRESHOLD_DAYS": 5,
        },
    }
