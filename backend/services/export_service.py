"""
MDI export service — read-only CSV and JSON evidence downloads (MDI-16).

Generates exports in memory only. No VT/RDAP/WHOIS/DNS/live calls.
No runtime file writes. No usage history append.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from models import (
    ExportFormat,
    ExportRequest,
    ExportScope,
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
    TriageBucket,
)
from services.job_store import InMemoryJob

CSV_HEADERS: List[str] = [
    "position",
    "input_original",
    "input_normalized",
    "input_type",
    "processing_status",
    "triage_bucket",
    "triage_confidence",
    "recommended_action",
    "evidence_status",
    "vt_hits",
    "vt_suspicious",
    "vt_total_engines",
    "vt_ratio",
    "freshness",
    "vt_scan_date",
    "live_status",
    "http_status_code",
    "redirect_count",
    "created_at",
    "age_bucket",
    "registrar",
    "domain_status_source",
    "domain_hold_has_hold",
    "domain_hold_source",
    "triage_reason",
    "error_codes",
]

_INJECTION_FIRST_CHARS = frozenset("=+-@")
_SCHEMA_VERSION = "mdi-evidence-v1"


def validate_job_for_export(job: InMemoryJob) -> Optional[str]:
    """Return error detail if job cannot be exported, else None."""
    if job.action_in_progress:
        return "action_in_progress"
    if job.status in ("queued", "running"):
        return f"Job status '{job.status}' does not allow export."
    if job.status not in ("done", "error"):
        return f"Job status '{job.status}' does not allow export."
    return None


def _ordered_results(job: InMemoryJob) -> List[MdiResultItem]:
    order = job.item_order or list(job.results.keys())
    return [job.results[key] for key in order if key in job.results]


def _is_held(result: MdiResultItem) -> bool:
    return (
        result.processing_status == MdiProcessingStatus.HOLD_SKIPPED
        or bool(result.domain_hold and result.domain_hold.has_hold)
    )


def is_export_flagged(result: MdiResultItem) -> bool:
    """Flagged rows for export: malicious/suspicious bucket or VT hits/suspicious."""
    if _is_held(result):
        return False
    if result.triage_bucket in (TriageBucket.MALICIOUS, TriageBucket.SUSPICIOUS):
        return True
    if (result.vt_hits or 0) > 0 or (result.vt_suspicious or 0) > 0:
        return True
    return False


def select_export_rows(
    job: InMemoryJob,
    request: ExportRequest,
) -> Tuple[List[MdiResultItem], Optional[str]]:
    """
    Select rows for export by scope.

    positions is ignored for all/flagged scopes.
    Returns (rows, error_detail) where error_detail is set when selection fails.
    """
    all_rows = _ordered_results(job)

    if request.scope == ExportScope.ALL:
        if not all_rows:
            return [], "no_results"
        return all_rows, None

    if request.scope == ExportScope.FLAGGED:
        flagged = [row for row in all_rows if is_export_flagged(row)]
        if not flagged:
            return [], "no_flagged_rows"
        return flagged, None

    positions = request.positions or []
    if not positions:
        return [], "positions is required when scope is 'selected'."

    valid_positions = {row.position for row in all_rows}
    invalid = sorted({pos for pos in positions if pos not in valid_positions})
    if invalid:
        return [], f"Invalid positions: {invalid}"

    pos_set = set(positions)
    selected = [row for row in all_rows if row.position in pos_set]
    if not selected:
        return [], "No rows match the requested positions."
    return selected, None


def sanitize_csv_cell(value: Any) -> str:
    """Format a cell for CSV and mitigate formula injection."""
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, datetime):
        text = value.isoformat()
    elif hasattr(value, "value"):
        text = str(getattr(value, "value"))
    else:
        text = str(value)

    if not text:
        return text
    first = text[0]
    if first in _INJECTION_FIRST_CHARS or first == "\t" or first == "\r":
        return "'" + text
    return text


def _enum_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "value"):
        return value.value
    return value


def _result_csv_row(result: MdiResultItem) -> List[str]:
    hold = result.domain_hold
    hold_source = _enum_value(hold.source) if hold else ""
    return [
        sanitize_csv_cell(result.position),
        sanitize_csv_cell(result.input_original),
        sanitize_csv_cell(result.input_normalized),
        sanitize_csv_cell(_enum_value(result.input_type)),
        sanitize_csv_cell(_enum_value(result.processing_status)),
        sanitize_csv_cell(_enum_value(result.triage_bucket)),
        sanitize_csv_cell(_enum_value(result.triage_confidence)),
        sanitize_csv_cell(_enum_value(result.recommended_action)),
        sanitize_csv_cell(_enum_value(result.evidence_status)),
        sanitize_csv_cell(result.vt_hits),
        sanitize_csv_cell(result.vt_suspicious),
        sanitize_csv_cell(result.vt_total_engines),
        sanitize_csv_cell(result.vt_ratio),
        sanitize_csv_cell(_enum_value(result.freshness)),
        sanitize_csv_cell(result.vt_scan_date),
        sanitize_csv_cell(_enum_value(result.live_status)),
        sanitize_csv_cell(result.http_status_code),
        sanitize_csv_cell(result.redirect_count),
        sanitize_csv_cell(result.created_at),
        sanitize_csv_cell(_enum_value(result.age_bucket)),
        sanitize_csv_cell(result.registrar),
        sanitize_csv_cell(hold_source),
        sanitize_csv_cell(hold.has_hold if hold else False),
        sanitize_csv_cell(hold_source),
        sanitize_csv_cell(" | ".join(result.triage_reason)),
        sanitize_csv_cell(" | ".join(err.code for err in result.errors)),
    ]


def build_csv_export(
    job: InMemoryJob,
    rows: List[MdiResultItem],
    scope: ExportScope,
) -> str:
    """Build UTF-8 CSV string with stable headers."""
    del job, scope  # reserved for future metadata rows
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_HEADERS)
    for row in rows:
        writer.writerow(_result_csv_row(row))
    return buffer.getvalue()


def safe_timestamp_for_filename() -> str:
    """UTC timestamp safe for Content-Disposition filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def build_export_filename(
    fmt: str,
    scope: ExportScope,
    positions: Optional[List[int]] = None,
) -> str:
    """Build attachment filename; positions ignored except for selected scope label."""
    del positions
    ts = safe_timestamp_for_filename()
    if fmt == "json":
        return f"mdi_evidence_{scope.value}_{ts}.json"
    return f"mdi_export_{scope.value}_{ts}.csv"


def _sanitize_errors(errors: List[MdiError]) -> List[Dict[str, Any]]:
    return [
        {
            "code": err.code,
            "message": err.message,
            "source": err.source,
            "retriable": err.retriable,
        }
        for err in errors
    ]


def _domain_hold_json(result: MdiResultItem) -> Optional[Dict[str, Any]]:
    hold = result.domain_hold
    if hold is None:
        return None
    return {
        "has_hold": hold.has_hold,
        "hold_types": [_enum_value(t) for t in hold.hold_types],
        "source": _enum_value(hold.source),
    }


def _result_json(result: MdiResultItem) -> Dict[str, Any]:
    hold = result.domain_hold
    hold_source = _enum_value(hold.source) if hold else None
    return {
        "position": result.position,
        "input_original": result.input_original,
        "input_normalized": result.input_normalized,
        "input_type": _enum_value(result.input_type),
        "processing_status": _enum_value(result.processing_status),
        "triage_bucket": _enum_value(result.triage_bucket),
        "triage_confidence": _enum_value(result.triage_confidence),
        "recommended_action": _enum_value(result.recommended_action),
        "evidence_status": _enum_value(result.evidence_status),
        "vt_hits": result.vt_hits,
        "vt_suspicious": result.vt_suspicious,
        "vt_total_engines": result.vt_total_engines,
        "vt_ratio": result.vt_ratio,
        "freshness": _enum_value(result.freshness),
        "vt_scan_date": result.vt_scan_date.isoformat() if result.vt_scan_date else None,
        "live_status": _enum_value(result.live_status),
        "http_status_code": result.http_status_code,
        "redirect_count": result.redirect_count,
        "created_at": result.created_at.isoformat() if result.created_at else None,
        "age_bucket": _enum_value(result.age_bucket),
        "registrar": result.registrar,
        "domain_status_source": hold_source,
        "domain_hold_has_hold": hold.has_hold if hold else False,
        "domain_hold_source": hold_source,
        "triage_reason": list(result.triage_reason),
        "error_codes": [err.code for err in result.errors],
        "errors": _sanitize_errors(result.errors),
        "vt_engine_results": result.vt_engine_results,
        "epp_status": list(result.epp_status),
        "nameservers": list(result.nameservers),
        "domain_hold": _domain_hold_json(result),
        "vt_mode_used": _enum_value(result.vt_mode_used),
    }


def _job_metadata(job: InMemoryJob) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "submitted_at": datetime.fromtimestamp(job.submitted_at, tz=timezone.utc).isoformat(),
        "completed_at": (
            datetime.fromtimestamp(job.completed_at, tz=timezone.utc).isoformat()
            if job.completed_at is not None
            else None
        ),
        "use_domain_reports": job.use_domain_reports,
        "stale_threshold_days": job.stale_threshold_days,
        "auto_rescan_stale": job.auto_rescan_stale,
        "max_auto_rescans": job.max_auto_rescans,
        "lookups_used": job.lookups_used,
        "estimated_requests": job.estimated_requests,
        "rdap_enriched_count": job.rdap_enriched_count,
        "rdap_failed_count": job.rdap_failed_count,
        "whois_fallback_count": job.whois_fallback_count,
        "live_check_count": job.live_check_count,
        "live_check_skipped_count": job.live_check_skipped_count,
        "live_check_error_count": job.live_check_error_count,
        "auto_rescan_attempted_count": job.auto_rescan_attempted_count,
        "auto_rescan_completed_count": job.auto_rescan_completed_count,
        "auto_rescan_failed_count": job.auto_rescan_failed_count,
        "auto_rescan_skipped_count": job.auto_rescan_skipped_count,
        "auto_rescan_quota_blocked_count": job.auto_rescan_quota_blocked_count,
        "rejected_count": job.rejected_count,
        "held_skipped": job.held_skipped,
        "quota_blocked_count": job.quota_blocked_count,
    }


def build_evidence_json_export(
    job: InMemoryJob,
    rows: List[MdiResultItem],
    scope: ExportScope,
    positions: Optional[List[int]] = None,
) -> str:
    """Build JSON evidence export string (mdi-evidence-v1)."""
    payload: Dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "job": _job_metadata(job),
        "scope": scope.value,
        "results": [_result_json(row) for row in rows],
    }
    if scope == ExportScope.SELECTED and positions:
        payload["positions"] = list(positions)
    return json.dumps(payload, indent=2, default=str)
