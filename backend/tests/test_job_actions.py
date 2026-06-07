"""
MDI-15 — Manual VT refresh/rescan lifecycle tests.

All VT, RDAP/WHOIS, and live-check HTTP is mocked.
No live /var/lib/dns-tool files touched.
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
    Freshness,
    InputType,
    JobActionRequest,
    LiveStatus,
    MdiProcessingStatus,
    MdiResultItem,
    RefreshScanScope,
    TriageBucket,
)
from services import job_actions, job_persistence, job_store, live_check
from services.job_store import InMemoryJob
from services.live_check import LiveCheckResult


def _run(coro):
    return asyncio.run(coro)


def _mock_resp(status_code: int, body: dict = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    return m


def _no_limiter():
    return patch.object(vt_svc._VT_LIMITER, "acquire", new=AsyncMock())


def _vt_body(malicious=0, suspicious=0, age_days=1, engines=None):
    scan_ts = int(time.time()) - (age_days * 86400)
    body = {
        "data": {
            "attributes": {
                "last_analysis_stats": {
                    "malicious": malicious,
                    "suspicious": suspicious,
                    "harmless": 70,
                    "undetected": 5,
                    "timeout": 0,
                },
                "last_analysis_date": scan_ts,
            }
        }
    }
    if engines:
        body["data"]["attributes"]["last_analysis_results"] = engines
    return body


def _make_result(
    normalized: str,
    *,
    position: int = 1,
    input_type=InputType.DOMAIN,
    freshness=Freshness.FRESH,
    vt_hits=0,
    vt_suspicious=0,
    held=False,
    age_days=365,
):
    hold = DomainHold(
        has_hold=held,
        hold_types=[DomainHoldType.CLIENT_HOLD] if held else [DomainHoldType.NONE],
        source=DomainStatusSource.RDAP if held else DomainStatusSource.NOT_CHECKED,
    )
    return MdiResultItem(
        input_original=normalized,
        input_normalized=normalized,
        input_type=input_type,
        position=position,
        processing_status=MdiProcessingStatus.HOLD_SKIPPED if held else MdiProcessingStatus.DONE,
        domain_hold=hold,
        vt_hits=vt_hits,
        vt_suspicious=vt_suspicious,
        vt_total_engines=75 if not held else 0,
        vt_ratio=f"{vt_hits}/75",
        freshness=freshness,
        age_bucket=AgeBucket.MATURE,
        triage_bucket=TriageBucket.CLEAN if vt_hits == 0 else TriageBucket.MALICIOUS,
        live_status=LiveStatus.NOT_CHECKED,
    )


def _make_job(
    items: list[MdiResultItem],
    *,
    use_domain_reports=False,
    stale_threshold_days=7,
    job_id="test-job-actions",
) -> InMemoryJob:
    job = InMemoryJob(
        job_id=job_id,
        status="done",
        submitted_at=time.time() - 100,
        completed_at=time.time() - 50,
        total=len(items),
        processed=len(items),
        use_domain_reports=use_domain_reports,
        stale_threshold_days=stale_threshold_days,
    )
    for item in items:
        job.results[item.input_normalized] = item
        job.item_order.append(item.input_normalized)
    return job


# ── 1–4: Refresh selected ─────────────────────────────────────────────────────

def test_refresh_selected_updates_vt_and_triage(tmp_path):
    item = _make_result("flagged.example.com", vt_hits=2, freshness=Freshness.STALE, age_days=10)
    job = _make_job([item])
    engines = {"Kaspersky": {"category": "malicious", "result": "phishing", "method": "blacklist"}}

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(2, engines=engines)))), \
         patch.object(live_check, "live_check_item", new=AsyncMock(return_value=LiveCheckResult(
             live_status=LiveStatus.ACTIVE, http_status_code=200, redirect_count=0))):
        stats = _run(job_actions._run_items(job, [item], "refresh",
                     usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json"))

    updated = job.results["flagged.example.com"]
    assert updated.vt_hits == 2
    assert updated.triage_bucket == TriageBucket.MALICIOUS
    assert updated.vt_engine_results is not None
    assert len(updated.vt_engine_results) >= 1
    assert stats.quota_units == 1


def test_refresh_clean_row_no_live_check(tmp_path):
    item = _make_result("clean.example.com", vt_hits=0)
    job = _make_job([item])
    lc_mock = AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.ACTIVE))

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))), \
         patch.object(live_check, "live_check_item", new=lc_mock):
        _run(job_actions._run_items(job, [item], "refresh", usage_file=tmp_path / "u.json"))

    lc_mock.assert_not_called()
    assert job.results["clean.example.com"].live_status == LiveStatus.NOT_CHECKED


def test_refresh_held_row_skipped_zero_vt_calls():
    held = _make_result("held.example.com", held=True, position=1)
    job = _make_job([held])
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])
    sel = job_actions.select_eligible_items(job, req.scope, req.positions, "refresh")
    assert len(sel.eligible) == 0
    assert sel.skipped_reasons.get("held") == 1

    vt_mock = AsyncMock()
    with patch("services.vt_service._vt_request", new=vt_mock):
        _run(job_actions._run_items(job, sel.eligible, "refresh"))
    vt_mock.assert_not_called()


# ── 6–10: Scan selected / stale / domain-report ───────────────────────────────

def test_scan_selected_url_success(tmp_path):
    item = _make_result(
        "https://scan-me.example.com/path",
        input_type=InputType.URL,
        freshness=Freshness.VERY_STALE,
        age_days=40,
    )
    job = _make_job([item])

    async def _vt_side_effect(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(200, {})
        return _mock_resp(200, _vt_body(malicious=1))

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_vt_side_effect)), \
         patch.object(live_check, "live_check_item", new=AsyncMock(return_value=LiveCheckResult(
             live_status=LiveStatus.ACTIVE, http_status_code=200))):
        _run(job_actions._run_items(job, [item], "scan", usage_file=tmp_path / "u.json"))

    updated = job.results["https://scan-me.example.com/path"]
    assert updated.vt_hits == 1
    assert job.vt_scan_requested_count == 1


def test_scan_stale_selects_only_stale_rows():
    fresh = _make_result("fresh.com", position=1, freshness=Freshness.FRESH)
    stale = _make_result("stale.com", position=2, freshness=Freshness.STALE, age_days=10)
    vstale = _make_result("vstale.com", position=3, freshness=Freshness.VERY_STALE, age_days=40)
    job = _make_job([fresh, stale, vstale])
    req = JobActionRequest(scope=RefreshScanScope.STALE)
    sel = job_actions.select_eligible_items(job, req.scope, None, "scan")
    positions = {r.position for r in sel.eligible}
    assert positions == {2, 3}


def test_scan_stale_excludes_held():
    stale_held = _make_result("held-stale.com", position=1, freshness=Freshness.STALE, held=True)
    stale_ok = _make_result("ok-stale.com", position=2, freshness=Freshness.STALE, age_days=10)
    job = _make_job([stale_held, stale_ok])
    sel = job_actions.select_eligible_items(job, RefreshScanScope.STALE, None, "scan")
    assert len(sel.eligible) == 1
    assert sel.eligible[0].position == 2


import services.vt_service as vt_service  # noqa: E402


def test_scan_domain_report_mode_eligible():
    item = _make_result("domain.com", freshness=Freshness.STALE, age_days=10)
    job = _make_job([item], use_domain_reports=True)
    sel = job_actions.select_eligible_items(
        job, RefreshScanScope.SELECTED, [1], "scan",
    )
    assert len(sel.eligible) == 1
    assert sel.eligible[0].input_normalized == "domain.com"


def test_scan_domain_report_mode_rescan_success(tmp_path):
    item = _make_result("himovies.to", freshness=Freshness.STALE, age_days=10, vt_hits=1)
    job = _make_job([item], use_domain_reports=True)
    analysis_polls = 0

    async def _vt_side_effect(method, url, **kwargs):
        nonlocal analysis_polls
        if method == "POST" and "/domains/" in url and url.endswith("/analyse"):
            return _mock_resp(200, {"data": {"id": "analysis-dom-1", "type": "analysis"}})
        if method == "GET" and "/analyses/" in url:
            analysis_polls += 1
            status = "completed" if analysis_polls >= 1 else "queued"
            return _mock_resp(200, {"data": {"attributes": {"status": status}}})
        if method == "GET" and "/domains/" in url:
            return _mock_resp(200, _vt_body(malicious=3, age_days=1))
        return _mock_resp(404)

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_vt_side_effect)):
        _run(job_actions._run_items(job, [item], "scan", usage_file=tmp_path / "u.json"))

    updated = job.results["himovies.to"]
    assert updated.vt_hits == 3
    assert job.vt_scan_requested_count == 1


def test_scan_domain_report_pending_preserves_prior(tmp_path):
    item = _make_result("pending-dom.com", freshness=Freshness.VERY_STALE, age_days=45, vt_hits=2)
    job = _make_job([item], use_domain_reports=True)

    async def _vt_side_effect(method, url, **kwargs):
        if method == "POST" and "/analyse" in url:
            return _mock_resp(200, {"data": {"id": "analysis-pending"}})
        if method == "GET" and "/analyses/" in url:
            return _mock_resp(200, {"data": {"attributes": {"status": "queued"}}})
        return _mock_resp(404)

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_vt_side_effect)):
        _run(job_actions._run_items(job, [item], "scan", usage_file=tmp_path / "u.json"))

    updated = job.results["pending-dom.com"]
    assert updated.vt_hits == 2
    assert any(e.code == "vt_scan_pending" for e in (updated.errors or []))


def test_scan_mixed_url_and_domain_report_selected():
    url_item = _make_result(
        "https://evil.example/path",
        position=1,
        input_type=InputType.URL,
        freshness=Freshness.STALE,
        age_days=10,
    )
    dom_item = _make_result("himovies.to", position=2, freshness=Freshness.STALE, age_days=10)
    job = _make_job([url_item, dom_item], use_domain_reports=True)
    sel = job_actions.select_eligible_items(
        job, RefreshScanScope.SELECTED, [1, 2], "scan",
    )
    assert len(sel.eligible) == 2
    est = job_actions.estimate_action(
        job, "scan", JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1, 2]),
    )
    assert est.url_scan_eligible_count == 1
    assert est.domain_rescan_eligible_count == 1
    assert est.estimated_quota_max == 9  # URL 4 + domain 5


def test_scan_stale_includes_domain_report_bare_domain():
    item = _make_result("stale-dom.com", freshness=Freshness.STALE, age_days=10)
    job = _make_job([item], use_domain_reports=True)
    sel = job_actions.select_eligible_items(job, RefreshScanScope.STALE, None, "scan")
    assert len(sel.eligible) == 1


def test_quota_blocked_before_scan():
    item = _make_result("a.com", freshness=Freshness.STALE, age_days=10)
    job = _make_job([item])
    req = JobActionRequest(scope=RefreshScanScope.STALE)
    with patch("services.job_actions.read_remaining_quota", return_value=0):
        est = job_actions.estimate_action(job, "scan", req)
    assert est.will_exceed_quota is True


def test_refresh_failure_preserves_prior_row(tmp_path):
    item = _make_result("fail.com", vt_hits=3, vt_suspicious=1, freshness=Freshness.STALE, age_days=10)
    job = _make_job([item])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(500))):
        _run(job_actions._run_items(job, [item], "refresh", usage_file=tmp_path / "u.json"))

    updated = job.results["fail.com"]
    assert updated.vt_hits == 3
    assert any(e.code == "vt_server_error" for e in (updated.errors or []))


def test_scan_pending_after_bounded_poll(tmp_path):
    item = _make_result("pending.com", freshness=Freshness.VERY_STALE, age_days=45)
    job = _make_job([item])

    async def _vt_side_effect(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(200, {})
        return _mock_resp(404)

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_vt_side_effect)):
        _run(job_actions._run_items(job, [item], "scan", usage_file=tmp_path / "u.json"))

    updated = job.results["pending.com"]
    assert any(e.code == "vt_scan_pending" for e in (updated.errors or []))
    assert job.vt_scan_failed_count >= 1


def test_saved_job_options_used_not_ui_defaults():
    item = _make_result("opts.com")
    job = _make_job([item], use_domain_reports=True, stale_threshold_days=14)
    captured = {}

    async def _capture_refresh(*args, **kwargs):
        captured.update(kwargs)
        return vt_svc.VtLookupResult(calls_made=0, error=vt_svc._vt_error("skip", "mock"))

    with patch("services.vt_service.refresh_report", new=AsyncMock(side_effect=_capture_refresh)):
        _run(job_actions._run_items(job, [item], "refresh"))

    assert captured["use_domain_reports"] is True
    assert captured["stale_threshold_days"] == 14


def test_recovered_job_refresh(tmp_path):
    item = _make_result("recovered.com", vt_hits=1, freshness=Freshness.STALE, age_days=10)
    job = _make_job([item], job_id="recover-job-1")
    job_file = tmp_path / "mdi_latest_job.json"
    _run(job_persistence.write_latest_job(job, job_file=job_file))

    job_store._JOBS.clear()
    with patch.dict(os.environ, {"MDI_LATEST_JOB_FILE": str(job_file)}):
        loaded = _run(job_actions.resolve_job("recover-job-1"))
    assert loaded is not None
    assert loaded.use_domain_reports == job.use_domain_reports


def test_persistence_after_refresh(tmp_path):
    item = _make_result("persist.com")
    job = _make_job([item])
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))), \
         patch.dict(os.environ, {"MDI_LATEST_JOB_FILE": str(job_file)}):
        _run(job_actions._run_items(job, [item], "refresh", job_file=job_file))

    assert job_file.exists()
    data = json.loads(job_file.read_text())
    assert data["job_id"] == job.job_id
    assert "persist.com" in data["results"]


def test_usage_history_aggregate_only_no_domains(tmp_path):
    item = _make_result("secret-leak.example.com", vt_hits=1, freshness=Freshness.STALE, age_days=10)
    job = _make_job([item])
    history = tmp_path / "history.jsonl"
    engines = {"EvilEngine": {"category": "malicious", "result": "bad"}}

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(1, engines=engines)))), \
         patch.object(live_check, "live_check_item", new=AsyncMock(return_value=LiveCheckResult(
             live_status=LiveStatus.NOT_FOUND, http_status_code=404))):
        sel = job_actions.EligibilityResult(eligible=[item])
        stats = _run(job_actions._run_items(job, [item], "refresh", usage_file=tmp_path / "u.json"))
        job_actions._append_action_history(
            job, "refresh", RefreshScanScope.SELECTED, sel, stats, history_file=history,
        )

    text = history.read_text()
    assert "secret-leak.example.com" not in text
    assert "EvilEngine" not in text
    assert '"operation": "refresh"' in text or '"operation": "refresh"' in text.replace(" ", "")
    rec = json.loads(text.strip().split("\n")[-1])
    assert rec["operation"] == "refresh"
    assert "refresh_count" in rec


def test_ip_input_cannot_reach_scan_action_path():
    from services.input_parser import parse_raw_input

    result = parse_raw_input("8.8.8.8")
    assert len(result.accepted) == 0
    assert result.rejected[0].error.code == "ip_address_not_supported"


def test_scan_submit_failure_structured_error(tmp_path):
    item = _make_result("submit-fail.com", freshness=Freshness.STALE, age_days=10)
    job = _make_job([item])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(400))):
        _run(job_actions._run_items(job, [item], "scan", usage_file=tmp_path / "u.json"))

    assert any(e.code == "vt_submit_error" for e in (job.results["submit-fail.com"].errors or []))
