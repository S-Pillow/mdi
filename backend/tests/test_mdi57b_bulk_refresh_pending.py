"""
MDI-57B — Bulk Refresh Pending tests.

All VT / live-check HTTP is mocked. No live /var/lib/dns-tool files touched.
No Request New Scan / URL submit paths are exercised for pending refresh.
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
from services import export_service, job_actions, job_persistence, triage_rules
from services.export_service import format_export_result, _result_json
from services.job_store import InMemoryJob
from services.pending_analysis import (
    has_completed_vt_scan,
    is_pending_analysis,
    is_pending_refresh_eligible,
)
from services.quota_writer import QuotaLockTimeout


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


def _empty_pending_url_report():
    return {
        "data": {
            "attributes": {
                "last_analysis_stats": {
                    "malicious": 0, "suspicious": 0, "harmless": 0,
                    "undetected": 0, "timeout": 0,
                },
                "times_submitted": 1,
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


def _stale_flagged_row(normalized: str = "stale.example.com", *, position: int = 1) -> MdiResultItem:
    return MdiResultItem(
        input_original=normalized,
        input_normalized=normalized,
        input_type=InputType.DOMAIN,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        vt_mode_used=VtModeUsed.DOMAIN_REPORT,
        vt_hits=2,
        vt_suspicious=0,
        vt_total_engines=75,
        vt_ratio="2/75",
        vt_scan_date="2026-01-01T00:00:00Z",
        freshness=Freshness.STALE,
        triage_bucket=TriageBucket.MALICIOUS,
        live_status=LiveStatus.NOT_CHECKED,
        age_bucket=AgeBucket.MATURE,
    )


def _blocking_error_row(normalized: str = "err.example.com", *, position: int = 1) -> MdiResultItem:
    return MdiResultItem(
        input_original=normalized,
        input_normalized=normalized,
        input_type=InputType.URL,
        position=position,
        processing_status=MdiProcessingStatus.ERROR,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=0,
        vt_ratio="",
        vt_scan_date=None,
        freshness=Freshness.UNKNOWN,
        triage_bucket=TriageBucket.ERROR,
        live_status=LiveStatus.NOT_CHECKED,
        errors=[MdiError(
            code="vt_auth",
            message="VT API key is invalid.",
            source="vt_service",
            retriable=False,
            severity="error",
            blocks_triage=True,
        )],
    )


def _make_job(items: list[MdiResultItem], *, job_id: str = "mdi57b-job") -> InMemoryJob:
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


# ── Shared helper ─────────────────────────────────────────────────────────────

class TestPendingAnalysisHelper:

    def test_pending_row_detected(self):
        assert is_pending_analysis(_pending_row())
        assert is_pending_refresh_eligible(_pending_row())

    def test_completed_not_pending(self):
        assert not is_pending_analysis(_clean_row())
        assert has_completed_vt_scan(_clean_row())

    def test_held_pending_shape_not_eligible(self):
        held = _pending_row("http://held-pending.example/", held=True)
        assert not is_pending_analysis(held)
        assert not is_pending_refresh_eligible(held)

    def test_domain_report_not_pending(self):
        row = _clean_row()
        assert row.vt_mode_used == VtModeUsed.DOMAIN_REPORT
        assert not is_pending_analysis(row)

    def test_blocking_error_not_pending(self):
        assert not is_pending_analysis(_blocking_error_row())


# ── Eligibility ───────────────────────────────────────────────────────────────

class TestPendingScopeEligibility:

    def test_selects_only_pending_url_rows(self):
        pending = _pending_row("http://a.example/", position=1)
        clean = _clean_row("clean.example.com", position=2)
        stale = _stale_flagged_row("stale.example.com", position=3)
        job = _make_job([pending, clean, stale])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.PENDING, None, "refresh",
        )
        assert len(sel.eligible) == 1
        assert sel.eligible[0].input_normalized == "http://a.example/"
        assert sel.skipped_reasons.get("not_pending") == 2

    def test_held_rows_skipped(self):
        held = _pending_row("http://held.example/", position=1, held=True)
        ok = _pending_row("http://ok.example/", position=2)
        job = _make_job([held, ok])
        # held pending shape is excluded by helper; also mark as held via hold
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.PENDING, None, "refresh",
        )
        assert len(sel.eligible) == 1
        assert sel.eligible[0].position == 2

    def test_domain_report_rows_skipped(self):
        domain = _clean_row("domain.example.com", position=1)
        pending = _pending_row("http://url.example/", position=2)
        job = _make_job([domain, pending])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.PENDING, None, "refresh",
        )
        assert [r.position for r in sel.eligible] == [2]

    def test_blocking_error_rows_skipped(self):
        err = _blocking_error_row(position=1)
        pending = _pending_row("http://p.example/", position=2)
        job = _make_job([err, pending])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.PENDING, None, "refresh",
        )
        assert len(sel.eligible) == 1
        assert sel.eligible[0].position == 2

    def test_missing_input_skipped(self):
        row = _pending_row("http://missing.example/", position=1)
        row = row.model_copy(update={"input_normalized": ""})
        job = _make_job([row])
        # empty key — put under a placeholder key for store
        job.results.clear()
        job.item_order = ["placeholder"]
        job.results["placeholder"] = row
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.PENDING, None, "refresh",
        )
        assert len(sel.eligible) == 0
        assert sel.skipped_reasons.get("missing_input") == 1

    def test_stale_non_pending_not_selected(self):
        stale = _stale_flagged_row(position=1)
        job = _make_job([stale])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.PENDING, None, "refresh",
        )
        assert len(sel.eligible) == 0

    def test_scan_action_rejects_pending_scope(self):
        pending = _pending_row(position=1)
        job = _make_job([pending])
        sel = job_actions.select_eligible_items(
            job, RefreshScanScope.PENDING, None, "scan",
        )
        assert len(sel.eligible) == 0
        assert sel.skipped_reasons.get("pending_scope_refresh_only") == 1

    def test_selected_and_stale_scopes_unchanged(self):
        pending = _pending_row("http://p.example/", position=1)
        stale = _stale_flagged_row("stale.example.com", position=2)
        job = _make_job([pending, stale])
        sel_stale = job_actions.select_eligible_items(
            job, RefreshScanScope.STALE, None, "refresh",
        )
        assert [r.position for r in sel_stale.eligible] == [2]
        sel_sel = job_actions.select_eligible_items(
            job, RefreshScanScope.SELECTED, [1], "refresh",
        )
        assert [r.position for r in sel_sel.eligible] == [1]


# ── Estimate / quota ──────────────────────────────────────────────────────────

class TestPendingEstimateQuota:

    def test_estimate_one_call_per_pending_row(self, tmp_path):
        rows = [
            _pending_row(f"http://p{i}.example/", position=i)
            for i in range(1, 4)
        ]
        job = _make_job(rows)
        usage = tmp_path / "vt_usage.json"
        usage.write_text(json.dumps({
            "date_utc": "2026-07-09",
            "daily_lookups_used": 10,
            "daily_limit": 500,
        }))
        with patch("services.job_actions.read_remaining_quota", return_value=490):
            est = job_actions.estimate_action(
                job, "refresh",
                JobActionRequest(scope=RefreshScanScope.PENDING),
            )
        assert est.eligible_count == 3
        assert est.estimated_quota_min == 3
        assert est.estimated_quota_max == 3
        assert est.pending_eligible_count == 3
        assert est.will_exceed_quota is False
        assert "1 lookup per pending URL" in est.message

    def test_insufficient_quota_blocks_before_start(self):
        rows = [
            _pending_row(f"http://p{i}.example/", position=i)
            for i in range(1, 4)
        ]
        job = _make_job(rows)
        with patch("services.job_actions.read_remaining_quota", return_value=2):
            est = job_actions.estimate_action(
                job, "refresh",
                JobActionRequest(scope=RefreshScanScope.PENDING),
            )
        assert est.will_exceed_quota is True
        assert "Insufficient quota" in est.message
        assert "needs 3 lookups" in est.message
        assert "only 2 remain" in est.message


# ── Refresh outcomes ──────────────────────────────────────────────────────────

class TestPendingRefreshOutcomes:

    def test_completed_refresh_clears_pending_and_retriages(self, tmp_path):
        row = _pending_row()
        job = _make_job([row])
        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 return_value=_mock_resp(200, _completed_url_report(0)))), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            stats = _run(job_actions._run_items(
                job, [row], "refresh",
                usage_file=tmp_path / "u.json",
                job_file=tmp_path / "j.json",
            ))
        updated = job.results["http://pending.example/"]
        assert stats.quota_units == 1
        assert updated.triage_bucket == TriageBucket.CLEAN
        assert not any(e.code == "vt_scan_pending" for e in (updated.errors or []))
        assert updated.vt_total_engines == 75

    def test_still_pending_stays_pending_not_clean(self, tmp_path):
        row = _pending_row()
        job = _make_job([row])
        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 return_value=_mock_resp(200, _empty_pending_url_report()))), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            _run(job_actions._run_items(
                job, [row], "refresh",
                usage_file=tmp_path / "u.json",
                job_file=tmp_path / "j.json",
            ))
        updated = job.results["http://pending.example/"]
        assert updated.triage_bucket == TriageBucket.PENDING
        assert updated.recommended_action == RecommendedAction.REFRESH_REPORT
        assert any(e.code == "vt_scan_pending" for e in (updated.errors or []))
        assert updated.vt_total_engines == 0
        assert updated.vt_ratio in ("", None)
        assert format_export_result(updated) == "pending_analysis"

    def test_refresh_404_does_not_auto_submit(self, tmp_path):
        row = _pending_row()
        job = _make_job([row])
        mock_req = AsyncMock(return_value=_mock_resp(404, {"error": {"code": "NotFoundError"}}))
        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=mock_req), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            _run(job_actions._run_items(
                job, [row], "refresh",
                usage_file=tmp_path / "u.json",
                job_file=tmp_path / "j.json",
            ))
        # Only GET — no POST submit
        assert mock_req.call_count == 1
        assert mock_req.call_args.args[0] == "GET"
        updated = job.results["http://pending.example/"]
        assert updated.triage_bucket != TriageBucket.CLEAN
        assert any(e.code == "vt_not_found" for e in (updated.errors or []))

    def test_auth_error_not_clean(self, tmp_path):
        row = _pending_row()
        job = _make_job([row])
        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 return_value=_mock_resp(401, {}))), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            _run(job_actions._run_items(
                job, [row], "refresh",
                usage_file=tmp_path / "u.json",
                job_file=tmp_path / "j.json",
            ))
        updated = job.results["http://pending.example/"]
        assert updated.triage_bucket != TriageBucket.CLEAN
        assert any(e.code == "vt_auth" for e in (updated.errors or []))

    def test_no_request_new_scan_or_url_submit(self, tmp_path):
        row = _pending_row()
        job = _make_job([row])
        scan_mock = AsyncMock()
        submit_mock = AsyncMock()
        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 return_value=_mock_resp(200, _completed_url_report(0)))), \
             patch("services.vt_service.request_new_scan", new=scan_mock), \
             patch("services.vt_service._submit_url_for_scan", new=submit_mock), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            _run(job_actions._run_items(
                job, [row], "refresh",
                usage_file=tmp_path / "u.json",
                job_file=tmp_path / "j.json",
            ))
        scan_mock.assert_not_called()
        submit_mock.assert_not_called()

    def test_quota_exhaustion_mid_action_partial(self, tmp_path):
        rows = [
            _pending_row(f"http://p{i}.example/", position=i)
            for i in range(1, 4)
        ]
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
                job, list(rows), "refresh",
                usage_file=tmp_path / "u.json",
                job_file=tmp_path / "j.json",
            ))
        # First two processed; third skipped due to remaining<=0
        assert stats.quota_units == 2
        assert job.results["http://p1.example/"].triage_bucket == TriageBucket.CLEAN
        assert job.results["http://p2.example/"].triage_bucket == TriageBucket.CLEAN
        assert is_pending_analysis(job.results["http://p3.example/"])

    def test_run_refresh_action_clears_action_in_progress(self, tmp_path):
        row = _pending_row()
        job = _make_job([row], job_id="mdi57b-persist")
        job_file = tmp_path / "mdi_latest_job.json"
        usage = tmp_path / "vt_usage.json"
        usage.write_text(json.dumps({
            "date_utc": "2026-07-09",
            "daily_lookups_used": 0,
            "daily_limit": 500,
        }))
        history = tmp_path / "history.jsonl"
        daily = tmp_path / "daily.json"

        with patch("services.job_actions.resolve_job", new=AsyncMock(return_value=job)), \
             _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 return_value=_mock_resp(200, _completed_url_report(0)))), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()), \
             patch("services.quota_writer.append_usage_history"), \
             patch("services.quota_writer.update_daily_history"):
            _run(job_actions.run_refresh_action(
                "mdi57b-persist",
                JobActionRequest(scope=RefreshScanScope.PENDING),
                usage_file=usage,
                history_file=history,
                daily_file=daily,
                job_file=job_file,
            ))
        assert job.action_in_progress is False
        assert job.last_action_type == "refresh"
        assert job_file.exists()


# ── Export ────────────────────────────────────────────────────────────────────

class TestPendingExportUnchanged:

    def test_pending_export_result(self):
        assert format_export_result(_pending_row()) == "pending_analysis"

    def test_pending_json_flag(self):
        payload = _result_json(_pending_row())
        assert payload["pending_analysis"] is True

    def test_helper_aligned_with_export(self):
        row = _pending_row()
        assert is_pending_analysis(row)
        assert format_export_result(row) == "pending_analysis"
