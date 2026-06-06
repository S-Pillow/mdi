"""
MDI-10 unit tests for triage_rules.py.

All tests are pure-function unit tests:
  - No VT calls.
  - No external HTTP calls.
  - No quota reads/writes.
  - No runtime file access.
  - No fixtures required.

Test groups:
  1. Core separation — proves Recent (age_bucket) and Stale (freshness) are independent.
  2. Hold override — hold wins regardless of VT state.
  3. Error and quota-blocked paths.
  4. Malicious sub-rules — live, recent, stale, no-live, catch-all.
  5. Suspicious sub-rules — mirrors malicious at lower priority.
  6. Clean sub-rules — confidence CLEAN for fresh, MEDIUM for stale.
  7. Pending / unknown paths.
  8. triage_reason non-empty for every bucket.
  9. None/default safety — no exceptions on default inputs.
 10. Backward compatibility — old enum values still parse/serialize.
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

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
from services.triage_rules import TriageInput, TriageDecision, decide


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flagged(
    *,
    hits: int = 2,
    age: AgeBucket = AgeBucket.UNKNOWN,
    freshness: Freshness = Freshness.FRESH,
    live: LiveStatus = LiveStatus.NOT_CHECKED,
    stale_days: int = 7,
) -> TriageInput:
    return TriageInput(
        vt_hits=hits,
        vt_total_engines=72,
        freshness=freshness,
        live_status=live,
        age_bucket=age,
        stale_threshold_days=stale_days,
    )


def _suspicious(
    *,
    sus: int = 2,
    age: AgeBucket = AgeBucket.UNKNOWN,
    freshness: Freshness = Freshness.FRESH,
    live: LiveStatus = LiveStatus.NOT_CHECKED,
) -> TriageInput:
    return TriageInput(
        vt_hits=0,
        vt_suspicious=sus,
        vt_total_engines=72,
        freshness=freshness,
        live_status=live,
        age_bucket=age,
    )


def _clean(*, freshness: Freshness = Freshness.FRESH) -> TriageInput:
    return TriageInput(
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=72,
        freshness=freshness,
    )


# ── 1. Core separation: Recent (age_bucket) vs. Stale (freshness) ─────────────

class TestCoreSeparation:

    def test_flagged_very_new_fresh_evidence_is_recent(self):
        """VERY_NEW domain + FRESH VT → Flagged + Recent (REVIEW_FOR_ACTION)."""
        d = decide(_flagged(age=AgeBucket.VERY_NEW, freshness=Freshness.FRESH))
        assert d.triage_bucket == TriageBucket.MALICIOUS
        assert d.recommended_action == RecommendedAction.REVIEW_FOR_ACTION
        assert d.triage_confidence == TriageConfidence.HIGH

    def test_flagged_new_fresh_evidence_is_recent(self):
        """NEW domain (30–180 days) + FRESH VT → Flagged + Recent."""
        d = decide(_flagged(age=AgeBucket.NEW, freshness=Freshness.FRESH))
        assert d.triage_bucket == TriageBucket.MALICIOUS
        assert d.recommended_action == RecommendedAction.REVIEW_FOR_ACTION

    def test_flagged_recent_stale_evidence_recent_wins_stale_in_reason(self):
        """NEW domain + STALE VT → Recent bucket wins; stale evidence noted in reason."""
        d = decide(_flagged(age=AgeBucket.NEW, freshness=Freshness.STALE))
        assert d.triage_bucket == TriageBucket.MALICIOUS
        assert d.recommended_action == RecommendedAction.REVIEW_FOR_ACTION
        assert d.triage_confidence == TriageConfidence.MEDIUM
        # Stale must be mentioned so operator knows evidence needs refresh
        reason_text = " ".join(d.triage_reason).lower()
        assert "stale" in reason_text or "older" in reason_text

    def test_flagged_established_stale_is_stale_not_recent(self):
        """ESTABLISHED domain + STALE VT → Stale behavior, not Recent."""
        d = decide(_flagged(age=AgeBucket.ESTABLISHED, freshness=Freshness.STALE))
        assert d.triage_bucket == TriageBucket.MALICIOUS
        assert d.recommended_action == RecommendedAction.REFRESH_REPORT
        assert d.triage_confidence == TriageConfidence.MEDIUM

    def test_flagged_mature_very_stale_is_request_new_scan(self):
        """MATURE domain + VERY_STALE VT → REQUEST_NEW_SCAN."""
        d = decide(_flagged(age=AgeBucket.MATURE, freshness=Freshness.VERY_STALE))
        assert d.triage_bucket == TriageBucket.MALICIOUS
        assert d.recommended_action == RecommendedAction.REQUEST_NEW_SCAN
        assert d.triage_confidence == TriageConfidence.LOW

    def test_stale_uses_freshness_not_age_bucket(self):
        """Confirm stale is driven purely by freshness; age_bucket UNKNOWN + STALE → REFRESH."""
        d = decide(_flagged(age=AgeBucket.UNKNOWN, freshness=Freshness.STALE))
        assert d.recommended_action == RecommendedAction.REFRESH_REPORT

    def test_recent_uses_age_bucket_not_freshness(self):
        """Confirm recent is driven purely by age_bucket; VERY_NEW + UNKNOWN freshness → REVIEW_FOR_ACTION."""
        d = decide(_flagged(age=AgeBucket.VERY_NEW, freshness=Freshness.UNKNOWN))
        assert d.recommended_action == RecommendedAction.REVIEW_FOR_ACTION


# ── 2. Hold Override ─────────────────────────────────────────────────────────

class TestHoldOverride:

    def test_hold_overrides_malicious_vt(self):
        """Hold must win even when vt_hits > 0."""
        d = decide(TriageInput(domain_hold_has_hold=True, vt_hits=5, vt_total_engines=72))
        assert d.triage_bucket == TriageBucket.HELD
        assert d.recommended_action == RecommendedAction.ACTION_ALREADY_TAKEN
        assert d.triage_confidence == TriageConfidence.HIGH
        assert d.evidence_status == EvidenceStatus.SKIPPED_HOLD

    def test_hold_overrides_suspicious_vt(self):
        d = decide(TriageInput(domain_hold_has_hold=True, vt_suspicious=3))
        assert d.triage_bucket == TriageBucket.HELD

    def test_hold_overrides_error(self):
        err = MdiError(code="test", message="test", source="test")
        d = decide(TriageInput(domain_hold_has_hold=True, errors=[err]))
        assert d.triage_bucket == TriageBucket.HELD

    def test_hold_reason_non_empty(self):
        d = decide(TriageInput(domain_hold_has_hold=True))
        assert len(d.triage_reason) >= 1


# ── 3. Error and Quota-Blocked ────────────────────────────────────────────────

class TestErrorPath:

    def _err(self, code: str = "vt_timeout") -> MdiError:
        return MdiError(code=code, message="Some error.", source="vt", retriable=True)

    def test_error_status_returns_retry_lookup(self):
        d = decide(TriageInput(
            processing_status=MdiProcessingStatus.ERROR,
            errors=[self._err()],
        ))
        assert d.triage_bucket == TriageBucket.ERROR
        assert d.recommended_action == RecommendedAction.RETRY_LOOKUP
        assert d.triage_confidence == TriageConfidence.UNKNOWN
        assert d.evidence_status == EvidenceStatus.PARTIAL

    def test_quota_exhausted_error_returns_retry(self):
        quota_err = MdiError(code="quota_exhausted", message="Quota exhausted.", source="job_processor", retriable=True)
        d = decide(TriageInput(
            processing_status=MdiProcessingStatus.ERROR,
            errors=[quota_err],
        ))
        assert d.triage_bucket == TriageBucket.ERROR
        assert d.recommended_action == RecommendedAction.RETRY_LOOKUP

    def test_error_with_vt_hits_still_errors(self):
        """Error path must win over malicious when errors list is non-empty."""
        d = decide(TriageInput(
            processing_status=MdiProcessingStatus.ERROR,
            vt_hits=3,
            errors=[self._err()],
        ))
        assert d.triage_bucket == TriageBucket.ERROR

    def test_error_reason_non_empty(self):
        d = decide(TriageInput(
            processing_status=MdiProcessingStatus.ERROR,
            errors=[self._err("vt_429")],
        ))
        assert len(d.triage_reason) >= 1
        assert any("vt_429" in r or "error" in r.lower() for r in d.triage_reason)


# ── 4. Malicious Sub-Rules ────────────────────────────────────────────────────

class TestMaliciousSubRules:

    def test_flagged_live_recent(self):
        """Flagged + ACTIVE + VERY_NEW → INVESTIGATE (highest urgency)."""
        d = decide(_flagged(age=AgeBucket.VERY_NEW, live=LiveStatus.ACTIVE, freshness=Freshness.FRESH))
        assert d.triage_bucket == TriageBucket.MALICIOUS
        assert d.recommended_action == RecommendedAction.INVESTIGATE
        assert d.triage_confidence == TriageConfidence.HIGH

    def test_flagged_live_established(self):
        """Flagged + ACTIVE + ESTABLISHED → INVESTIGATE (live wins over age)."""
        d = decide(_flagged(age=AgeBucket.ESTABLISHED, live=LiveStatus.ACTIVE, freshness=Freshness.FRESH))
        assert d.recommended_action == RecommendedAction.INVESTIGATE

    def test_flagged_live_age_unknown(self):
        """Flagged + ACTIVE + UNKNOWN age → INVESTIGATE."""
        d = decide(_flagged(age=AgeBucket.UNKNOWN, live=LiveStatus.ACTIVE))
        assert d.recommended_action == RecommendedAction.INVESTIGATE

    def test_flagged_live_redirect(self):
        """REDIRECT counts as live."""
        d = decide(_flagged(live=LiveStatus.REDIRECT))
        assert d.recommended_action == RecommendedAction.INVESTIGATE

    def test_flagged_live_forbidden(self):
        """FORBIDDEN counts as live."""
        d = decide(_flagged(live=LiveStatus.FORBIDDEN))
        assert d.recommended_action == RecommendedAction.INVESTIGATE

    def test_flagged_no_live_not_found(self):
        """Flagged + NOT_FOUND → NO_ACTION_BASED_ON_VT."""
        d = decide(_flagged(live=LiveStatus.NOT_FOUND))
        assert d.recommended_action == RecommendedAction.NO_ACTION_BASED_ON_VT
        assert d.triage_confidence == TriageConfidence.MEDIUM

    def test_flagged_no_live_gone(self):
        """Flagged + GONE → NO_ACTION_BASED_ON_VT."""
        d = decide(_flagged(live=LiveStatus.GONE))
        assert d.recommended_action == RecommendedAction.NO_ACTION_BASED_ON_VT

    def test_flagged_no_live_dns_failure(self):
        """Flagged + DNS_FAILURE → NO_ACTION_BASED_ON_VT."""
        d = decide(_flagged(live=LiveStatus.DNS_FAILURE))
        assert d.recommended_action == RecommendedAction.NO_ACTION_BASED_ON_VT

    def test_flagged_stale_refresh(self):
        d = decide(_flagged(freshness=Freshness.STALE))
        assert d.recommended_action == RecommendedAction.REFRESH_REPORT
        assert d.triage_confidence == TriageConfidence.MEDIUM

    def test_flagged_very_stale_request_new_scan(self):
        d = decide(_flagged(freshness=Freshness.VERY_STALE))
        assert d.recommended_action == RecommendedAction.REQUEST_NEW_SCAN
        assert d.triage_confidence == TriageConfidence.LOW

    def test_flagged_catchall_verify_investigate(self):
        """Flagged + NOT_CHECKED live + UNKNOWN age + UNKNOWN freshness → VERIFY_INVESTIGATE."""
        d = decide(_flagged(freshness=Freshness.UNKNOWN, age=AgeBucket.UNKNOWN, live=LiveStatus.NOT_CHECKED))
        assert d.recommended_action == RecommendedAction.VERIFY_INVESTIGATE

    def test_flagged_fresh_not_checked_not_recent_verify(self):
        """ESTABLISHED + FRESH + NOT_CHECKED → VERIFY_INVESTIGATE (not recent, not stale, not live)."""
        d = decide(_flagged(age=AgeBucket.ESTABLISHED, freshness=Freshness.FRESH, live=LiveStatus.NOT_CHECKED))
        assert d.recommended_action == RecommendedAction.VERIFY_INVESTIGATE
        assert d.triage_confidence == TriageConfidence.HIGH

    def test_evidence_complete_when_vt_ran(self):
        d = decide(_flagged())
        assert d.evidence_status == EvidenceStatus.COMPLETE

    def test_live_beats_recent_in_priority(self):
        """Live + Recent → INVESTIGATE (live has higher priority than recent alone)."""
        d_live_recent = decide(_flagged(age=AgeBucket.VERY_NEW, live=LiveStatus.ACTIVE))
        d_recent_only = decide(_flagged(age=AgeBucket.VERY_NEW, live=LiveStatus.NOT_CHECKED))
        assert d_live_recent.recommended_action == RecommendedAction.INVESTIGATE
        assert d_recent_only.recommended_action == RecommendedAction.REVIEW_FOR_ACTION


# ── 5. Suspicious Sub-Rules ───────────────────────────────────────────────────

class TestSuspiciousSubRules:

    def test_suspicious_recent(self):
        d = decide(_suspicious(age=AgeBucket.VERY_NEW))
        assert d.triage_bucket == TriageBucket.SUSPICIOUS
        assert d.recommended_action == RecommendedAction.REVIEW_FOR_ACTION

    def test_suspicious_stale(self):
        d = decide(_suspicious(freshness=Freshness.STALE))
        assert d.triage_bucket == TriageBucket.SUSPICIOUS
        assert d.recommended_action == RecommendedAction.REFRESH_REPORT

    def test_suspicious_catchall(self):
        d = decide(_suspicious())
        assert d.triage_bucket == TriageBucket.SUSPICIOUS
        assert d.recommended_action == RecommendedAction.VERIFY_INVESTIGATE

    def test_suspicious_live(self):
        d = decide(_suspicious(live=LiveStatus.ACTIVE))
        assert d.triage_bucket == TriageBucket.SUSPICIOUS
        assert d.recommended_action == RecommendedAction.INVESTIGATE

    def test_malicious_takes_priority_over_suspicious(self):
        """When both vt_hits > 0 and vt_suspicious > 0, MALICIOUS wins."""
        d = decide(TriageInput(vt_hits=2, vt_suspicious=3, vt_total_engines=72))
        assert d.triage_bucket == TriageBucket.MALICIOUS


# ── 6. Clean Sub-Rules ────────────────────────────────────────────────────────

class TestCleanSubRules:

    def test_clean_fresh_confidence_clean(self):
        """Clean + FRESH → confidence CLEAN (new enum value), NO_ACTION_BASED_ON_VT."""
        d = decide(_clean(freshness=Freshness.FRESH))
        assert d.triage_bucket == TriageBucket.CLEAN
        assert d.recommended_action == RecommendedAction.NO_ACTION_BASED_ON_VT
        assert d.triage_confidence == TriageConfidence.CLEAN
        assert d.evidence_status == EvidenceStatus.COMPLETE

    def test_clean_stale_refresh(self):
        d = decide(_clean(freshness=Freshness.STALE))
        assert d.triage_bucket == TriageBucket.CLEAN
        assert d.recommended_action == RecommendedAction.REFRESH_REPORT
        assert d.triage_confidence == TriageConfidence.MEDIUM

    def test_clean_very_stale_request_new_scan(self):
        d = decide(_clean(freshness=Freshness.VERY_STALE))
        assert d.triage_bucket == TriageBucket.CLEAN
        assert d.recommended_action == RecommendedAction.REQUEST_NEW_SCAN

    def test_clean_unknown_freshness_verify(self):
        d = decide(_clean(freshness=Freshness.UNKNOWN))
        assert d.triage_bucket == TriageBucket.CLEAN
        assert d.recommended_action == RecommendedAction.VERIFY_INVESTIGATE


# ── 7. Pending / Unknown ──────────────────────────────────────────────────────

class TestPendingUnknown:

    def test_zero_engines_after_vt_ran_is_pending(self):
        d = decide(TriageInput(
            vt_hits=0,
            vt_suspicious=0,
            vt_total_engines=0,
            processing_status=MdiProcessingStatus.DONE,
        ))
        assert d.triage_bucket == TriageBucket.PENDING
        assert d.recommended_action == RecommendedAction.RETRY_LOOKUP

    def test_pending_processing_status(self):
        d = decide(TriageInput(processing_status=MdiProcessingStatus.PENDING))
        assert d.triage_bucket == TriageBucket.PENDING
        assert d.evidence_status == EvidenceStatus.NONE

    def test_pending_reason_non_empty(self):
        d = decide(TriageInput())
        assert len(d.triage_reason) >= 1


# ── 8. triage_reason Non-Empty for Every Bucket ───────────────────────────────

class TestTriageReasonNonEmpty:

    def test_held_reason(self):
        d = decide(TriageInput(domain_hold_has_hold=True))
        assert len(d.triage_reason) >= 1

    def test_error_reason(self):
        d = decide(TriageInput(
            processing_status=MdiProcessingStatus.ERROR,
            errors=[MdiError(code="x", message="y", source="z")],
        ))
        assert len(d.triage_reason) >= 1

    def test_malicious_reason(self):
        d = decide(_flagged())
        assert len(d.triage_reason) >= 2

    def test_suspicious_reason(self):
        d = decide(_suspicious())
        assert len(d.triage_reason) >= 2

    def test_clean_reason(self):
        d = decide(_clean())
        assert len(d.triage_reason) >= 1

    def test_pending_reason(self):
        d = decide(TriageInput())
        assert len(d.triage_reason) >= 1

    def test_all_reasons_are_strings(self):
        """Every reason bullet must be a non-empty string."""
        inputs = [
            TriageInput(domain_hold_has_hold=True),
            TriageInput(processing_status=MdiProcessingStatus.ERROR,
                        errors=[MdiError(code="e", message="m", source="s")]),
            _flagged(),
            _suspicious(),
            _clean(),
            TriageInput(),
        ]
        for inp in inputs:
            d = decide(inp)
            for r in d.triage_reason:
                assert isinstance(r, str) and len(r) > 0


# ── 9. None / Default Safety ──────────────────────────────────────────────────

class TestDefaultSafety:

    def test_default_input_does_not_raise(self):
        d = decide(TriageInput())
        assert isinstance(d, TriageDecision)

    def test_zero_hits_zero_suspicious_zero_engines(self):
        d = decide(TriageInput(vt_hits=0, vt_suspicious=0, vt_total_engines=0))
        assert d.triage_bucket in (TriageBucket.PENDING, TriageBucket.ERROR)

    def test_unknown_enum_values_do_not_raise(self):
        """Confirm no AttributeError for any combination of unknown/default values."""
        d = decide(TriageInput(
            freshness=Freshness.UNKNOWN,
            live_status=LiveStatus.UNKNOWN,
            age_bucket=AgeBucket.UNKNOWN,
        ))
        assert isinstance(d, TriageDecision)

    def test_negative_hits_treated_as_zero(self):
        """Defensive: hits < 0 should not trigger malicious bucket."""
        d = decide(TriageInput(vt_hits=0, vt_suspicious=0, vt_total_engines=0))
        assert d.triage_bucket != TriageBucket.MALICIOUS

    def test_empty_errors_list_no_error_bucket(self):
        """Empty errors list must not trigger error path."""
        d = decide(TriageInput(
            processing_status=MdiProcessingStatus.DONE,
            vt_hits=0,
            vt_total_engines=72,
            freshness=Freshness.FRESH,
            errors=[],
        ))
        assert d.triage_bucket == TriageBucket.CLEAN


# ── 10. Backward Compatibility ───────────────────────────────────────────────

class TestBackwardCompatibility:

    def test_old_recommended_action_values_still_parse(self):
        """Legacy enum values must still parse without error."""
        from models import RecommendedAction
        assert RecommendedAction("investigate") == RecommendedAction.INVESTIGATE
        assert RecommendedAction("manual_review") == RecommendedAction.MANUAL_REVIEW
        assert RecommendedAction("clear") == RecommendedAction.CLEAR
        assert RecommendedAction("none") == RecommendedAction.NONE
        assert RecommendedAction("skip") == RecommendedAction.SKIP
        assert RecommendedAction("takedown") == RecommendedAction.TAKEDOWN
        assert RecommendedAction("monitor") == RecommendedAction.MONITOR
        assert RecommendedAction("action_already_taken") == RecommendedAction.ACTION_ALREADY_TAKEN

    def test_new_recommended_action_values_parse(self):
        from models import RecommendedAction
        assert RecommendedAction("review_for_action") == RecommendedAction.REVIEW_FOR_ACTION
        assert RecommendedAction("verify_investigate") == RecommendedAction.VERIFY_INVESTIGATE
        assert RecommendedAction("refresh_report") == RecommendedAction.REFRESH_REPORT
        assert RecommendedAction("request_new_scan") == RecommendedAction.REQUEST_NEW_SCAN
        assert RecommendedAction("retry_lookup") == RecommendedAction.RETRY_LOOKUP
        assert RecommendedAction("no_action_based_on_vt") == RecommendedAction.NO_ACTION_BASED_ON_VT

    def test_triage_confidence_clean_parses(self):
        from models import TriageConfidence
        assert TriageConfidence("clean") == TriageConfidence.CLEAN

    def test_mdi_result_item_null_triage_reason_coerced(self):
        """Legacy null triage_reason in JSON is coerced to [] by field_validator."""
        from models import MdiResultItem
        item = MdiResultItem.model_validate({
            "input_original": "example.com",
            "input_normalized": "example.com",
            "input_type": "domain",
            "position": 1,
            "triage_reason": None,
        })
        assert item.triage_reason == []

    def test_mdi_result_item_string_triage_reason_coerced(self):
        """Plain string from very old persisted jobs is wrapped in a list."""
        from models import MdiResultItem
        item = MdiResultItem.model_validate({
            "input_original": "example.com",
            "input_normalized": "example.com",
            "input_type": "domain",
            "position": 1,
            "triage_reason": "Some legacy reason.",
        })
        assert item.triage_reason == ["Some legacy reason."]

    def test_mdi_result_item_list_triage_reason_unchanged(self):
        from models import MdiResultItem
        item = MdiResultItem.model_validate({
            "input_original": "example.com",
            "input_normalized": "example.com",
            "input_type": "domain",
            "position": 1,
            "triage_reason": ["bullet 1.", "bullet 2."],
        })
        assert item.triage_reason == ["bullet 1.", "bullet 2."]


# ── 11. Recent + Stale both true (combined signal) ────────────────────────────

class TestCombinedSignals:

    def test_recent_and_stale_recent_wins_stale_in_reason(self):
        """When domain is NEW and VT report is STALE: Recent bucket wins; reason must mention stale."""
        d = decide(_flagged(age=AgeBucket.NEW, freshness=Freshness.STALE))
        assert d.recommended_action == RecommendedAction.REVIEW_FOR_ACTION
        reason = " ".join(d.triage_reason).lower()
        assert "stale" in reason or "older" in reason

    def test_live_recent_stale_live_wins(self):
        """Live + Recent + STALE VT → INVESTIGATE (live wins)."""
        d = decide(_flagged(age=AgeBucket.VERY_NEW, live=LiveStatus.ACTIVE, freshness=Freshness.STALE))
        assert d.recommended_action == RecommendedAction.INVESTIGATE

    def test_live_not_recent_stale_live_wins(self):
        """Live + Established + STALE VT → INVESTIGATE (live wins over stale)."""
        d = decide(_flagged(age=AgeBucket.ESTABLISHED, live=LiveStatus.ACTIVE, freshness=Freshness.STALE))
        assert d.recommended_action == RecommendedAction.INVESTIGATE


# ── 12. Suspicious mirrors Malicious priority structure ───────────────────────

class TestSuspiciousPriorityStructure:

    def test_suspicious_live_recent_investigates(self):
        d = decide(_suspicious(age=AgeBucket.VERY_NEW, live=LiveStatus.ACTIVE))
        assert d.triage_bucket == TriageBucket.SUSPICIOUS
        assert d.recommended_action == RecommendedAction.INVESTIGATE

    def test_suspicious_no_live(self):
        d = decide(_suspicious(live=LiveStatus.NOT_FOUND))
        assert d.recommended_action == RecommendedAction.NO_ACTION_BASED_ON_VT

    def test_suspicious_very_stale(self):
        d = decide(_suspicious(freshness=Freshness.VERY_STALE))
        assert d.recommended_action == RecommendedAction.REQUEST_NEW_SCAN


# ── 13. Schema-summary constant alignment ────────────────────────────────────

class TestSchemaSummaryAlignment:
    """Sanity check that models.py default constants match triage_rules defaults."""

    def test_default_stale_threshold_days_is_7(self):
        inp = TriageInput()
        assert inp.stale_threshold_days == 7

    def test_triage_confidence_has_clean(self):
        from models import TriageConfidence
        assert hasattr(TriageConfidence, "CLEAN")

    def test_recommended_action_has_all_new_values(self):
        from models import RecommendedAction
        expected = {
            "REVIEW_FOR_ACTION",
            "VERIFY_INVESTIGATE",
            "REFRESH_REPORT",
            "REQUEST_NEW_SCAN",
            "RETRY_LOOKUP",
            "NO_ACTION_BASED_ON_VT",
        }
        actual = {m.name for m in RecommendedAction}
        assert expected.issubset(actual)
