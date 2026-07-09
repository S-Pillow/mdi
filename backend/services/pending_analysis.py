"""
MDI-57A / MDI-57B shared pending-analysis detection.

Identifies URL-mode rows submitted to VirusTotal whose analysis is not yet
complete (submit-only pending state). Used by export formatting and by
Bulk Refresh Pending eligibility so both paths stay aligned.

No network calls. No disk I/O.
"""

from __future__ import annotations

from models import (
    MdiProcessingStatus,
    MdiResultItem,
    TriageBucket,
    VtModeUsed,
)


def has_completed_vt_scan(result: MdiResultItem) -> bool:
    """True when saved row data includes a completed VT report lookup."""
    if result.vt_mode_used not in (VtModeUsed.URL_REPORT, VtModeUsed.DOMAIN_REPORT):
        return False
    if result.vt_scan_date is not None:
        return True
    if (result.vt_total_engines or 0) > 0:
        return True
    return False


def is_pending_analysis(result: MdiResultItem) -> bool:
    """
    True for a URL submitted to VT whose analysis is not complete (MDI-57A).

    Canonical shape:
      - vt_mode_used == url_report
      - no completed scan evidence (no scan date, no engine total)
      - vt_scan_pending warning present, OR triage_bucket == pending

    Does not treat held rows, domain-report rows, or generic blocking-error
    rows as pending analysis.
    """
    if result is None:
        return False
    if has_completed_vt_scan(result):
        return False
    if result.vt_mode_used != VtModeUsed.URL_REPORT:
        return False
    if result.processing_status == MdiProcessingStatus.HOLD_SKIPPED:
        return False
    hold = result.domain_hold
    if hold is not None and hold.has_hold:
        return False
    if any((e.code or "") == "vt_scan_pending" for e in (result.errors or [])):
        return True
    return result.triage_bucket == TriageBucket.PENDING


def is_pending_refresh_eligible(result: MdiResultItem) -> bool:
    """
    True when a row is eligible for Bulk Refresh Pending (MDI-57B).

    Requires pending-analysis shape plus a refreshable normalized input.
    Held / missing-input rows are excluded.
    """
    if not is_pending_analysis(result):
        return False
    if not result.input_normalized:
        return False
    return True
