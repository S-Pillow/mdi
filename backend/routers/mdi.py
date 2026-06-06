"""
MDI API router — /api/mdi/* endpoints.

MDI-03 endpoints:
  GET /api/mdi/health          — service liveness check
  GET /api/mdi/usage           — read shared VT quota state (read-only)
  GET /api/mdi/schema-summary  — enum/field summary for development verification

Future endpoints (not yet implemented):
  POST /api/mdi/jobs/submit
  GET  /api/mdi/jobs/{job_id}
  GET  /api/mdi/jobs/{job_id}/export
  POST /api/mdi/jobs/{job_id}/rescan
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from models import (
    AgeBucket,
    DomainHoldType,
    DomainStatusSource,
    DuplicateItemResponse,
    EvidenceStatus,
    Freshness,
    InputType,
    LiveStatus,
    MdiJobOptions,
    MdiJobStatus,
    MdiProcessingStatus,
    ParsePreviewRequest,
    ParsePreviewResponse,
    RecommendedAction,
    RejectedItemResponse,
    TriageBucket,
    TriageConfidence,
    VtModeUsed,
)
from services.vt_quota import get_usage_summary
from services.input_parser import parse_raw_input

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
