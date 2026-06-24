"""
Hold-impact guidance derived from Cloudflare Radar rank bucket (MDI-50C).

Analyst guidance only — does not change triage, VT verdicts, or enforcement.
No HTTP calls; uses stored cloudflare_rank_bucket only.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from services.cloudflare_radar import CloudflareRankBucket


class HoldImpactLevel:
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"
    UNKNOWN = "unknown"


_BUCKET_TO_LEVEL: Dict[str, str] = {
    CloudflareRankBucket.TOP_100: HoldImpactLevel.CRITICAL,
    CloudflareRankBucket.TOP_1K: HoldImpactLevel.CRITICAL,
    CloudflareRankBucket.TOP_5K: HoldImpactLevel.HIGH,
    CloudflareRankBucket.TOP_10K: HoldImpactLevel.HIGH,
    CloudflareRankBucket.TOP_100K: HoldImpactLevel.MEDIUM,
    CloudflareRankBucket.TOP_1M: HoldImpactLevel.LOW,
    CloudflareRankBucket.UNRANKED: HoldImpactLevel.NONE,
    CloudflareRankBucket.UNKNOWN: HoldImpactLevel.UNKNOWN,
}

_REASON_BY_LEVEL: Dict[str, str] = {
    HoldImpactLevel.CRITICAL: (
        "Domain is highly ranked by Cloudflare Radar popularity data; "
        "review potential blast radius before any hold action."
    ),
    HoldImpactLevel.HIGH: (
        "Domain is within a high-popularity Cloudflare Radar bucket; "
        "escalate or review blast radius before any hold action."
    ),
    HoldImpactLevel.MEDIUM: (
        "Domain has measurable Cloudflare Radar popularity; "
        "consider business or customer impact before hold action."
    ),
    HoldImpactLevel.LOW: (
        "Domain appears in a lower Cloudflare Radar popularity bucket; "
        "hold-impact risk appears lower but still requires analyst review."
    ),
    HoldImpactLevel.NONE: (
        "Domain is not ranked in the Cloudflare Radar popularity bucket used by MDI; "
        "no rank-based hold-impact warning."
    ),
    HoldImpactLevel.UNKNOWN: (
        "Cloudflare Radar rank impact is unavailable or unknown; "
        "do not use rank as hold-impact evidence."
    ),
}


def derive_hold_impact_from_cloudflare_bucket(
    bucket: Optional[str],
) -> Tuple[str, str]:
    """
    Map stored cloudflare_rank_bucket to (hold_impact_level, hold_impact_reason).

    null / missing / disabled lookup → unknown.
    """
    if bucket is None:
        return HoldImpactLevel.UNKNOWN, _REASON_BY_LEVEL[HoldImpactLevel.UNKNOWN]

    level = _BUCKET_TO_LEVEL.get(bucket)
    if level is None:
        return HoldImpactLevel.UNKNOWN, _REASON_BY_LEVEL[HoldImpactLevel.UNKNOWN]

    return level, _REASON_BY_LEVEL[level]


def hold_impact_item_update(bucket: Optional[str]) -> Dict[str, Any]:
    """Return model_copy update dict for hold-impact guidance fields."""
    level, reason = derive_hold_impact_from_cloudflare_bucket(bucket)
    return {
        "hold_impact_level": level,
        "hold_impact_reason": reason,
    }
