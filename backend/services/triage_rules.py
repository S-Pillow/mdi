"""
MDI-10 Centralized Triage Rules Engine.

This module is the single authoritative source for all per-item triage decisions.
All callers (job_processor, held-domain path, quota-blocked path, error paths)
must route through decide() to guarantee consistent output.

Rules:
  - Pure function — no I/O, no HTTP, no quota reads/writes, no runtime file access.
  - Safe with None values and unknown/default enum values.
  - "Recent" means domain registration recency: age_bucket in (VERY_NEW, NEW).
  - "Stale" means VT report age: freshness in (STALE, VERY_STALE).
  - These dimensions are independent — both can be true simultaneously.
  - Priority is strict first-match (highest priority wins).

Priority order:
  1. Domain On Hold              (domain_hold overrides all VT signals)
  2. Error / Quota Blocked       (processing failed; retry)
  3. Flagged + Live + Recent     (highest-urgency malicious: live AND new)
  4. Flagged + Live              (live malicious)
  5. Flagged + Recent            (newly-registered malicious)
  6. Flagged + Stale             (malicious but evidence is old)
  7. Flagged + No-Live           (malicious but domain appears down)
  8. Flagged (catch-all)         (malicious, unknown live/age)
  9. Suspicious (same sub-rules) (suspicious signal, lower priority than malicious)
 10. Clean                       (VT succeeded, no hits)
 11. Pending / Unknown           (no reliable VT decision)

Roadmap notes:
  - live_status is always NOT_CHECKED until MDI-12 (URL Activity Scanner).
    Branches 3, 4, 7 exist in code but are unreachable until MDI-12.
  - age_bucket is always UNKNOWN for raw-text items until MDI-11 (WHOIS/RDAP).
    age_bucket can be set now for uploaded CSV/XLSX items with a create-date column.
    Branch 5 is partially reachable today; fully reachable after MDI-11.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from models import (
    AgeBucket,
    EvidenceStatus,
    Freshness,
    LiveStatus,
    MdiError,
    MdiProcessingStatus,
    RecommendedAction,
    TriageBucket,
    TriageConfidence,
)
from services.error_taxonomy import has_blocking_errors


# ── Helpers ───────────────────────────────────────────────────────────────────

_RECENT_BUCKETS = frozenset({AgeBucket.VERY_NEW, AgeBucket.NEW})

_ACTIVE_LIVE = frozenset({
    LiveStatus.ACTIVE,
    LiveStatus.REDIRECT,
    LiveStatus.FORBIDDEN,
})

_NO_LIVE = frozenset({
    LiveStatus.NOT_FOUND,
    LiveStatus.GONE,
    LiveStatus.DNS_FAILURE,
    LiveStatus.CONNECTION_REFUSED,
    LiveStatus.TIMEOUT,
})


def _is_recent(age_bucket: AgeBucket) -> bool:
    """True when domain is recently registered (< 180 days)."""
    return age_bucket in _RECENT_BUCKETS


def _is_live(live_status: LiveStatus) -> bool:
    """True when live check indicates domain is active/responding."""
    return live_status in _ACTIVE_LIVE


def _is_no_live(live_status: LiveStatus) -> bool:
    """True when live check confirmed domain is down/gone/unreachable."""
    return live_status in _NO_LIVE


def _vt_complete(vt_total_engines: int, errors: List[MdiError]) -> bool:
    """True when VT ran and returned engine votes with no errors."""
    return vt_total_engines > 0 and not errors


# ── Input / Output dataclasses ────────────────────────────────────────────────

@dataclass
class TriageInput:
    """
    All inputs the rules engine needs. Drawn from MdiResultItem / VtLookupResult.
    All fields have safe defaults so callers may omit irrelevant ones.
    """
    domain_hold_has_hold: bool = False
    processing_status: MdiProcessingStatus = MdiProcessingStatus.PENDING
    vt_hits: int = 0            # vt_malicious count
    vt_suspicious: int = 0
    vt_total_engines: int = 0
    freshness: Freshness = Freshness.UNKNOWN
    live_status: LiveStatus = LiveStatus.NOT_CHECKED
    age_bucket: AgeBucket = AgeBucket.UNKNOWN
    errors: List[MdiError] = field(default_factory=list)
    created_at: Optional[datetime] = None
    stale_threshold_days: int = 7


@dataclass
class TriageDecision:
    """Output from the rules engine for one item."""
    triage_bucket: TriageBucket
    triage_confidence: TriageConfidence
    recommended_action: RecommendedAction
    evidence_status: EvidenceStatus
    triage_reason: List[str]


# ── Reason helpers ────────────────────────────────────────────────────────────

def _reason_hold() -> List[str]:
    return [
        "Domain is on registry hold (clientHold or serverHold).",
        "VT check was skipped — the hold is the operative action.",
        "No further action required unless the hold is lifted.",
    ]


def _reason_error(inp: TriageInput) -> List[str]:
    lines: List[str] = []
    blocking = [e for e in inp.errors if has_blocking_errors([e])]
    for e in blocking or inp.errors:
        lines.append(f"Processing error: {e.message} (code: {e.code}).")
    if not lines:
        lines.append("Processing failed or was blocked before VT could run.")
    lines.append("Retry when quota or connectivity allows.")
    return lines


def _is_error_triage_path(inp: TriageInput) -> bool:
    """
    True when triage should route to ERROR bucket.

    Blocking errors always qualify. processing_status=ERROR qualifies only when
    there is no usable VT evidence (VT did not succeed).
    """
    if has_blocking_errors(inp.errors):
        return True
    if inp.processing_status == MdiProcessingStatus.ERROR:
        return not _vt_complete(inp.vt_total_engines, [])
    return False


def _reason_flagged(inp: TriageInput, sub_reason: List[str]) -> List[str]:
    lines: List[str] = [
        f"VT flagged this item with {inp.vt_hits} malicious engine(s).",
    ]
    lines.extend(sub_reason)
    return lines


def _reason_suspicious(inp: TriageInput, sub_reason: List[str]) -> List[str]:
    lines: List[str] = [
        f"VT flagged this item with {inp.vt_suspicious} suspicious engine(s) and no malicious engines.",
    ]
    lines.extend(sub_reason)
    return lines


def _live_recent_sub(inp: TriageInput) -> List[str]:
    lines = ["Domain appears live/active based on live check."]
    lines.extend(_recent_sub(inp))
    return lines


def _live_sub(inp: TriageInput) -> List[str]:
    lines = ["Domain appears live/active based on live check."]
    lines.extend(_freshness_note(inp))
    return lines


def _recent_sub(inp: TriageInput) -> List[str]:
    lines = [f"Domain age is recent (age bucket: {inp.age_bucket.value})."]
    lines.extend(_freshness_note(inp))
    return lines


def _stale_sub(inp: TriageInput) -> List[str]:
    lines = [f"VT report is {inp.freshness.value} (older than {inp.stale_threshold_days} days)."]
    if inp.freshness == Freshness.VERY_STALE:
        lines.append("A new VT scan is recommended before actioning.")
    else:
        lines.append("Refreshing the VT report is recommended before actioning.")
    lines.append("Live check has not been performed.")
    return lines


def _no_live_sub(inp: TriageInput) -> List[str]:
    lines = [f"Live check indicates domain is not active (status: {inp.live_status.value})."]
    lines.extend(_freshness_note(inp))
    return lines


def _catchall_sub(inp: TriageInput) -> List[str]:
    lines: List[str] = []
    lines.extend(_freshness_note(inp))
    lines.append("Live check has not been performed.")
    if _is_recent(inp.age_bucket):
        lines.append(f"Domain age is recent (age bucket: {inp.age_bucket.value}).")
    return lines


def _freshness_note(inp: TriageInput) -> List[str]:
    if inp.freshness in (Freshness.STALE, Freshness.VERY_STALE):
        return [
            f"VT report is {inp.freshness.value} (older than {inp.stale_threshold_days} days); "
            "consider refreshing before actioning."
        ]
    if inp.freshness == Freshness.FRESH:
        return ["VT report is recent."]
    return ["VT report freshness is unknown."]


def _clean_sub(inp: TriageInput) -> List[str]:
    lines: List[str] = [
        f"No VT engines flagged this item ({inp.vt_total_engines} engine(s) checked).",
    ]
    if inp.freshness == Freshness.FRESH:
        lines.append("VT report is recent; no action required based on current VT data.")
    elif inp.freshness == Freshness.STALE:
        lines.append(f"VT report is stale (older than {inp.stale_threshold_days} days); consider refreshing to confirm.")
    elif inp.freshness == Freshness.VERY_STALE:
        lines.append(f"VT report is very stale (older than {inp.stale_threshold_days} days); requesting a new scan is advised.")
    else:
        lines.append("VT report freshness is unknown; verify evidence quality.")
    lines.append("Live check has not been performed.")
    return lines


def _pending_sub(inp: TriageInput) -> List[str]:
    if inp.vt_total_engines == 0 and inp.processing_status != MdiProcessingStatus.PENDING:
        return [
            "VT returned no engine results for this item.",
            "Item may not have been scanned by VT yet.",
            "Retry or request a new VT scan.",
        ]
    return [
        "Item has not been processed yet.",
        "Submit a new job or retry when quota is available.",
    ]


# ── Confidence from freshness ─────────────────────────────────────────────────

def _conf_from_freshness(freshness: Freshness) -> TriageConfidence:
    if freshness == Freshness.FRESH:
        return TriageConfidence.HIGH
    if freshness == Freshness.STALE:
        return TriageConfidence.MEDIUM
    if freshness == Freshness.VERY_STALE:
        return TriageConfidence.LOW
    return TriageConfidence.LOW


# ── Evidence status ───────────────────────────────────────────────────────────

def _evidence_from_vt(inp: TriageInput) -> EvidenceStatus:
    if _vt_complete(inp.vt_total_engines, inp.errors):
        return EvidenceStatus.COMPLETE
    if inp.vt_total_engines == 0 and not inp.errors:
        return EvidenceStatus.PARTIAL
    return EvidenceStatus.PARTIAL


# ── Flagged sub-decision (malicious or suspicious) ────────────────────────────

def _flagged_decision(inp: TriageInput, is_suspicious: bool) -> TriageDecision:
    """
    Apply the same live/recent/stale/no-live modifier tree for both
    malicious (vt_hits > 0) and suspicious (vt_suspicious > 0, vt_hits == 0).
    """
    bucket = TriageBucket.SUSPICIOUS if is_suspicious else TriageBucket.MALICIOUS
    evidence = _evidence_from_vt(inp)
    reason_wrap = _reason_suspicious if is_suspicious else _reason_flagged

    # 1. Live + Recent
    if _is_live(inp.live_status) and _is_recent(inp.age_bucket):
        return TriageDecision(
            triage_bucket=bucket,
            triage_confidence=TriageConfidence.HIGH,
            recommended_action=RecommendedAction.INVESTIGATE_HOLD,
            evidence_status=evidence,
            triage_reason=reason_wrap(inp, _live_recent_sub(inp)),
        )

    # 2. Live
    if _is_live(inp.live_status):
        return TriageDecision(
            triage_bucket=bucket,
            triage_confidence=TriageConfidence.HIGH,
            recommended_action=RecommendedAction.INVESTIGATE_HOLD,
            evidence_status=evidence,
            triage_reason=reason_wrap(inp, _live_sub(inp)),
        )

    # 3. Recent (domain age) — recent wins even if VT is stale (stale noted in reason)
    if _is_recent(inp.age_bucket):
        conf = TriageConfidence.HIGH if inp.freshness == Freshness.FRESH else TriageConfidence.MEDIUM
        return TriageDecision(
            triage_bucket=bucket,
            triage_confidence=conf,
            recommended_action=RecommendedAction.INVESTIGATE_HOLD,
            evidence_status=evidence,
            triage_reason=reason_wrap(inp, _recent_sub(inp)),
        )

    # 4. VT report stale
    if inp.freshness == Freshness.STALE:
        return TriageDecision(
            triage_bucket=bucket,
            triage_confidence=TriageConfidence.MEDIUM,
            recommended_action=RecommendedAction.REQUEST_NEW_SCAN,
            evidence_status=evidence,
            triage_reason=reason_wrap(inp, _stale_sub(inp)),
        )

    # 5. VT report very stale
    if inp.freshness == Freshness.VERY_STALE:
        return TriageDecision(
            triage_bucket=bucket,
            triage_confidence=TriageConfidence.LOW,
            recommended_action=RecommendedAction.REQUEST_NEW_SCAN,
            evidence_status=evidence,
            triage_reason=reason_wrap(inp, _stale_sub(inp)),
        )

    # 6. No-Live (domain appears down)
    if _is_no_live(inp.live_status):
        return TriageDecision(
            triage_bucket=bucket,
            triage_confidence=TriageConfidence.MEDIUM,
            recommended_action=RecommendedAction.VERIFY_INVESTIGATE,
            evidence_status=evidence,
            triage_reason=reason_wrap(inp, _no_live_sub(inp)),
        )

    # 7. Catch-all (unknown live/age/freshness)
    conf = _conf_from_freshness(inp.freshness)
    return TriageDecision(
        triage_bucket=bucket,
        triage_confidence=conf,
        recommended_action=RecommendedAction.VERIFY_INVESTIGATE,
        evidence_status=evidence,
        triage_reason=reason_wrap(inp, _catchall_sub(inp)),
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def decide(inp: TriageInput) -> TriageDecision:
    """
    Return a TriageDecision for a single item.

    Priority is strict first-match. See module docstring for the full order.
    This function never raises; all inputs have safe defaults.
    """

    # ── Priority 1: Domain On Hold ────────────────────────────────────────────
    if inp.domain_hold_has_hold:
        return TriageDecision(
            triage_bucket=TriageBucket.HELD,
            triage_confidence=TriageConfidence.HIGH,
            recommended_action=RecommendedAction.ACTION_ALREADY_TAKEN,
            evidence_status=EvidenceStatus.SKIPPED_HOLD,
            triage_reason=_reason_hold(),
        )

    # ── Priority 2: Blocking errors / failed processing without VT evidence ───
    if _is_error_triage_path(inp):
        return TriageDecision(
            triage_bucket=TriageBucket.ERROR,
            triage_confidence=TriageConfidence.UNKNOWN,
            recommended_action=RecommendedAction.RETRY_LOOKUP,
            evidence_status=EvidenceStatus.PARTIAL,
            triage_reason=_reason_error(inp),
        )

    # ── Priority 3–8: Flagged (malicious) ────────────────────────────────────
    if inp.vt_hits > 0:
        return _flagged_decision(inp, is_suspicious=False)

    # ── Priority 9: Suspicious ────────────────────────────────────────────────
    if inp.vt_suspicious > 0:
        return _flagged_decision(inp, is_suspicious=True)

    # ── Priority 10: Clean ────────────────────────────────────────────────────
    if inp.vt_total_engines > 0:
        if inp.freshness == Freshness.FRESH:
            return TriageDecision(
                triage_bucket=TriageBucket.CLEAN,
                triage_confidence=TriageConfidence.CLEAN,
                recommended_action=RecommendedAction.NO_ACTION_BASED_ON_VT,
                evidence_status=EvidenceStatus.COMPLETE,
                triage_reason=_clean_sub(inp),
            )
        if inp.freshness == Freshness.STALE:
            return TriageDecision(
                triage_bucket=TriageBucket.CLEAN,
                triage_confidence=TriageConfidence.MEDIUM,
                recommended_action=RecommendedAction.REQUEST_NEW_SCAN,
                evidence_status=EvidenceStatus.COMPLETE,
                triage_reason=_clean_sub(inp),
            )
        if inp.freshness == Freshness.VERY_STALE:
            return TriageDecision(
                triage_bucket=TriageBucket.CLEAN,
                triage_confidence=TriageConfidence.MEDIUM,
                recommended_action=RecommendedAction.REQUEST_NEW_SCAN,
                evidence_status=EvidenceStatus.COMPLETE,
                triage_reason=_clean_sub(inp),
            )
        # Unknown freshness but VT ran
        return TriageDecision(
            triage_bucket=TriageBucket.CLEAN,
            triage_confidence=TriageConfidence.MEDIUM,
            recommended_action=RecommendedAction.VERIFY_INVESTIGATE,
            evidence_status=EvidenceStatus.COMPLETE,
            triage_reason=_clean_sub(inp),
        )

    # ── Priority 11: Pending / Unknown ────────────────────────────────────────
    return TriageDecision(
        triage_bucket=TriageBucket.PENDING,
        triage_confidence=TriageConfidence.UNKNOWN,
        recommended_action=RecommendedAction.RETRY_LOOKUP,
        evidence_status=EvidenceStatus.PARTIAL if inp.processing_status != MdiProcessingStatus.PENDING else EvidenceStatus.NONE,
        triage_reason=_pending_sub(inp),
    )
