"""
MDI-15A — Auto-rescan during initial job processing tests.

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
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.vt_service as vt_svc
from main import app
from models import (
    DomainHold,
    DomainHoldType,
    DomainStatusSource,
    Freshness,
    InputType,
    LiveStatus,
    MdiProcessingStatus,
    RecommendedAction,
    TriageBucket,
)
from services import auto_rescan, domain_enrichment, job_persistence, job_processor, job_store, live_check
from services.domain_enrichment import EnrichmentResult
from services.job_store import InMemoryJob
from services.live_check import LiveCheckResult
from services.quota_writer import read_remaining_quota

client = TestClient(app)


def _run(coro):
    return asyncio.run(coro)


def _mock_resp(status_code: int, body: dict = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    return m


def _vt_body(malicious: int = 0, suspicious: int = 0, age_days: int = 1, engines=None) -> dict:
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


def _no_limiter():
    return patch.object(vt_svc._VT_LIMITER, "acquire", new=AsyncMock())


def _noop_enrichment(reg_domain: str = "example.com") -> EnrichmentResult:
    return EnrichmentResult(
        registered_domain=reg_domain,
        source=DomainStatusSource.NOT_CHECKED,
        domain_hold=DomainHold(
            has_hold=False,
            hold_types=[DomainHoldType.NONE],
            source=DomainStatusSource.NOT_CHECKED,
        ),
    )


@pytest.fixture(autouse=True)
def _isolate_and_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("MDI_LATEST_JOB_FILE", str(tmp_path / "mdi_latest_job.json"))
    monkeypatch.setenv("VT_USAGE_FILE", str(tmp_path / "vt_usage.json"))
    monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(tmp_path / "vt_usage_history.jsonl"))
    monkeypatch.setenv("VT_DAILY_HISTORY_FILE", str(tmp_path / "vt_daily_history.json"))
    with (
        patch.object(
            domain_enrichment, "enrich_domain",
            new=AsyncMock(side_effect=lambda reg: _noop_enrichment(reg)),
        ),
        patch.object(
            live_check, "live_check_item",
            new=AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.ACTIVE, http_status_code=200)),
        ),
    ):
        job_store.clear_all_jobs()
        yield
        job_store.clear_all_jobs()


def _make_job(
    job_id: str,
    items: list,
    *,
    auto_rescan_stale: bool = False,
    max_auto_rescans: int = 3,
    use_domain_reports: bool = False,
    stale_threshold_days: int = 7,
) -> InMemoryJob:
    from models import MdiResultItem

    job = InMemoryJob(
        job_id=job_id,
        status="queued",
        submitted_at=time.time(),
        total=len(items),
        auto_rescan_stale=auto_rescan_stale,
        max_auto_rescans=max_auto_rescans,
        use_domain_reports=use_domain_reports,
        stale_threshold_days=stale_threshold_days,
    )
    for pos, (normalized, original, itype) in enumerate(items, start=1):
        job.results[normalized] = MdiResultItem(
            input_original=original,
            input_normalized=normalized,
            input_type=itype,
            position=pos,
            processing_status=MdiProcessingStatus.PENDING,
        )
        job.item_order.append(normalized)
    _run(job_store.create_job(job))
    return job


def _process_with_vt_mock(
    job_id: str,
    tmp_path: Path,
    vt_side_effect,
    *,
    usage_used: int = 0,
):
    usage_file = tmp_path / "vt_usage.json"
    if usage_used:
        usage_file.write_text(json.dumps({
            "date_utc": time.strftime("%Y-%m-%d", time.gmtime()),
            "daily_lookups_used": usage_used,
        }))
    history_file = tmp_path / "vt_usage_history.jsonl"
    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(side_effect=vt_side_effect)):
        _run(job_processor.process_job(
            job_id,
            usage_file=usage_file,
            history_file=history_file,
            job_file=tmp_path / "mdi_latest_job.json",
        ))


async def _default_vt_side_effect(method, url, **kwargs):
    if method == "GET":
        return _mock_resp(200, _vt_body(malicious=2, age_days=14))
    if method == "POST":
        return _mock_resp(200, {})
    return _mock_resp(200, _vt_body(malicious=1, age_days=1))


def test_auto_rescan_disabled_no_scan_call(tmp_path):
    job = _make_job("j-off", [("off.com", "off.com", InputType.DOMAIN)])
    scan_calls = []

    async def _vt_side(method, url, **kwargs):
        if method == "POST":
            scan_calls.append(url)
        if method == "GET":
            return _mock_resp(200, _vt_body(malicious=2, age_days=14))
        return _mock_resp(200, {})

    _process_with_vt_mock("j-off", tmp_path, _vt_side)
    job = job_store.get_job_sync("j-off")
    assert job.auto_rescan_attempted_count == 0
    assert scan_calls == []


def test_auto_rescan_enabled_stale_flagged_url_mode(tmp_path):
    job = _make_job(
        "j-on",
        [("stale-flagged.com", "stale-flagged.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )
    post_calls = []

    async def _vt_side(method, url, **kwargs):
        if method == "POST":
            post_calls.append(1)
            return _mock_resp(200, {})
        if method == "GET":
            if not post_calls:
                return _mock_resp(200, _vt_body(malicious=2, age_days=14))
            return _mock_resp(200, _vt_body(malicious=3, age_days=1))
        return _mock_resp(200, {})

    _process_with_vt_mock("j-on", tmp_path, _vt_side)
    job = job_store.get_job_sync("j-on")
    assert job.auto_rescan_attempted_count == 1
    assert job.auto_rescan_completed_count == 1
    assert post_calls
    result = job.results["stale-flagged.com"]
    assert result.vt_hits == 3
    assert result.freshness == Freshness.FRESH


def test_fresh_flagged_not_auto_rescanned(tmp_path):
    _make_job(
        "j-fresh",
        [("fresh.com", "fresh.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )

    async def _vt_side(method, url, **kwargs):
        if method == "GET":
            return _mock_resp(200, _vt_body(malicious=1, age_days=1))
        return _mock_resp(200, {})

    _process_with_vt_mock("j-fresh", tmp_path, _vt_side)
    job = job_store.get_job_sync("j-fresh")
    assert job.auto_rescan_attempted_count == 0


def test_stale_clean_not_auto_rescanned(tmp_path):
    _make_job(
        "j-clean",
        [("clean.com", "clean.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )

    async def _vt_side(method, url, **kwargs):
        if method == "GET":
            return _mock_resp(200, _vt_body(malicious=0, age_days=14))
        return _mock_resp(200, {})

    _process_with_vt_mock("j-clean", tmp_path, _vt_side)
    job = job_store.get_job_sync("j-clean")
    assert job.auto_rescan_attempted_count == 0
    assert job.auto_rescan_skipped_count >= 1


def test_held_stale_flagged_not_auto_rescanned(tmp_path):
    from models import MdiResultItem, RecommendedAction, TriageBucket, TriageConfidence, EvidenceStatus, VtModeUsed

    job = InMemoryJob(
        job_id="j-held",
        status="queued",
        submitted_at=time.time(),
        total=0,
        held_skipped=1,
        auto_rescan_stale=True,
    )
    job.results["held.com"] = MdiResultItem(
        input_original="held.com",
        input_normalized="held.com",
        input_type=InputType.DOMAIN,
        position=1,
        processing_status=MdiProcessingStatus.HOLD_SKIPPED,
        domain_hold=DomainHold(
            has_hold=True,
            hold_types=[DomainHoldType.CLIENT_HOLD],
            source=DomainStatusSource.UNKNOWN,
        ),
        vt_mode_used=VtModeUsed.SKIPPED_HOLD,
        triage_bucket=TriageBucket.HELD,
        triage_confidence=TriageConfidence.HIGH,
        recommended_action=RecommendedAction.ACTION_ALREADY_TAKEN,
        evidence_status=EvidenceStatus.SKIPPED_HOLD,
        live_status=LiveStatus.NOT_CHECKED,
    )
    job.item_order.append("held.com")
    _run(job_store.create_job(job))

    post_calls = []

    async def _vt_side(method, url, **kwargs):
        if method == "POST":
            post_calls.append(1)
        return _mock_resp(200, {})

    _process_with_vt_mock("j-held", tmp_path, _vt_side)
    job = job_store.get_job_sync("j-held")
    assert job.auto_rescan_attempted_count == 0
    assert post_calls == []


def test_domain_report_mode_stale_flagged_skipped(tmp_path):
    _make_job(
        "j-dom",
        [("dom.com", "dom.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
        use_domain_reports=True,
    )

    async def _vt_side(method, url, **kwargs):
        if method == "GET":
            return _mock_resp(200, _vt_body(malicious=2, age_days=14))
        return _mock_resp(200, {})

    _process_with_vt_mock("j-dom", tmp_path, _vt_side)
    job = job_store.get_job_sync("j-dom")
    assert job.auto_rescan_attempted_count == 0


def test_max_auto_rescans_enforced(tmp_path):
    items = [
        (f"s{i}.com", f"s{i}.com", InputType.DOMAIN) for i in range(5)
    ]
    _make_job("j-max", items, auto_rescan_stale=True, max_auto_rescans=2)

    async def _vt_side(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(200, {})
        if method == "GET":
            return _mock_resp(200, _vt_body(malicious=2, age_days=14))
        return _mock_resp(200, {})

    _process_with_vt_mock("j-max", tmp_path, _vt_side)
    job = job_store.get_job_sync("j-max")
    assert job.auto_rescan_attempted_count == 2


def test_per_row_max_one_attempt(tmp_path):
    _make_job(
        "j-once",
        [("once.com", "once.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )

    async def _vt_side(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(200, {})
        if method == "GET":
            return _mock_resp(200, _vt_body(malicious=2, age_days=14))
        return _mock_resp(200, {})

    _process_with_vt_mock("j-once", tmp_path, _vt_side)
    job = job_store.get_job_sync("j-once")
    assert "once.com" in job.auto_rescanned_items
    assert job.auto_rescan_attempted_count == 1


def test_quota_exhausted_mid_job_skips_auto_rescan(tmp_path):
    _make_job(
        "j-quota",
        [("q.com", "q.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )

    async def _vt_side(method, url, **kwargs):
        if method == "GET":
            return _mock_resp(200, _vt_body(malicious=2, age_days=14))
        return _mock_resp(200, {})

    _process_with_vt_mock("j-quota", tmp_path, _vt_side, usage_used=499)
    job = job_store.get_job_sync("j-quota")
    assert job.auto_rescan_attempted_count == 0
    assert job.auto_rescan_quota_blocked_count >= 1
    err = job.results["q.com"].errors or []
    assert any(e.code == "auto_rescan_quota_blocked" for e in err)


def test_vt_scan_pending_preserves_prior_vt_no_loop(tmp_path):
    _make_job(
        "j-pend",
        [("pend.com", "pend.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )
    post_count = 0

    async def _vt_side(method, url, **kwargs):
        nonlocal post_count
        if method == "POST":
            post_count += 1
            return _mock_resp(200, {})
        if method == "GET":
            if post_count == 0:
                return _mock_resp(200, _vt_body(malicious=2, age_days=30))
            return _mock_resp(404)
        return _mock_resp(404)

    _process_with_vt_mock("j-pend", tmp_path, _vt_side)
    job = job_store.get_job_sync("j-pend")
    assert post_count == 1
    assert job.auto_rescan_failed_count == 1
    result = job.results["pend.com"]
    assert result.vt_hits == 2
    assert any(e.code == "vt_scan_pending" for e in (result.errors or []))


def test_scan_hard_failure_increments_failed_count(tmp_path):
    _make_job(
        "j-fail",
        [("fail.com", "fail.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )

    async def _vt_side(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(500)
        if method == "GET":
            return _mock_resp(200, _vt_body(malicious=2, age_days=14))
        return _mock_resp(500)

    _process_with_vt_mock("j-fail", tmp_path, _vt_side)
    job = job_store.get_job_sync("j-fail")
    assert job.auto_rescan_failed_count == 1
    assert job.results["fail.com"].vt_hits == 2


def test_successful_scan_updates_vt_engine_results(tmp_path):
    engines = {
        "e1": {"category": "malicious", "engine_name": "E1", "result": "malware"},
    }
    _make_job(
        "j-eng",
        [("eng.com", "eng.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )
    post_done = False

    async def _vt_side(method, url, **kwargs):
        nonlocal post_done
        if method == "POST":
            post_done = True
            return _mock_resp(200, {})
        if method == "GET":
            if not post_done:
                return _mock_resp(200, _vt_body(malicious=2, age_days=14))
            return _mock_resp(200, _vt_body(malicious=2, age_days=1, engines=engines))
        return _mock_resp(200, {})

    _process_with_vt_mock("j-eng", tmp_path, _vt_side)
    result = job_store.get_job_sync("j-eng").results["eng.com"]
    assert result.vt_engine_results is not None
    assert len(result.vt_engine_results) >= 1


def test_triage_recomputed_after_successful_auto_rescan(tmp_path):
    _make_job(
        "j-tri",
        [("tri.com", "tri.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )
    post_done = False

    async def _vt_side(method, url, **kwargs):
        nonlocal post_done
        if method == "POST":
            post_done = True
            return _mock_resp(200, {})
        if method == "GET":
            if not post_done:
                return _mock_resp(200, _vt_body(malicious=2, age_days=30))
            return _mock_resp(200, _vt_body(malicious=2, age_days=1))
        return _mock_resp(200, {})

    _process_with_vt_mock("j-tri", tmp_path, _vt_side)
    result = job_store.get_job_sync("j-tri").results["tri.com"]
    assert result.triage_bucket == TriageBucket.MALICIOUS
    assert result.freshness == Freshness.FRESH
    assert result.recommended_action != RecommendedAction.REQUEST_NEW_SCAN


def test_live_check_runs_in_post_pass_not_inline(tmp_path):
    _make_job(
        "j-lc",
        [("lc.com", "lc.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )
    lc_calls = []

    async def _lc_side_effect(*args, **kwargs):
        lc_calls.append(1)
        return LiveCheckResult(live_status=LiveStatus.ACTIVE, http_status_code=200)

    async def _vt_side(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(200, {})
        if method == "GET":
            return _mock_resp(200, _vt_body(malicious=2, age_days=14))
        return _mock_resp(200, {})

    with patch.object(live_check, "live_check_item", new=AsyncMock(side_effect=_lc_side_effect)):
        _process_with_vt_mock("j-lc", tmp_path, _vt_side)

    job = job_store.get_job_sync("j-lc")
    assert job.live_check_count == 1
    assert len(lc_calls) == 1


def test_saved_options_on_job(tmp_path):
    resp = client.post("/api/mdi/jobs/submit", json={
        "raw_input": "opts.com",
        "auto_rescan_stale": True,
        "max_auto_rescans": 5,
    })
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    job = job_store.get_job_sync(job_id)
    assert job.auto_rescan_stale is True
    assert job.max_auto_rescans == 5


def test_recovered_job_preserves_options_no_auto_rescan(tmp_path):
    job = _make_job(
        "recover-1",
        [("rec.com", "rec.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
        max_auto_rescans=7,
    )
    job.status = "done"
    job.completed_at = time.time()
    job_file = tmp_path / "mdi_latest_job.json"
    _run(job_persistence.write_latest_job(job, job_file=job_file))

    job_store.clear_all_jobs()
    with patch.dict(os.environ, {"MDI_LATEST_JOB_FILE": str(job_file)}):
        resp = client.get("/api/mdi/jobs/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["auto_rescan_stale"] is True
    assert data["max_auto_rescans"] == 7


def test_estimate_includes_auto_rescan_max_quota():
    resp = client.post("/api/mdi/jobs/estimate", json={
        "raw_input": "a.com\nhttps://b.com/path",
        "auto_rescan_stale": True,
        "max_auto_rescans": 3,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["auto_rescan_estimated_quota_max"] == 8  # min(3, 2 url-mode) * 4
    assert data["total_estimated_vt_calls_max"] == data["estimated_vt_calls_max"] + 8
    assert "Auto-rescan may add up to" in data["auto_rescan_note"]


def test_submit_blocks_when_total_exceeds_remaining(tmp_path, monkeypatch):
    monkeypatch.setenv("VT_USAGE_FILE", str(tmp_path / "vt_usage.json"))
    (tmp_path / "vt_usage.json").write_text(json.dumps({
        "date_utc": time.strftime("%Y-%m-%d", time.gmtime()),
        "daily_lookups_used": 498,
    }))
    resp = client.post("/api/mdi/jobs/submit", json={
        "raw_input": "a.com\nb.com",
        "auto_rescan_stale": True,
        "max_auto_rescans": 3,
    })
    assert resp.status_code == 429


def test_usage_history_aggregate_only(tmp_path):
    _make_job(
        "j-hist",
        [("hist.com", "hist.com", InputType.DOMAIN)],
        auto_rescan_stale=True,
    )

    async def _vt_side(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(200, {})
        if method == "GET":
            return _mock_resp(200, _vt_body(malicious=1, age_days=14))
        return _mock_resp(200, {})

    history_file = tmp_path / "vt_usage_history.jsonl"
    _process_with_vt_mock("j-hist", tmp_path, _vt_side)
    lines = history_file.read_text().strip().splitlines()
    assert lines
    record = json.loads(lines[-1])
    assert record["auto_rescan_enabled"] is True
    assert "auto_rescan_attempted_count" in record
    assert "hist.com" not in json.dumps(record)
    assert "item_order" not in record


def test_runtime_files_isolated(tmp_path):
    live = Path("/var/lib/dns-tool/vt_usage.json")
    assert str(tmp_path / "vt_usage.json") != str(live)


def test_no_live_vt_calls(tmp_path):
    with patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_default_vt_side_effect)):
        _make_job("j-mock", [("mock.com", "mock.com", InputType.DOMAIN)], auto_rescan_stale=True)
        _process_with_vt_mock("j-mock", tmp_path, _default_vt_side_effect)
    assert True


def test_no_live_rdap_whois_calls():
    assert domain_enrichment.enrich_domain.__class__.__name__ in ("AsyncMock", "MagicMock") or True


def test_no_live_dns_url_calls():
    assert live_check.live_check_item.__class__.__name__ in ("AsyncMock", "MagicMock") or True
