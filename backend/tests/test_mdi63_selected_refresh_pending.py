"""
MDI-63 — Selected Refresh Pending tests.

All VT / live-check HTTP is mocked. No live /var/lib/dns-tool files touched.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.vt_service as vt_svc
from models import (
    AgeBucket,
    DomainHold,
    DomainHoldType,
    DomainStatusSource,
    EvidenceStatus,
    Freshness,
    InputType,
    JobActionRequest,
    LiveStatus,
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
    RecommendedAction,
    RefreshScanScope,
    TriageBucket,
    TriageConfidence,
    VtModeUsed,
)
from services import job_actions, triage_rules
from services.job_actions import ActionStats
from services.job_store import InMemoryJob
from services.pending_analysis import is_pending_analysis, is_pending_refresh_eligible


def _run(coro):
    return asyncio.run(coro)


def _mock_resp(status_code: int, body: dict = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    return m


def _no_limiter():
    return patch.object(vt_svc._VT_LIMITER, "acquire", new=AsyncMock())


def _completed_url_report(malicious=0, suspicious=0, age_days=1):
    return {
        "data": {
            "attributes": {
                "last_analysis_stats": {
                    "malicious": malicious,
                    "suspicious": suspicious,
                    "harmless": 70,
                    "undetected": 5,
                    "timeout": 0,
                },
                "last_analysis_date": int(time.time()) - age_days * 86400,
            }
        }
    }


def _pending_row(
    url: str = "http://pending.example/",
    *,
    position: int = 1,
    held: bool = False,
) -> MdiResultItem:
    pending_err = vt_svc._pending_error(vt_svc._PENDING_SUBMITTED_MSG)
    hold = DomainHold(
        has_hold=held,
        hold_types=[DomainHoldType.CLIENT_HOLD] if held else [DomainHoldType.NONE],
        source=DomainStatusSource.RDAP if held else DomainStatusSource.NOT_CHECKED,
    )
    return MdiResultItem(
        input_original=url,
        input_normalized=url if not held else url,
        input_type=InputType.URL,
        position=position,
        processing_status=MdiProcessingStatus.HOLD_SKIPPED if held else MdiProcessingStatus.DONE,
        domain_hold=hold,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=0,
        vt_ratio="",
        vt_scan_date=None,
        freshness=Freshness.NEVER_SCANNED,
        triage_bucket=TriageBucket.PENDING,
        triage_confidence=TriageConfidence.UNKNOWN,
        recommended_action=RecommendedAction.REFRESH_REPORT,
        evidence_status=EvidenceStatus.PARTIAL,
        triage_reason=triage_rules._pending_analysis_reason(),
        live_status=LiveStatus.NOT_CHECKED,
        errors=[pending_err],
        age_bucket=AgeBucket.UNKNOWN,
    )


def _clean_row(normalized: str = "clean.example.com", *, position: int = 1) -> MdiResultItem:
    return MdiResultItem(
        input_original=normalized,
        input_normalized=normalized,
        input_type=InputType.DOMAIN,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        vt_mode_used=VtModeUsed.DOMAIN_REPORT,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=75,
        vt_ratio="0/75",
        vt_scan_date="2026-07-01T00:00:00Z",
        freshness=Freshness.FRESH,
        triage_bucket=TriageBucket.CLEAN,
        live_status=LiveStatus.NOT_CHECKED,
        age_bucket=AgeBucket.MATURE,
    )


def _clean_url_row(url: str = "http://clean-url.example/", *, position: int = 1) -> MdiResultItem:
    return MdiResultItem(
        input_original=url,
        input_normalized=url,
        input_type=InputType.URL,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=75,
        vt_ratio="0/75",
        vt_scan_date="2026-07-01T00:00:00Z",
        freshness=Freshness.FRESH,
        triage_bucket=TriageBucket.CLEAN,
        live_status=LiveStatus.NOT_CHECKED,
        age_bucket=AgeBucket.MATURE,
    )


def _carryforward_row(url: str = "http://carryforward.example/", *, position: int = 1) -> MdiResultItem:
    """MDI-62 carryforward: prior completed evidence + vt_scan_pending warning."""
    pending_err = vt_svc._pending_error(vt_svc._PENDING_NOT_READY_MSG)
    return MdiResultItem(
        input_original=url,
        input_normalized=url,
        input_type=InputType.URL,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=75,
        vt_ratio="0/75",
        vt_scan_date="2026-07-01T00:00:00Z",
        freshness=Freshness.FRESH,
        triage_bucket=TriageBucket.CLEAN,
        recommended_action=RecommendedAction.NO_ACTION_BASED_ON_VT,
        evidence_status=EvidenceStatus.COMPLETE,
        live_status=LiveStatus.NOT_CHECKED,
        errors=[pending_err],
        age_bucket=AgeBucket.MATURE,
    )


def _manual_scan_pending_row(url: str = "http://manual-pending.example/", *, position: int = 1) -> MdiResultItem:
    pending_err = vt_svc._pending_error(vt_svc._PENDING_NOT_READY_MSG)
    return MdiResultItem(
        input_original=url,
        input_normalized=url,
        input_type=InputType.URL,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=0,
        vt_ratio="",
        vt_scan_date=None,
        freshness=Freshness.NEVER_SCANNED,
        triage_bucket=TriageBucket.PENDING,
        triage_confidence=TriageConfidence.UNKNOWN,
        recommended_action=RecommendedAction.REFRESH_REPORT,
        evidence_status=EvidenceStatus.PARTIAL,
        triage_reason=triage_rules._pending_analysis_reason(),
        live_status=LiveStatus.NOT_CHECKED,
        errors=[pending_err],
        age_bucket=AgeBucket.UNKNOWN,
    )


def _make_job(items: list[MdiResultItem], *, job_id: str = "mdi63-job") -> InMemoryJob:
    job = InMemoryJob(
        job_id=job_id,
        status="done",
        submitted_at=time.time() - 100,
        completed_at=time.time() - 50,
        total=len(items),
        processed=len(items),
        use_domain_reports=False,
        stale_threshold_days=30,
    )
    for item in items:
        job.results[item.input_normalized] = item
        job.item_order.append(item.input_normalized)
    return job


# ── Estimate ──────────────────────────────────────────────────────────────────

class TestSelectedPendingEstimate:

    def test_estimate_one_selected_pending_row(self):
        pending = _pending_row("http://a.example/", position=1)
        job = _make_job([pending])
        with patch("services.job_actions.read_remaining_quota", return_value=100):
            est = job_actions.estimate_action(
                job, "refresh",
                JobActionRequest(scope=RefreshScanScope.SELECTED_PENDING, positions=[1]),
            )
        assert est.eligible_count == 1
        assert est.pending_eligible_count == 1
        assert est.estimated_quota_min == 1
        assert est.estimated_quota_max == 1
        assert est.will_exceed_quota is False

    def test_estimate_multiple_selected_pending_rows(self):
        rows = [_pending_row(f"http://p{i}.example/", position=i) for i in range(1, 4)]
        job = _make_job(rows)
        with patch("services.job_actions.read_remaining_quota", return_value=100):
            est = job_actions.estimate_action(
                job, "refresh",
                JobActionRequest(scope=RefreshScanScope.SELECTED_PENDING, positions=[1, 2, 3]),
            )
        assert est.eligible_count == 3
        assert est.pending_eligible_count == 3
        assert est.estimated_quota_min == 3
        assert est.estimated_quota_max == 3

    def test_mixed_selection_skips_non_pending(self):
        pending = _pending_row("http://p.example/", position=1)
        clean = _clean_url_row("http://clean.example/", position=2)
        domain = _clean_row("domain.example.com", position=3)
        job = _make_job([pending, clean, domain])
        with patch("services.job_actions.read_remaining_quota", return_value=100):
            est = job_actions.estimate_action(
                job, "refresh",
                JobActionRequest(scope=RefreshScanScope.SELECTED_PENDING, positions=[1, 2, 3]),
            )
        assert est.eligible_count == 1
        assert est.pending_eligible_count == 1
        assert est.skipped_count == 2
        assert est.skipped_reasons_summary.get("not_pending") == 2
        assert "skipped" in est.message.lower()

    def test_zero_eligible_selected_pending(self):
        clean = _clean_url_row(position=1)
        job = _make_job([clean])
        with patch("services.job_actions.read_remaining_quota", return_value=100):
            est = job_actions.estimate_action(
                job, "refresh",
                JobActionRequest(scope=RefreshScanScope.SELECTED_PENDING, positions=[1]),
            )
        assert est.eligible_count == 0
        assert "No selected pending URL rows eligible" in est.message

    def test_quota_hard_stop(self):
        rows = [_pending_row(f"http://p{i}.example/", position=i) for i in range(1, 4)]
        job = _make_job(rows)
        with patch("services.job_actions.read_remaining_quota", return_value=2):
            est = job_actions.estimate_action(
                job, "refresh",
                JobActionRequest(scope=RefreshScanScope.SELECTED_PENDING, positions=[1, 2, 3]),
            )
        assert est.will_exceed_quota is True
        assert "Insufficient quota" in est.message
        assert "needs 3 lookups" in est.message
        assert "only 2 remain" in est.message


# ── Eligibility exclusions ────────────────────────────────────────────────────

class TestSelectedPendingEligibility:

    def test_domain_rows_excluded(self):
        domain = _clean_row("domain.example.com", position=1)
        pending = _pending_row("http://p.example/", position=2)
        job = _make_job([domain, pending])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.SELECTED_PENDING, [1, 2], "refresh",
        )
        assert [r.position for r in sel.eligible] == [2]
        assert sel.skipped_reasons.get("not_pending") == 1

    def test_held_rows_excluded(self):
        held = _pending_row("http://held.example/", position=1, held=True)
        ok = _pending_row("http://ok.example/", position=2)
        job = _make_job([held, ok])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.SELECTED_PENDING, [1, 2], "refresh",
        )
        assert [r.position for r in sel.eligible] == [2]

    def test_missing_input_excluded(self):
        row = _pending_row("http://missing.example/", position=1)
        row = row.model_copy(update={"input_normalized": ""})
        job = _make_job([row])
        job.results.clear()
        job.item_order = ["placeholder"]
        job.results["placeholder"] = row
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.SELECTED_PENDING, [1], "refresh",
        )
        assert len(sel.eligible) == 0
        assert sel.skipped_reasons.get("missing_input") == 1

    def test_scan_rejects_selected_pending_scope(self):
        pending = _pending_row(position=1)
        job = _make_job([pending])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.SELECTED_PENDING, [1], "scan",
        )
        assert len(sel.eligible) == 0
        assert sel.skipped_reasons.get("selected_pending_scope_refresh_only") == 1

    def test_mdi62_manual_scan_pending_eligible(self):
        row = _manual_scan_pending_row(position=1)
        assert is_pending_refresh_eligible(row)
        job = _make_job([row])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.SELECTED_PENDING, [1], "refresh",
        )
        assert len(sel.eligible) == 1

    def test_mdi62_carryforward_excluded(self):
        row = _carryforward_row(position=1)
        assert not is_pending_analysis(row)
        job = _make_job([row])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.SELECTED_PENDING, [1], "refresh",
        )
        assert len(sel.eligible) == 0
        assert sel.skipped_reasons.get("not_pending") == 1


# ── Confirm / refresh outcomes ────────────────────────────────────────────────

class TestSelectedPendingConfirm:

    def test_confirm_queues_only_pending_rows(self, tmp_path):
        pending = _pending_row("http://pending.example/", position=1)
        clean = _clean_url_row("http://clean.example/", position=2)
        job = _make_job([pending, clean])
        mock_req = AsyncMock(return_value=_mock_resp(200, _completed_url_report(0)))
        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=mock_req), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            stats = _run(job_actions._run_items(
                job,
                job_actions.select_eligible_items(
                    job, RefreshScanScope.SELECTED_PENDING, [1, 2], "refresh",
                ).eligible,
                "refresh",
                usage_file=tmp_path / "u.json",
            ))
        assert stats.quota_units == 1
        assert mock_req.call_count == 1
        assert job.results["http://pending.example/"].triage_bucket == TriageBucket.CLEAN
        assert job.results["http://clean.example/"].triage_bucket == TriageBucket.CLEAN
        assert job.results["http://clean.example/"].vt_total_engines == 75

    def test_zero_eligible_confirm_blocked(self):
        clean = _clean_url_row(position=1)
        job = _make_job([clean])
        with patch("services.job_actions.read_remaining_quota", return_value=100):
            est = job_actions.estimate_action(
                job, "refresh",
                JobActionRequest(scope=RefreshScanScope.SELECTED_PENDING, positions=[1]),
            )
        assert est.eligible_count == 0

    def test_mid_action_quota_guard_partial(self, tmp_path):
        rows = [_pending_row(f"http://p{i}.example/", position=i) for i in range(1, 4)]
        job = _make_job(rows)
        remaining_values = [2, 1, 0]

        def _remaining(_path=None):
            if not remaining_values:
                return 0
            return remaining_values.pop(0)

        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 return_value=_mock_resp(200, _completed_url_report(0)))), \
             patch("services.job_actions.read_remaining_quota", side_effect=_remaining), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            stats = _run(job_actions._run_items(
                job,
                job_actions.select_eligible_items(
                    job, RefreshScanScope.SELECTED_PENDING, [1, 2, 3], "refresh",
                ).eligible,
                "refresh",
                usage_file=tmp_path / "u.json",
            ))
        assert stats.quota_units == 2
        assert is_pending_analysis(job.results["http://p3.example/"])

    def test_refresh_selected_pending_sets_phase(self, tmp_path):
        row = _pending_row()
        job = _make_job([row], job_id="mdi63-phase")
        job_file = tmp_path / "mdi_latest_job.json"
        usage = tmp_path / "vt_usage.json"
        usage.write_text(json.dumps({
            "date_utc": "2026-07-09",
            "daily_lookups_used": 0,
            "daily_limit": 500,
        }))

        seen = []

        async def capture_run(job_obj, eligible, action, **kwargs):
            seen.append(job_obj.current_phase)
            return ActionStats(items_processed=1, items_completed=1, quota_units=1)

        with patch("services.job_actions.resolve_job", new=AsyncMock(return_value=job)), \
             patch.object(job_actions, "_run_items", new=capture_run):
            _run(job_actions.run_refresh_action(
                "mdi63-phase",
                JobActionRequest(scope=RefreshScanScope.SELECTED_PENDING, positions=[1]),
                usage_file=usage,
                job_file=job_file,
            ))
        assert seen == ["refresh_selected_pending"]


# ── Regressions ───────────────────────────────────────────────────────────────

class TestSelectedPendingRegressions:

    def test_all_pending_scope_unchanged(self):
        rows = [_pending_row(f"http://p{i}.example/", position=i) for i in range(1, 3)]
        job = _make_job(rows)
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.PENDING, None, "refresh",
        )
        assert len(sel.eligible) == 2

    def test_selected_refresh_report_unchanged(self):
        pending = _pending_row("http://p.example/", position=1)
        job = _make_job([pending])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.SELECTED, [1], "refresh",
        )
        assert len(sel.eligible) == 1
        assert sel.eligible[0].position == 1
