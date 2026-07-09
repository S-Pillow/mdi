"""
MDI-62 — Manual Request New Scan URL completedness gate tests.

All VT HTTP is mocked. No live external calls. No quota consumed.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.vt_service as vt_svc
from models import (
    EvidenceStatus,
    Freshness,
    InputType,
    JobActionRequest,
    LiveStatus,
    MdiProcessingStatus,
    MdiResultItem,
    RecommendedAction,
    RefreshScanScope,
    TriageBucket,
    TriageConfidence,
    VtModeUsed,
)
from services import job_actions, triage_rules
from services.export_service import format_export_result
from services.job_store import InMemoryJob
from services.pending_analysis import is_pending_analysis
from services.vt_service import report_is_completed


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


def _empty_pending_url_report() -> dict:
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


def _scan_side_effect(responses):
    """responses: list of (method_filter, status, body) for GET after POST."""
    get_idx = 0

    async def side(method, url, **kwargs):
        nonlocal get_idx
        if method == "POST" and url.endswith("/urls"):
            return _mock_resp(200, {"data": {"id": "url-id"}})
        if method == "GET" and "/urls/" in url:
            idx = min(get_idx, len(responses) - 1)
            _, status, body = responses[idx]
            get_idx += 1
            return _mock_resp(status, body)
        return _mock_resp(404)

    return side


def _make_job(items, **kwargs) -> InMemoryJob:
    job = InMemoryJob(
        job_id=kwargs.get("job_id", "mdi62-job"),
        status="done",
        submitted_at=time.time(),
        total=len(items),
        **{k: v for k, v in kwargs.items() if k != "job_id"},
    )
    for item in items:
        job.results[item.input_normalized] = item
        job.item_order.append(item.input_normalized)
    return job


def _make_url_row(
    url: str,
    *,
    position: int = 1,
    freshness=Freshness.VERY_STALE,
    vt_hits=0,
    vt_total_engines=0,
    vt_ratio="",
    triage_bucket=TriageBucket.PENDING,
):
    return MdiResultItem(
        input_original=url,
        input_normalized=url,
        input_type=InputType.URL,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_hits=vt_hits,
        vt_suspicious=0,
        vt_total_engines=vt_total_engines,
        vt_ratio=vt_ratio,
        vt_scan_date=None if vt_total_engines == 0 else None,
        freshness=freshness,
        triage_bucket=triage_bucket,
        triage_confidence=TriageConfidence.UNKNOWN,
        recommended_action=RecommendedAction.REFRESH_REPORT,
        evidence_status=EvidenceStatus.PARTIAL,
        live_status=LiveStatus.NOT_CHECKED,
    )


# ── vt_service: completed scan outcomes ─────────────────────────────────────

class TestScanCompletedReport:

    def test_zero_detection_clean(self):
        body = _completed_url_report(malicious=0, suspicious=0)
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 side_effect=_scan_side_effect([("GET", 200, body)]))), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.request_new_scan(
                "https://clean.example/path", InputType.URL,
            ))

        assert result.error is None
        assert report_is_completed(result)
        assert result.vt_total_engines == 75
        assert result.vt_ratio == "0/75"
        dec = triage_rules.decide(triage_rules.TriageInput(
            processing_status=MdiProcessingStatus.DONE,
            vt_hits=0, vt_suspicious=0, vt_total_engines=result.vt_total_engines,
            freshness=result.freshness,
        ))
        assert dec.triage_bucket == TriageBucket.CLEAN
        assert dec.recommended_action == RecommendedAction.NO_ACTION_BASED_ON_VT

    def test_detection_report(self):
        body = _completed_url_report(malicious=2, suspicious=1)
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 side_effect=_scan_side_effect([("GET", 200, body)]))), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.request_new_scan(
                "https://bad.example/path", InputType.URL,
            ))

        assert result.error is None
        assert result.vt_malicious == 2
        assert result.vt_suspicious == 1
        dec = triage_rules.decide(triage_rules.TriageInput(
            processing_status=MdiProcessingStatus.DONE,
            vt_hits=result.vt_malicious,
            vt_suspicious=result.vt_suspicious,
            vt_total_engines=result.vt_total_engines,
            freshness=result.freshness,
        ))
        assert dec.triage_bucket == TriageBucket.MALICIOUS


# ── vt_service: incomplete outcomes ───────────────────────────────────────────

class TestScanIncompleteReport:

    def test_incomplete_200_is_pending_not_clean(self):
        empty = _empty_pending_url_report()
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 side_effect=_scan_side_effect([("GET", 200, empty)]))), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.request_new_scan(
                "http://queued.example/", InputType.URL,
            ))

        assert result.error is not None
        assert result.error.code == "vt_scan_pending"
        assert result.vt_total_engines == 0
        assert result.vt_ratio == ""
        assert result.freshness == Freshness.NEVER_SCANNED
        assert not report_is_completed(result)
        dec = triage_rules.decide(triage_rules.TriageInput(
            processing_status=MdiProcessingStatus.DONE,
            vt_hits=0, vt_suspicious=0, vt_total_engines=0,
            freshness=Freshness.NEVER_SCANNED,
            errors=[result.error],
        ))
        assert dec.triage_bucket == TriageBucket.PENDING
        assert dec.triage_bucket != TriageBucket.CLEAN
        assert dec.recommended_action == RecommendedAction.REFRESH_REPORT
        assert dec.evidence_status == EvidenceStatus.PARTIAL

    def test_stats_without_scan_date_not_completed(self):
        body = _completed_url_report(malicious=0)
        del body["data"]["attributes"]["last_analysis_date"]
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 side_effect=_scan_side_effect([("GET", 200, body)]))), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.request_new_scan(
                "http://partial.example/", InputType.URL,
            ))

        assert result.error is not None
        assert result.error.code == "vt_scan_pending"
        assert not report_is_completed(result)


# ── Poll-loop behavior ────────────────────────────────────────────────────────

class TestScanPollLoop:

    def test_incomplete_then_complete_within_budget(self):
        empty = _empty_pending_url_report()
        complete = _completed_url_report(malicious=0)
        side = _scan_side_effect([
            ("GET", 200, empty),
            ("GET", 200, complete),
        ])
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=AsyncMock(side_effect=side)), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.request_new_scan(
                "http://retry.example/", InputType.URL,
            ))

        assert result.error is None
        assert report_is_completed(result)
        assert result.calls_made == 3  # POST + 2 GETs
        assert result.calls_made <= vt_svc.URL_SCAN_QUOTA_MAX

    def test_incomplete_until_max_attempts(self):
        empty = _empty_pending_url_report()
        side = _scan_side_effect([
            ("GET", 200, empty),
            ("GET", 200, empty),
            ("GET", 200, empty),
        ])
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=AsyncMock(side_effect=side)), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.request_new_scan(
                "http://still-queued.example/", InputType.URL,
            ))

        assert result.error is not None
        assert result.error.code == "vt_scan_pending"
        assert result.vt_ratio == ""
        assert result.calls_made == 4  # POST + 3 GETs
        assert result.calls_made <= vt_svc.URL_SCAN_QUOTA_MAX

    def test_all_404_poll_regression(self):
        async def side(method, url, **kwargs):
            if method == "POST":
                return _mock_resp(200, {"data": {"id": "url-id"}})
            return _mock_resp(404, {"error": {"code": "NotFoundError"}})

        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=AsyncMock(side_effect=side)), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.request_new_scan(
                "http://not-ready.example/", InputType.URL,
            ))

        assert result.error is not None
        assert result.error.code == "vt_scan_pending"
        assert result.vt_total_engines == 0
        assert result.vt_ratio == ""
        assert "polls" in (result.error.message or "").lower()

    def test_429_regression(self):
        async def side(method, url, **kwargs):
            if method == "POST":
                return _mock_resp(200, {"data": {"id": "url-id"}})
            return _mock_resp(429, {})

        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=AsyncMock(side_effect=side)), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.request_new_scan(
                "http://rate-limited.example/", InputType.URL,
            ))

        assert result.error is not None
        assert result.error.code == "vt_429"
        assert result.vt_total_engines == 0


# ── Job action integration ────────────────────────────────────────────────────

class TestScanJobActionIntegration:

    def test_incomplete_scan_does_not_turn_row_clean(self, tmp_path):
        url = "http://scan-pending.example/"
        row = _make_url_row(url, vt_hits=0, triage_bucket=TriageBucket.PENDING)
        job = _make_job([row])
        empty = _empty_pending_url_report()

        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 side_effect=_scan_side_effect([("GET", 200, empty)]))), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            _run(job_actions._run_items(
                job, [row], "scan",
                usage_file=tmp_path / "u.json",
            ))

        updated = job.results[url]
        assert updated.triage_bucket != TriageBucket.CLEAN
        assert any(e.code == "vt_scan_pending" for e in (updated.errors or []))
        assert updated.vt_ratio in ("", None) or updated.vt_ratio != "0/0"

    def test_incomplete_scan_preserves_prior_evidence(self, tmp_path):
        url = "http://stale-flagged.example/"
        row = _make_url_row(
            url,
            vt_hits=2,
            vt_total_engines=75,
            vt_ratio="2/75",
            triage_bucket=TriageBucket.MALICIOUS,
            freshness=Freshness.VERY_STALE,
        )
        job = _make_job([row])
        empty = _empty_pending_url_report()

        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 side_effect=_scan_side_effect([("GET", 200, empty)]))), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            _run(job_actions._run_items(
                job, [row], "scan",
                usage_file=tmp_path / "u.json",
            ))

        updated = job.results[url]
        assert updated.vt_hits == 2
        assert updated.vt_ratio == "2/75"
        assert updated.triage_bucket == TriageBucket.MALICIOUS
        assert any(e.code == "vt_scan_pending" for e in (updated.errors or []))

    def test_completed_scan_updates_row(self, tmp_path):
        url = "http://scan-clean.example/"
        row = _make_url_row(url, freshness=Freshness.VERY_STALE)
        job = _make_job([row])
        complete = _completed_url_report(malicious=0)

        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 side_effect=_scan_side_effect([("GET", 200, complete)]))), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            _run(job_actions._run_items(
                job, [row], "scan",
                usage_file=tmp_path / "u.json",
            ))

        updated = job.results[url]
        assert updated.triage_bucket == TriageBucket.CLEAN
        assert updated.vt_total_engines == 75
        assert not any(e.code == "vt_scan_pending" for e in (updated.errors or []))


# ── Refresh Pending completion ────────────────────────────────────────────────

class TestScanPendingRefreshLater:

    def test_refresh_clears_manual_scan_pending(self, tmp_path):
        url = "http://manual-pending.example/"
        pending_err = vt_svc._pending_error(vt_svc._PENDING_NOT_READY_MSG)
        row = MdiResultItem(
            input_original=url,
            input_normalized=url,
            input_type=InputType.URL,
            position=1,
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
        )
        job = _make_job([row])

        with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch("services.vt_service._vt_request", new=AsyncMock(
                 return_value=_mock_resp(200, _completed_url_report(0)))), \
             patch("services.job_actions.read_remaining_quota", return_value=100), \
             patch("services.quota_writer.increment_quota", new=AsyncMock()):
            _run(job_actions._run_items(
                job, [row], "refresh",
                usage_file=tmp_path / "u.json",
            ))

        updated = job.results[url]
        assert updated.triage_bucket == TriageBucket.CLEAN
        assert updated.vt_total_engines == 75
        assert not any(e.code == "vt_scan_pending" for e in (updated.errors or []))

    def test_pending_row_exports_pending_analysis(self):
        pending_err = vt_svc._pending_error(vt_svc._PENDING_NOT_READY_MSG)
        row = MdiResultItem(
            input_original="http://export-pending.example/",
            input_normalized="http://export-pending.example/",
            input_type=InputType.URL,
            position=1,
            processing_status=MdiProcessingStatus.DONE,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_total_engines=0,
            vt_ratio="",
            freshness=Freshness.NEVER_SCANNED,
            triage_bucket=TriageBucket.PENDING,
            recommended_action=RecommendedAction.REFRESH_REPORT,
            evidence_status=EvidenceStatus.PARTIAL,
            errors=[pending_err],
        )
        assert is_pending_analysis(row)
        assert format_export_result(row) == "pending_analysis"

    def test_completed_scan_exports_clean(self):
        row = MdiResultItem(
            input_original="http://export-clean.example/",
            input_normalized="http://export-clean.example/",
            input_type=InputType.URL,
            position=1,
            processing_status=MdiProcessingStatus.DONE,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_hits=0,
            vt_total_engines=75,
            vt_ratio="0/75",
            freshness=Freshness.FRESH,
            triage_bucket=TriageBucket.CLEAN,
            recommended_action=RecommendedAction.NO_ACTION_BASED_ON_VT,
            evidence_status=EvidenceStatus.COMPLETE,
        )
        assert format_export_result(row) == "clean"
        assert not is_pending_analysis(row)
