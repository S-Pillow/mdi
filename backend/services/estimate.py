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

# MDI-11A: RDAP enrichment timing constants
# rdap.org allows ~10 req/10s; MDI enforces 1.1 s minimum gap between requests.
# Estimate uses 1.1 s as the per-item worst case (all unique registered domains).
# Best-case enrichment time = 0 (all items share the same registered domain → 1 lookup).
RDAP_ESTIMATE_SECONDS_PER_ITEM: float = 1.1

# Items above this threshold trigger the enrichment_warning field.
RDAP_ENRICHMENT_LARGE_COUNT_THRESHOLD: int = 100

ENRICHMENT_NOTE: str = (
    "MDI-11: RDAP/WHOIS enrichment runs before VT. "
    f"Rate limit: 1.1 s minimum between requests (rdap.org ≈ 10 req/10 s). "
    "Worst-case estimate assumes all items have unique registered domains. "
    "Items sharing the same registered domain are enriched once (per-job cache)."
)

# MDI-12: live-check note (shown at estimate time — count is always 0 before VT)
LIVE_CHECK_NOTE: str = (
    "Live checks run only after VT and only for flagged/suspicious items. "
    "They may add up to 10 seconds per flagged item, plus redirect time. "
    "The exact count is not known until VT processing completes."
)

AUTO_RESCAN_URL_QUOTA_PER_ITEM_MAX: int = 4
AUTO_RESCAN_DOMAIN_QUOTA_PER_ITEM_MAX: int = 5


def _auto_rescan_slots(
    *,
    max_auto_rescans: int,
    domain_report_mode_count: int,
    url_report_mode_count: int,
) -> tuple[int, int, int]:
    """Return (domain_slots, url_slots, quota_max) for auto-rescan estimate."""
    eligible = domain_report_mode_count + url_report_mode_count
    if max_auto_rescans <= 0 or eligible <= 0:
        return 0, 0, 0
    slots = min(max_auto_rescans, eligible)
    domain_slots = min(domain_report_mode_count, slots)
    url_slots = min(url_report_mode_count, slots - domain_slots)
    quota_max = (
        domain_slots * AUTO_RESCAN_DOMAIN_QUOTA_PER_ITEM_MAX
        + url_slots * AUTO_RESCAN_URL_QUOTA_PER_ITEM_MAX
    )
    return domain_slots, url_slots, quota_max


def _auto_rescan_note(max_calls: int) -> str:
    if max_calls <= 0:
        return ""
    return (
        f"Auto-rescan may add up to {max_calls} VT calls (URL scans and domain reanalysis). "
        "Actual usage depends on how many stale flagged rows are found during processing."
    )


def _enrichment_warning(lookups: int) -> str:
    """
    Return a warning string when enrichment lookups will take significant time.
    Returns an empty string below the threshold.
    """
    if lookups <= RDAP_ENRICHMENT_LARGE_COUNT_THRESHOLD:
        return ""
    minutes = (lookups * RDAP_ESTIMATE_SECONDS_PER_ITEM) / 60.0
    return (
        f"Large batch: RDAP enrichment may add up to {minutes:.1f} minutes "
        f"for {lookups} unique domains "
        f"(rdap.org rate limit ~1 req/s, 1.1 s enforced gap). "
        "De-duplication of shared registered domains reduces actual runtime. "
        "Consider splitting large batches if enrichment latency is a concern."
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
    *,
    auto_rescan_stale: bool = False,
    max_auto_rescans: int = 3,
) -> dict:
    """
    Compute a full estimate for a list of eligible (non-held) MdiInputItem objects.

    Returns a dict with all estimate fields ready to be placed into EstimateResponse.
    Items must already be parsed and deduplicated (i.e., from parse_raw_input().accepted).

    No external calls, no job creation, no file writes.

    Enrichment runtime (MDI-11A):
      - Best case (min): 0 s — all items share the same registered domain (1 lookup).
      - Worst case (max): N × 1.1 s — every item has a unique registered domain.
      - Total min = VT min + enrichment min.
      - Total max = VT max + enrichment max.
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

    # MDI-11A: RDAP enrichment time estimate (separate from VT time).
    # Conservative: 1 lookup per item (real jobs de-duplicate by registered domain).
    # Min = 0 (best case: all items share a registered domain → 1 lookup).
    # Max = N × 1.1 s (worst case: every item is a unique registered domain).
    estimated_enrichment_lookups = len(items)
    enrichment_duration_min = 0.0
    enrichment_duration_max = estimated_enrichment_lookups * RDAP_ESTIMATE_SECONDS_PER_ITEM

    duration_min = vt_duration_min + enrichment_duration_min
    duration_max = vt_duration_max + enrichment_duration_max

    warning = _enrichment_warning(estimated_enrichment_lookups)

    auto_rescan_quota_min = 0
    auto_rescan_quota_max = 0
    auto_rescan_domain_eligible_max = 0
    auto_rescan_url_eligible_max = 0
    if auto_rescan_stale and max_auto_rescans > 0:
        domain_slots, url_slots, auto_rescan_quota_max = _auto_rescan_slots(
            max_auto_rescans=max_auto_rescans,
            domain_report_mode_count=domain_report_mode_count,
            url_report_mode_count=url_report_mode_count,
        )
        auto_rescan_domain_eligible_max = domain_slots
        auto_rescan_url_eligible_max = url_slots
    auto_rescan_duration_min = 0.0
    auto_rescan_duration_max = max(
        0.0,
        (auto_rescan_quota_max - 1) * VT_RATE_LIMIT_INTERVAL_SECONDS if auto_rescan_quota_max else 0.0,
    )
    total_vt_max = total_max + auto_rescan_quota_max
    total_duration_max = duration_max + auto_rescan_duration_max
    auto_rescan_note = _auto_rescan_note(auto_rescan_quota_max) if auto_rescan_stale else ""

    return {
        "domain_count": domain_count,
        "url_count": url_count,
        "domain_report_mode_count": domain_report_mode_count,
        "url_report_mode_count": url_report_mode_count,
        "estimated_vt_calls_min": total_min,
        "estimated_vt_calls_max": total_max,
        "estimated_enrichment_lookups": estimated_enrichment_lookups,
        "estimated_enrichment_duration_seconds_min": enrichment_duration_min,
        "estimated_enrichment_duration_seconds_max": enrichment_duration_max,
        "estimated_duration_seconds_min": duration_min,
        "estimated_duration_seconds_max": duration_max,
        "rate_limit_note": VT_RATE_LIMIT_NOTE,
        "job_state_note": JOB_STATE_NOTE,
        "enrichment_note": ENRICHMENT_NOTE,
        "enrichment_warning": warning,
        # MDI-12: live-check estimate (always 0 — flagged count unknown before VT)
        "estimated_live_check_count": 0,
        "live_check_note": LIVE_CHECK_NOTE,
        "auto_rescan_estimated_quota_min": auto_rescan_quota_min,
        "auto_rescan_estimated_quota_max": auto_rescan_quota_max,
        "auto_rescan_domain_eligible_max": auto_rescan_domain_eligible_max,
        "auto_rescan_url_eligible_max": auto_rescan_url_eligible_max,
        "total_estimated_vt_calls_max": total_vt_max,
        "auto_rescan_estimated_duration_seconds_min": auto_rescan_duration_min,
        "auto_rescan_estimated_duration_seconds_max": auto_rescan_duration_max,
        "auto_rescan_note": auto_rescan_note,
    }
