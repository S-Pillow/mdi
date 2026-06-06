"""
MDI estimate service — shared quota and runtime estimation logic.

This module is the single authoritative source for the estimate formula.
Both POST /api/mdi/jobs/estimate and POST /api/mdi/jobs/submit must use
the functions here to guarantee frontend/backend parity.

Hard guarantees:
  - No external calls (no VT, no WHOIS/RDAP, no DNS, no URL checks).
  - No job creation.
  - No runtime file writes.
  - No quota consumed.
"""

from __future__ import annotations

from typing import List

from models import InputType

# VT free-tier: 4 requests per minute → 15 seconds minimum between calls.
VT_RATE_LIMIT_INTERVAL_SECONDS: float = 15.0
VT_RATE_LIMIT_NOTE: str = (
    "VT free-tier: 4 req/min. Each VT call has a minimum 15-second gap. "
    "Runtime estimate assumes sequential processing with no caching discount."
)
JOB_STATE_NOTE: str = (
    "Jobs are stored in-memory only. All job data is lost on service restart. "
    "Persistent job recovery is deferred to MDI-08."
)

# MDI-11: conservative RDAP enrichment time per item (seconds)
RDAP_ESTIMATE_SECONDS_PER_ITEM: float = 0.5
ENRICHMENT_NOTE: str = (
    "MDI-11: RDAP/WHOIS enrichment runs before VT. "
    f"Estimate adds {RDAP_ESTIMATE_SECONDS_PER_ITEM}s per item for RDAP lookups. "
    "Domains sharing the same registered domain are enriched once (deduplication in live jobs)."
)


def estimate_calls_for_item(input_type: InputType, use_domain_reports: bool) -> tuple[int, int]:
    """
    Return (calls_min, calls_max) for a single eligible (non-held) item.

    Best case (calls_min): the VT report already exists and is returned immediately.
      - 1 GET call regardless of item type or mode.

    Worst case (calls_max): the report is missing (404), requiring a submit + refetch.
      - domain in domain-report mode: 1 call (domain reports do not require submit).
      - bare domain in URL-report mode: 3 calls (GET → 404 → POST submit → GET again).
      - full URL in URL-report mode:    3 calls (GET → 404 → POST submit → GET again).
    """
    if input_type == InputType.DOMAIN and use_domain_reports:
        return 1, 1
    return 1, 3


def estimate_job(
    items: list,
    use_domain_reports: bool,
) -> dict:
    """
    Compute a full estimate for a list of eligible (non-held) MdiInputItem objects.

    Returns a dict with all estimate fields ready to be placed into EstimateResponse.
    Items must already be parsed and deduplicated (i.e., from parse_raw_input().accepted).

    No external calls, no job creation, no file writes.
    """
    domain_report_mode_count = 0
    url_report_mode_count = 0
    domain_count = 0
    url_count = 0
    total_min = 0
    total_max = 0

    for item in items:
        c_min, c_max = estimate_calls_for_item(item.input_type, use_domain_reports)
        total_min += c_min
        total_max += c_max

        if item.input_type == InputType.DOMAIN:
            domain_count += 1
            if use_domain_reports:
                domain_report_mode_count += 1
            else:
                url_report_mode_count += 1
        else:
            url_count += 1
            url_report_mode_count += 1

    vt_duration_min = max(0.0, (total_min - 1) * VT_RATE_LIMIT_INTERVAL_SECONDS)
    vt_duration_max = max(0.0, (total_max - 1) * VT_RATE_LIMIT_INTERVAL_SECONDS)

    # MDI-11: each accepted item gets one RDAP lookup before VT.
    # For paste input all items are non-held at estimate time (hold status is NOT_CHECKED).
    # Conservative estimate: 1 lookup per item; de-duplication reduces real-world count.
    estimated_enrichment_lookups = len(items)
    enrichment_seconds = estimated_enrichment_lookups * RDAP_ESTIMATE_SECONDS_PER_ITEM

    duration_min = vt_duration_min + enrichment_seconds
    duration_max = vt_duration_max + enrichment_seconds

    return {
        "domain_count": domain_count,
        "url_count": url_count,
        "domain_report_mode_count": domain_report_mode_count,
        "url_report_mode_count": url_report_mode_count,
        "estimated_vt_calls_min": total_min,
        "estimated_vt_calls_max": total_max,
        "estimated_enrichment_lookups": estimated_enrichment_lookups,
        "estimated_duration_seconds_min": duration_min,
        "estimated_duration_seconds_max": duration_max,
        "rate_limit_note": VT_RATE_LIMIT_NOTE,
        "job_state_note": JOB_STATE_NOTE,
        "enrichment_note": ENRICHMENT_NOTE,
    }
