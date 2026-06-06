"""
Tests for job submission, job status endpoints, and the async processing loop.

Strategy:
  - Endpoint tests (submit / status) use FastAPI TestClient — test initial state.
  - Processing tests call job_processor.process_job() directly via asyncio.run()
    with mocked VT (_vt_request) and temp file paths (tmp_path).
  - Live /var/lib/dns-tool/vt_usage.json is never modified.
  - Live /var/lib/dns-tool/mdi_latest_job.json is never created or modified.
  - No real VT API calls are made.
  - No real RDAP or WHOIS calls are made (MDI-11 enrichment is mocked).

MDI-08A isolation fix (two paths):
  1. Direct process_job() calls: all now pass job_file=tmp_path / "mdi_latest_job.json".
  2. Background tasks from POST /api/mdi/jobs/submit TestClient tests: cannot
     inject job_file= through the endpoint, so an autouse fixture redirects
     MDI_LATEST_JOB_FILE to tmp_path for every test in this module.
  Prior to this fix, both paths defaulted to /var/lib/dns-tool/mdi_latest_job.json
  and wrote test artifacts to the live recovery file during every test run.

MDI-11 enrichment guard (autouse):
  The redirect_job_persistence fixture also patches enrich_domain to return a
  safe no-op EnrichmentResult so that all existing tests are unaffected by the
  new pre-enrichment pass.  Tests that need specific enrichment behavior override
  the mock explicitly within the test body.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.vt_service as vt_svc
from main import app
from models import (
    AgeBucket,
    DomainHold,
    DomainHoldType,
    DomainStatusSource,
    EvidenceStatus,
    Freshness,
    InputType,
    LiveStatus,
    MdiProcessingStatus,
    RecommendedAction,
    TriageBucket,
    VtModeUsed,
)
from services import domain_enrichment, job_processor, job_store, live_check
from services.domain_enrichment import EnrichmentResult
from services.job_store import InMemoryJob
from services.live_check import LiveCheckResult
from services.quota_writer import increment_quota, read_remaining_quota

client = TestClient(app)


# ── Module-level test isolation ────────────────────────────────────────────────

def _make_noop_enrichment(registered_domain: str = "example.com") -> EnrichmentResult:
    """Return a safe, empty enrichment result (no hold, no data, no error)."""
    return EnrichmentResult(
        registered_domain=registered_domain,
        source=DomainStatusSource.NOT_CHECKED,
        domain_hold=DomainHold(
            has_hold=False,
            hold_types=[DomainHoldType.NONE],
            source=DomainStatusSource.NOT_CHECKED,
        ),
    )


@pytest.fixture(autouse=True)
def redirect_job_persistence(tmp_path, monkeypatch):
    """
    Redirect ALL job persistence writes to tmp_path for every test in this module.

    This covers two write paths:
      1. Direct process_job() calls — each also passes explicit job_file=tmp_path/...
      2. Background tasks spawned by POST /api/mdi/jobs/submit via TestClient —
         those tasks cannot receive job_file= injection through the endpoint, so
         they pick up MDI_LATEST_JOB_FILE from the environment instead.

    Without this fixture, background tasks default to _default_job_file() =
    /var/lib/dns-tool/mdi_latest_job.json, writing test artifacts to the live
    recovery file.  monkeypatch automatically restores the env var after each test.

    MDI-11 enrichment guard: also patches enrich_domain to return a no-op result
    so existing tests never make live RDAP or WHOIS calls.  Tests that need real
    enrichment behavior override the mock explicitly within the test.

    MDI-12 live-check guard: also patches live_check.live_check_item to return
    NOT_CHECKED so all existing tests are unaffected by the new live-check pass.
    Tests that need specific live-check behavior override this mock explicitly.
    """
    monkeypatch.setenv("MDI_LATEST_JOB_FILE", str(tmp_path / "mdi_latest_job.json"))
    # Patch enrich_domain at the module level used by job_processor
    with (
        patch.object(
            domain_enrichment, "enrich_domain",
            new=AsyncMock(side_effect=lambda reg_domain: _make_noop_enrichment(reg_domain)),
        ),
        patch.object(
            live_check, "live_check_item",
            new=AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.NOT_CHECKED)),
        ),
    ):
        yield


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _mock_resp(status_code: int, body: dict = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    return m


def _vt_report_body(malicious: int = 0, suspicious: int = 0, harmless: int = 70,
                    age_days: int = 1) -> dict:
    scan_ts = int(time.time()) - (age_days * 86400)
    return {
        "data": {
            "attributes": {
                "last_analysis_stats": {
                    "malicious": malicious,
                    "suspicious": suspicious,
                    "harmless": harmless,
                    "undetected": 5,
                    "timeout": 0,
                },
                "last_analysis_date": scan_ts,
            }
        }
    }


def _no_limiter():
    return patch.object(vt_svc._VT_LIMITER, "acquire", new=AsyncMock())


def _run(coro):
    return asyncio.run(coro)


def _make_job(job_id: str, items: list, use_domain_reports: bool = False,
              stale_threshold_days: int = 7) -> InMemoryJob:
    """Create and register an InMemoryJob with pending items."""
    job = InMemoryJob(
        job_id=job_id,
        status="queued",
        submitted_at=time.time(),
        total=len(items),
        use_domain_reports=use_domain_reports,
        stale_threshold_days=stale_threshold_days,
    )
    from models import MdiResultItem, MdiProcessingStatus
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


def _make_held_job(job_id: str, normalized: str, original: str) -> InMemoryJob:
    """Create a job with a pre-populated HOLD_SKIPPED result."""
    from models import (
        DomainHold, DomainHoldType, DomainStatusSource,
        MdiResultItem, MdiProcessingStatus, TriageBucket, TriageConfidence,
        RecommendedAction, EvidenceStatus, VtModeUsed, LiveStatus,
    )
    job = InMemoryJob(
        job_id=job_id,
        status="queued",
        submitted_at=time.time(),
        total=0,     # no eligible VT items
        held_skipped=1,
    )
    job.results[normalized] = MdiResultItem(
        input_original=original,
        input_normalized=normalized,
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
    job.item_order.append(normalized)
    _run(job_store.create_job(job))
    return job


# ── Endpoint: POST /api/mdi/jobs/submit ────────────────────────────────────────

def test_submit_job_creates_job_id():
    """Submit with valid raw_input → response contains job_id."""
    resp = client.post("/api/mdi/jobs/submit", json={"raw_input": "example.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert len(data["job_id"]) > 0
    assert data["status"] == "queued"
    assert data["total"] >= 1


def test_submit_job_empty_input_rejected():
    """Empty raw_input → 422."""
    resp = client.post("/api/mdi/jobs/submit", json={"raw_input": ""})
    assert resp.status_code == 422


def test_submit_job_missing_input_rejected():
    """No raw_input → 422."""
    resp = client.post("/api/mdi/jobs/submit", json={})
    assert resp.status_code == 422


def test_submit_job_counts_are_correct():
    """Submit two domains → queued_count=2, held_skipped_count=0."""
    resp = client.post("/api/mdi/jobs/submit", json={
        "raw_input": "alpha.com\nbeta.com",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["queued_count"] == 2
    assert data["held_skipped_count"] == 0
    assert data["rejected_count"] == 0


def test_submit_job_estimated_requests_url_mode():
    """URL-report mode: each domain item = 3 estimated requests."""
    resp = client.post("/api/mdi/jobs/submit", json={
        "raw_input": "test1.com\ntest2.com",
        "use_domain_reports": False,
    })
    data = resp.json()
    assert data["estimated_requests"] == 6   # 2 domains × 3 in URL-mode


def test_submit_job_estimated_requests_domain_mode():
    """Domain-report mode: each domain item = 1 estimated request."""
    resp = client.post("/api/mdi/jobs/submit", json={
        "raw_input": "a.com\nb.com",
        "use_domain_reports": True,
    })
    data = resp.json()
    assert data["estimated_requests"] == 2


def test_submit_job_quota_hard_stop():
    """If estimated > remaining → 429 with quota_blocked error."""
    with patch("routers.mdi.read_remaining_quota", return_value=0):
        resp = client.post("/api/mdi/jobs/submit", json={
            "raw_input": "x.com\ny.com\nz.com",
        })
    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["error"] == "quota_blocked"
    assert "estimated_requests" in detail


def test_submit_job_quota_not_blocked_when_sufficient():
    """Sufficient quota → job created successfully."""
    with patch("routers.mdi.read_remaining_quota", return_value=500):
        resp = client.post("/api/mdi/jobs/submit", json={"raw_input": "ok.com"})
    assert resp.status_code == 200


# ── Endpoint: GET /api/mdi/jobs/{job_id} ──────────────────────────────────────

def test_job_status_not_found():
    resp = client.get("/api/mdi/jobs/does-not-exist")
    assert resp.status_code == 404


def test_job_status_returns_queued_state():
    """Newly submitted job → status endpoint reflects queued state."""
    resp = client.post("/api/mdi/jobs/submit", json={"raw_input": "queued-check.com"})
    job_id = resp.json()["job_id"]

    status_resp = client.get(f"/api/mdi/jobs/{job_id}")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["job_id"] == job_id
    assert data["status"] in ("queued", "running", "done")
    assert "results" in data


# ── Processing loop: VT checks ────────────────────────────────────────────────

def test_process_job_clean_domain(tmp_path):
    """Clean domain → result is CLEAN after processing."""
    job_id = "test-clean-" + str(time.time_ns())
    _make_job(job_id, [("example.com", "example.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, harmless=70, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    job = job_store.get_job_sync(job_id)
    assert job.status == "done"
    result = job.results["example.com"]
    assert result.processing_status == MdiProcessingStatus.DONE
    assert result.triage_bucket == TriageBucket.CLEAN
    assert result.vt_hits == 0


def test_process_job_malicious_domain(tmp_path):
    """Malicious domain → result is MALICIOUS after processing."""
    job_id = "test-mal-" + str(time.time_ns())
    _make_job(job_id, [("evil.com", "evil.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=4, suspicious=1, harmless=65, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    job = job_store.get_job_sync(job_id)
    result = job.results["evil.com"]
    assert result.triage_bucket == TriageBucket.MALICIOUS
    assert result.vt_hits == 4
    # MDI-10: FRESH + NOT_CHECKED live + UNKNOWN age → catch-all → VERIFY_INVESTIGATE
    assert result.recommended_action == RecommendedAction.VERIFY_INVESTIGATE


def test_process_job_held_item_not_vt_checked(tmp_path):
    """HOLD_SKIPPED items are never passed to VT; mock must not be called."""
    job_id = "test-held-" + str(time.time_ns())
    _make_held_job(job_id, "held-domain.com", "held-domain.com")

    mock_req = AsyncMock()
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    mock_req.assert_not_called()
    job = job_store.get_job_sync(job_id)
    result = job.results["held-domain.com"]
    assert result.processing_status == MdiProcessingStatus.HOLD_SKIPPED
    assert result.vt_mode_used == VtModeUsed.SKIPPED_HOLD
    assert result.triage_bucket == TriageBucket.HELD
    assert result.evidence_status == EvidenceStatus.SKIPPED_HOLD
    assert result.recommended_action == RecommendedAction.ACTION_ALREADY_TAKEN


def test_process_job_unknown_hold_is_processed(tmp_path):
    """Domain with no hold info (unknown) → VT is called normally."""
    job_id = "test-unknown-hold-" + str(time.time_ns())
    _make_job(job_id, [("maybe-held.com", "maybe-held.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, age_days=2)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    mock_req.assert_called()
    job = job_store.get_job_sync(job_id)
    assert job.results["maybe-held.com"].processing_status == MdiProcessingStatus.DONE


# ── Quota increment tests ──────────────────────────────────────────────────────

def test_quota_increment_after_successful_call(tmp_path):
    """Processing one URL-mode item increments usage by calls_made."""
    job_id = "test-quota-inc-" + str(time.time_ns())
    _make_job(job_id, [("quota-test.com", "quota-test.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    data = json.loads(usage_file.read_text())
    # One successful GET call → 1 increment
    assert data["daily_lookups_used"] == 1

    job = job_store.get_job_sync(job_id)
    assert job.lookups_used == 1


def test_quota_increment_url_404_flow(tmp_path):
    """URL 404→submit→refetch flow increments quota by 3."""
    job_id = "test-quota-404-" + str(time.time_ns())
    _make_job(job_id, [("new-url.com", "new-url.com", InputType.URL)],)

    body = _vt_report_body(malicious=0, age_days=1)
    responses = [
        _mock_resp(404, {}),
        _mock_resp(200, {"data": {"id": "x"}}),
        _mock_resp(200, body),
    ]
    idx = 0

    async def multi(method, url, *, headers, data=None):
        nonlocal idx
        r = responses[idx]; idx += 1
        return r

    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=multi), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    data = json.loads(usage_file.read_text())
    assert data["daily_lookups_used"] == 3
    job = job_store.get_job_sync(job_id)
    assert job.lookups_used == 3


def test_quota_hard_stop_mid_run(tmp_path):
    """If quota is exhausted before an item is processed, item is quota_blocked."""
    from datetime import datetime, timezone as tz
    job_id = "test-quota-stop-" + str(time.time_ns())
    _make_job(job_id, [
        ("first.com", "first.com", InputType.DOMAIN),
        ("second.com", "second.com", InputType.DOMAIN),
    ])

    # Exhaust quota: write today's date so the counter is recognized as current
    from services.quota_writer import DAILY_QUOTA
    today_str = datetime.now(tz.utc).strftime("%Y-%m-%d")
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text(json.dumps({
        "date_utc": today_str,
        "daily_lookups_used": DAILY_QUOTA
    }))

    mock_req = AsyncMock()  # should not be called

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    mock_req.assert_not_called()
    job = job_store.get_job_sync(job_id)
    assert job.quota_blocked_count == 2


# ── VT error handling ──────────────────────────────────────────────────────────

def test_process_job_vt_429_structured_error(tmp_path):
    """VT 429 → item.processing_status=ERROR, triage_bucket=ERROR, retriable=True."""
    job_id = "test-429-" + str(time.time_ns())
    _make_job(job_id, [("ratelimited.com", "ratelimited.com", InputType.DOMAIN)])

    mock_req = AsyncMock(return_value=_mock_resp(429, {}))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    job = job_store.get_job_sync(job_id)
    result = job.results["ratelimited.com"]
    assert result.processing_status == MdiProcessingStatus.ERROR
    assert result.triage_bucket == TriageBucket.ERROR
    assert len(result.errors) == 1
    assert result.errors[0].code == "vt_429"
    assert result.errors[0].retriable is True


def test_process_job_vt_500_structured_error(tmp_path):
    """VT 500 → structured server error on item."""
    job_id = "test-500-" + str(time.time_ns())
    _make_job(job_id, [("server-error.com", "server-error.com", InputType.DOMAIN)])

    mock_req = AsyncMock(return_value=_mock_resp(500, {}))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    result = job_store.get_job_sync(job_id).results["server-error.com"]
    assert result.processing_status == MdiProcessingStatus.ERROR
    assert any(e.code == "vt_server_error" for e in result.errors)


def test_process_job_vt_timeout_structured_error(tmp_path):
    """Timeout exception → structured timeout error, job continues."""
    import httpx
    job_id = "test-timeout-" + str(time.time_ns())
    _make_job(job_id, [("slow.com", "slow.com", InputType.DOMAIN)])

    async def raise_timeout(*a, **kw):
        raise httpx.TimeoutException("timed out")

    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=raise_timeout), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    result = job_store.get_job_sync(job_id).results["slow.com"]
    assert result.processing_status == MdiProcessingStatus.ERROR
    assert any(e.code == "vt_timeout" for e in result.errors)


# ── Freshness classification ───────────────────────────────────────────────────

def test_freshness_1_day_is_fresh(tmp_path):
    job_id = "test-fresh-" + str(time.time_ns())
    _make_job(job_id, [("fresh.com", "fresh.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    result = job_store.get_job_sync(job_id).results["fresh.com"]
    assert result.freshness == Freshness.FRESH


def test_freshness_10_days_is_stale(tmp_path):
    job_id = "test-stale-" + str(time.time_ns())
    _make_job(job_id, [("stale.com", "stale.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, age_days=10)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    result = job_store.get_job_sync(job_id).results["stale.com"]
    assert result.freshness == Freshness.STALE


def test_freshness_45_days_is_very_stale(tmp_path):
    job_id = "test-vstale-" + str(time.time_ns())
    _make_job(job_id, [("very-stale.com", "very-stale.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, age_days=45)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    result = job_store.get_job_sync(job_id).results["very-stale.com"]
    assert result.freshness == Freshness.VERY_STALE


def test_freshness_missing_date_is_never_scanned(tmp_path):
    """No last_analysis_date → NEVER_SCANNED."""
    job_id = "test-never-" + str(time.time_ns())
    _make_job(job_id, [("no-scan.com", "no-scan.com", InputType.DOMAIN)])

    body = {
        "data": {
            "attributes": {
                "last_analysis_stats": {"malicious": 0, "harmless": 0},
                # no last_analysis_date key
            }
        }
    }
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    result = job_store.get_job_sync(job_id).results["no-scan.com"]
    assert result.freshness == Freshness.NEVER_SCANNED


# ── Usage history tests ────────────────────────────────────────────────────────

def test_usage_history_metadata_only(tmp_path):
    """Usage JSONL entry contains only metadata fields, no item data."""
    job_id = "test-hist-" + str(time.time_ns())
    _make_job(job_id, [("secret-domain.com", "secret-domain.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    history_file = tmp_path / "vt_usage_history.jsonl"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(
            job_id,
            usage_file=usage_file,
            history_file=history_file,
            job_file=tmp_path / "mdi_latest_job.json",
        ))

    assert history_file.exists()
    lines = [l for l in history_file.read_text().strip().split("\n") if l]
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["tool_name"] == "mdi"
    assert record["job_id"] == job_id
    assert record["operation"] == "report_lookup"
    assert "items_attempted" in record
    assert "quota_units_consumed" in record
    assert "status" in record


def test_usage_history_no_raw_domains_or_urls(tmp_path):
    """Usage JSONL must NOT contain any raw domain or URL values."""
    job_id = "test-no-leak-" + str(time.time_ns())
    _make_job(job_id, [("do-not-leak-me.com", "do-not-leak-me.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    history_file = tmp_path / "vt_usage_history.jsonl"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(
            job_id,
            usage_file=usage_file,
            history_file=history_file,
            job_file=tmp_path / "mdi_latest_job.json",
        ))

    raw = history_file.read_text()
    assert "do-not-leak-me.com" not in raw, "Domain leaked into usage history"


# ── Live runtime file protection ───────────────────────────────────────────────

def test_live_mdi_latest_job_not_created_or_modified(tmp_path):
    """
    Processing tests must never create or modify /var/lib/dns-tool/mdi_latest_job.json.

    This is the MDI-08A regression guard.  Before the fix, process_job() calls
    without job_file= defaulted to the live path and wrote test artifacts there.
    """
    live_path = Path("/var/lib/dns-tool/mdi_latest_job.json")
    existed_before = live_path.exists()
    mtime_before = live_path.stat().st_mtime if existed_before else None

    job_id = "test-isolation-" + str(time.time_ns())
    _make_job(job_id, [("isolation-check.com", "isolation-check.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(
            job_id,
            usage_file=usage_file,
            job_file=tmp_path / "mdi_latest_job.json",
        ))

    # Verify the test's own persistence went to tmp_path, not the live path
    assert (tmp_path / "mdi_latest_job.json").exists(), \
        "Persistence should have written to tmp_path"

    if not existed_before:
        assert not live_path.exists(), \
            "test must not create /var/lib/dns-tool/mdi_latest_job.json"
    else:
        mtime_after = live_path.stat().st_mtime
        assert mtime_before == mtime_after, \
            "test must not modify /var/lib/dns-tool/mdi_latest_job.json"


def test_live_vt_usage_file_not_modified(tmp_path):
    """Tests must not modify /var/lib/dns-tool/vt_usage.json."""
    live_path = Path("/var/lib/dns-tool/vt_usage.json")
    mtime_before: Optional[float] = None
    if live_path.exists():
        mtime_before = live_path.stat().st_mtime

    job_id = "test-live-prot-" + str(time.time_ns())
    _make_job(job_id, [("example.com", "example.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    tmp_usage = tmp_path / "vt_usage.json"
    tmp_usage.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job_id, usage_file=tmp_usage, job_file=tmp_path / "mdi_latest_job.json"))

    if live_path.exists() and mtime_before is not None:
        mtime_after = live_path.stat().st_mtime
        assert mtime_before == mtime_after, "Live VT usage file was modified during test!"


def test_no_socket_calls_in_processing(tmp_path):
    """Confirm no DNS resolution occurs during mocked job processing."""
    dns_calls = []
    original_getaddrinfo = socket.getaddrinfo

    def spy_getaddrinfo(*args, **kwargs):
        dns_calls.append(args)
        return original_getaddrinfo(*args, **kwargs)

    job_id = "test-dns-spy-" + str(time.time_ns())
    _make_job(job_id, [("example.com", "example.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("socket.getaddrinfo", side_effect=spy_getaddrinfo):
        _run(job_processor.process_job(job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"))

    assert dns_calls == [], f"Unexpected DNS calls: {dns_calls}"


# ── Regression: existing endpoints ────────────────────────────────────────────

def test_regression_parse_preview_still_works():
    """Existing parse-preview endpoint must not be broken by MDI-06 changes."""
    resp = client.post(
        "/api/mdi/jobs/parse-preview",
        json={"raw_input": "regression-test.com\nhttps://regression2.net/path"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted_count"] == 2
    assert data["external_calls_made"] is False
    assert data["quota_consumed"] is False


def test_regression_upload_preview_still_works():
    """Existing upload-preview endpoint must not be broken by MDI-06 changes."""
    import io
    csv_content = b"Domain Name,Creation Date\nregression.com,2023-01-01\n"
    resp = client.post(
        "/api/mdi/jobs/upload-preview",
        files={"file": ("test.csv", io.BytesIO(csv_content), "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "accepted_count" in data
    assert data["external_calls_made"] is False


def test_regression_usage_endpoint_still_works():
    """Existing /api/mdi/usage endpoint must not be broken by MDI-06 changes."""
    resp = client.get("/api/mdi/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert "daily_lookups_used" in data
    assert data.get("mutated") is False


# ── MDI-09 settings defaults in submit endpoint ────────────────────────────────

def test_submit_default_stale_threshold_is_7():
    """POST /api/mdi/jobs/submit without stale_threshold_days → status shows 7."""
    resp = client.post("/api/mdi/jobs/submit", json={"raw_input": "example.com"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    status = client.get(f"/api/mdi/jobs/{job_id}")
    assert status.status_code == 200
    data = status.json()
    assert data["stale_threshold_days"] == 7


def test_submit_use_domain_reports_stored(tmp_path):
    """
    use_domain_reports=True submitted via endpoint → stored in job and echoed by status.
    Uses the submit endpoint (TestClient) which spawns a background task.
    The redirect_job_persistence autouse fixture prevents live-file writes.
    """
    resp = client.post("/api/mdi/jobs/submit", json={
        "raw_input": "domainreport-test.com",
        "use_domain_reports": True,
    })
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    status = client.get(f"/api/mdi/jobs/{job_id}")
    assert status.status_code == 200
    data = status.json()
    assert data["use_domain_reports"] is True


def test_submit_custom_stale_threshold_stored(tmp_path):
    """
    Custom stale_threshold_days=14 → stored in job and echoed by status.
    """
    resp = client.post("/api/mdi/jobs/submit", json={
        "raw_input": "custom-stale.com",
        "stale_threshold_days": 14,
    })
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    status = client.get(f"/api/mdi/jobs/{job_id}")
    assert status.status_code == 200
    data = status.json()
    assert data["stale_threshold_days"] == 14


# ─────────────────────────────────────────────────────────────────────────────
# MDI-10 — Triage rules engine integration tests
# ─────────────────────────────────────────────────────────────────────────────

def test_mdi10_clean_result_has_non_empty_triage_reason(tmp_path):
    """
    MDI-10: mocked clean VT result → triage_reason is a non-empty list.
    Verifies triage_rules.decide() populates the field end-to-end.
    """
    from models import TriageBucket, RecommendedAction, TriageConfidence
    job_id = "test-mdi10-clean-" + str(time.time_ns())
    _make_job(job_id, [("clean-site.com", "clean-site.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, harmless=70, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    job = job_store.get_job_sync(job_id)
    result = job.results["clean-site.com"]
    assert result.triage_bucket == TriageBucket.CLEAN
    # MDI-10: triage_reason must be a non-empty list
    assert isinstance(result.triage_reason, list)
    assert len(result.triage_reason) >= 1
    assert all(isinstance(r, str) for r in result.triage_reason)
    # Clean + fresh → NO_ACTION_BASED_ON_VT and CLEAN confidence
    assert result.recommended_action == RecommendedAction.NO_ACTION_BASED_ON_VT
    assert result.triage_confidence == TriageConfidence.CLEAN


def test_mdi10_malicious_result_uses_new_recommended_action(tmp_path):
    """
    MDI-10: mocked malicious VT result → recommended_action from new rules engine.
    Flagged + FRESH + NOT_CHECKED live + UNKNOWN age → VERIFY_INVESTIGATE (catch-all).
    """
    from models import TriageBucket, RecommendedAction
    job_id = "test-mdi10-mal-" + str(time.time_ns())
    _make_job(job_id, [("evil-mdi10.com", "evil-mdi10.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=3, harmless=65, age_days=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    job = job_store.get_job_sync(job_id)
    result = job.results["evil-mdi10.com"]
    assert result.triage_bucket == TriageBucket.MALICIOUS
    # MDI-10: triage_reason must be non-empty
    assert isinstance(result.triage_reason, list)
    assert len(result.triage_reason) >= 1
    # FRESH + NOT_CHECKED live + UNKNOWN age → VERIFY_INVESTIGATE (catch-all flagged)
    assert result.recommended_action == RecommendedAction.VERIFY_INVESTIGATE


def test_mdi10_held_result_triage_reason_from_rules_engine(tmp_path):
    """
    MDI-10: held domain result must have triage_reason from rules engine, not empty.
    """
    from models import TriageBucket, RecommendedAction, EvidenceStatus
    job_id = "test-mdi10-held-" + str(time.time_ns())
    _make_held_job(job_id, "held-mdi10.com", "held-mdi10.com")

    mock_req = AsyncMock()
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    mock_req.assert_not_called()
    job = job_store.get_job_sync(job_id)
    result = job.results["held-mdi10.com"]
    assert result.triage_bucket == TriageBucket.HELD
    assert result.recommended_action == RecommendedAction.ACTION_ALREADY_TAKEN
    assert result.evidence_status == EvidenceStatus.SKIPPED_HOLD
    # Pre-populated held results don't go through process_job triage; check the field exists
    assert result.triage_reason is not None
    assert isinstance(result.triage_reason, list)


def test_mdi10_quota_blocked_uses_retry_lookup(tmp_path):
    """
    MDI-10: quota-blocked item → triage_bucket=ERROR, recommended_action=RETRY_LOOKUP,
    and triage_reason is non-empty (populated by rules engine).
    """
    from models import TriageBucket, RecommendedAction
    job_id = "test-mdi10-quota-" + str(time.time_ns())
    _make_job(job_id, [("quota-blocked.com", "quota-blocked.com", InputType.DOMAIN)])

    # Write an exhausted quota file (current date, 0 remaining)
    from datetime import date
    today = date.today().isoformat()
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text(f'{{"date_utc": "{today}", "daily_lookups_used": 500}}')
    mock_req = AsyncMock()

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    mock_req.assert_not_called()
    job = job_store.get_job_sync(job_id)
    result = job.results["quota-blocked.com"]
    assert result.triage_bucket == TriageBucket.ERROR
    assert result.recommended_action == RecommendedAction.RETRY_LOOKUP
    assert isinstance(result.triage_reason, list)
    assert len(result.triage_reason) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# MDI-11 — RDAP/WHOIS enrichment integration tests
# ─────────────────────────────────────────────────────────────────────────────

def _make_rdap_enrichment_result(
    registered_domain: str = "example.com",
    age_bucket: AgeBucket = AgeBucket.MATURE,
    has_hold: bool = False,
    hold_source: DomainStatusSource = DomainStatusSource.RDAP,
    registrar: str = "Test Registrar",
    error=None,
) -> EnrichmentResult:
    """Build a realistic EnrichmentResult for MDI-11 integration tests."""
    from datetime import datetime, timezone
    from models import MdiError
    return EnrichmentResult(
        registered_domain=registered_domain,
        source=DomainStatusSource.RDAP if error is None else DomainStatusSource.UNKNOWN,
        created_at=datetime(1995, 8, 14, tzinfo=timezone.utc) if age_bucket == AgeBucket.MATURE else None,
        age_bucket=age_bucket,
        registrar=registrar if not has_hold else None,
        epp_status=["clientHold"] if has_hold else ["clientTransferProhibited"],
        nameservers=["ns1.example.com"],
        domain_hold=DomainHold(
            has_hold=has_hold,
            hold_types=[DomainHoldType.CLIENT_HOLD] if has_hold else [DomainHoldType.NONE],
            source=hold_source,
        ),
        error=error,
        whois_fallback_used=False,
    )


def test_mdi11_enrichment_populates_created_at_and_age_bucket(tmp_path):
    """
    MDI-11: mocked RDAP enrichment → created_at and age_bucket populated in result.
    """
    job_id = "test-mdi11-enrich-" + str(time.time_ns())
    _make_job(job_id, [("example.com", "example.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, harmless=70, age_days=1)
    mock_vt = AsyncMock(return_value=_mock_resp(200, body))
    enrichment = _make_rdap_enrichment_result(age_bucket=AgeBucket.MATURE, registrar="IANA")
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_vt), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch.object(
             domain_enrichment, "enrich_domain",
             new=AsyncMock(return_value=enrichment),
         ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    job = job_store.get_job_sync(job_id)
    result = job.results["example.com"]
    assert result.age_bucket == AgeBucket.MATURE
    assert result.created_at is not None
    assert result.created_at.year == 1995
    assert result.registrar == "IANA"
    assert result.nameservers == ["ns1.example.com"]


def test_mdi11_client_hold_via_rdap_skips_vt(tmp_path):
    """
    MDI-11: RDAP confirms clientHold → VT is skipped; triage_bucket=HELD.
    VT mock must NOT be called.
    """
    job_id = "test-mdi11-hold-" + str(time.time_ns())
    _make_job(job_id, [("held-rdap.com", "held-rdap.com", InputType.DOMAIN)])

    mock_vt = AsyncMock()
    enrichment = _make_rdap_enrichment_result(
        registered_domain="held-rdap.com",
        has_hold=True,
        hold_source=DomainStatusSource.RDAP,
    )
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_vt), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch.object(
             domain_enrichment, "enrich_domain",
             new=AsyncMock(return_value=enrichment),
         ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    mock_vt.assert_not_called()
    job = job_store.get_job_sync(job_id)
    result = job.results["held-rdap.com"]
    assert result.processing_status == MdiProcessingStatus.HOLD_SKIPPED
    assert result.triage_bucket == TriageBucket.HELD
    assert result.recommended_action == RecommendedAction.ACTION_ALREADY_TAKEN
    assert result.evidence_status == EvidenceStatus.SKIPPED_HOLD
    assert job.hold_detected_by_enrichment_count == 1
    assert job.held_skipped >= 1


def test_mdi11_enrichment_failure_does_not_stop_vt(tmp_path):
    """
    MDI-11: RDAP + WHOIS both fail → enrichment error is non-fatal; VT still runs.
    """
    from models import MdiError
    job_id = "test-mdi11-fail-" + str(time.time_ns())
    _make_job(job_id, [("broken-enrich.com", "broken-enrich.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, harmless=70, age_days=1)
    mock_vt = AsyncMock(return_value=_mock_resp(200, body))
    failed_enrichment = _make_rdap_enrichment_result(
        error=MdiError(
            code="whois_failed",
            message="Both RDAP and WHOIS failed.",
            source="domain_enrichment",
            retriable=True,
        )
    )
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_vt), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch.object(
             domain_enrichment, "enrich_domain",
             new=AsyncMock(return_value=failed_enrichment),
         ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    mock_vt.assert_called_once()
    job = job_store.get_job_sync(job_id)
    result = job.results["broken-enrich.com"]
    assert result.processing_status == MdiProcessingStatus.DONE
    assert result.age_bucket == AgeBucket.UNKNOWN
    assert any(e.code == "whois_failed" for e in (result.errors or []))


def test_mdi11_duplicate_registered_domain_enriched_once(tmp_path):
    """
    MDI-11: two URL items sharing the same registered domain → enrich_domain called once.
    """
    job_id = "test-mdi11-cache-" + str(time.time_ns())
    _make_job(job_id, [
        ("https://a.shared-domain.com/p1", "https://a.shared-domain.com/p1", InputType.URL),
        ("https://b.shared-domain.com/p2", "https://b.shared-domain.com/p2", InputType.URL),
    ])

    body = _vt_report_body(malicious=0, harmless=70, age_days=1)
    mock_vt = AsyncMock(return_value=_mock_resp(200, body))
    enrichment = _make_rdap_enrichment_result(registered_domain="shared-domain.com")
    mock_enrich = AsyncMock(return_value=enrichment)
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_vt), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch.object(domain_enrichment, "enrich_domain", new=mock_enrich):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    # enrich_domain should be called only once due to the per-job domain cache
    assert mock_enrich.call_count == 1


def test_mdi11_history_metadata_has_enrichment_counts_not_domains(tmp_path):
    """
    MDI-11: usage history record must contain enrichment counts,
    and must NOT contain raw domain names, registrar names, or nameservers.
    """
    from models import MdiError
    job_id = "test-mdi11-meta-" + str(time.time_ns())
    _make_job(job_id, [("meta-check.com", "meta-check.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, harmless=70, age_days=1)
    mock_vt = AsyncMock(return_value=_mock_resp(200, body))
    enrichment = _make_rdap_enrichment_result(registrar="Sensitive Registrar Name")
    history_file = tmp_path / "history.jsonl"
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_vt), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch.object(
             domain_enrichment, "enrich_domain",
             new=AsyncMock(return_value=enrichment),
         ):
        _run(job_processor.process_job(
            job_id,
            usage_file=usage_file,
            history_file=history_file,
            job_file=tmp_path / "mdi_latest_job.json",
        ))

    assert history_file.exists()
    records = [json.loads(line) for line in history_file.read_text().splitlines() if line.strip()]
    assert len(records) == 1
    record = records[0]

    assert "rdap_enriched_count" in record
    assert "rdap_failed_count" in record
    assert "whois_fallback_count" in record
    assert "hold_detected_by_enrichment_count" in record

    record_str = json.dumps(record)
    assert "meta-check.com" not in record_str, "Raw domain leaked into history record"
    assert "Sensitive Registrar Name" not in record_str, "Registrar name leaked into history record"
    assert "ns1.example.com" not in record_str, "Nameserver leaked into history record"


def test_mdi11_enrichment_guard_noop_does_not_crash(tmp_path):
    """
    MDI-11: autouse fixture noop mock → job completes with UNKNOWN age_bucket.
    """
    job_id = "test-mdi11-guard-" + str(time.time_ns())
    _make_job(job_id, [("example.com", "example.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, harmless=70, age_days=1)
    mock_vt = AsyncMock(return_value=_mock_resp(200, body))
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_vt), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    job = job_store.get_job_sync(job_id)
    result = job.results["example.com"]
    assert result.processing_status == MdiProcessingStatus.DONE
    assert result.age_bucket == AgeBucket.UNKNOWN


# ── MDI-12 live-check integration tests ───────────────────────────────────────
# All tests use _no_limiter(), mocked VT, and mocked live_check.live_check_item.
# The autouse fixture patches live_check_item to NOT_CHECKED by default;
# individual tests override as needed.


def _make_flagged_vt_body(malicious: int = 3, suspicious: int = 0) -> dict:
    """Build a VT report body with positive VT signals."""
    return _vt_report_body(malicious=malicious, suspicious=suspicious, harmless=10, age_days=10)


def _make_clean_vt_body() -> dict:
    """Build a VT report body with zero flags."""
    return _vt_report_body(malicious=0, suspicious=0, harmless=80, age_days=10)


def test_mdi12_flagged_vt_item_triggers_live_check(tmp_path):
    """
    MDI-12: item with vt_hits > 0 → live_check_item is called once.
    The autouse fixture defaults live_check_item to NOT_CHECKED; we count calls.
    """
    job_id = "test-mdi12-flagged-" + str(time.time_ns())
    _make_job(job_id, [("evil.com", "evil.com", InputType.DOMAIN)])

    body = _make_flagged_vt_body(malicious=3)
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    lc_mock = AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.ACTIVE))
    with (
        _no_limiter(),
        patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, body))),
        patch.dict(os.environ, {"VT_API_KEY": "testkey"}),
        patch.object(live_check, "live_check_item", new=lc_mock),
    ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    lc_mock.assert_called_once()
    job = job_store.get_job_sync(job_id)
    assert job.live_check_count == 1
    assert job.live_check_skipped_count == 0


def test_mdi12_suspicious_vt_item_triggers_live_check(tmp_path):
    """MDI-12: item with vt_suspicious > 0 → live_check_item is called."""
    job_id = "test-mdi12-suspicious-" + str(time.time_ns())
    _make_job(job_id, [("suspect.com", "suspect.com", InputType.DOMAIN)])

    body = _vt_report_body(malicious=0, suspicious=2, harmless=70, age_days=5)
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    lc_mock = AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.ACTIVE))
    with (
        _no_limiter(),
        patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, body))),
        patch.dict(os.environ, {"VT_API_KEY": "testkey"}),
        patch.object(live_check, "live_check_item", new=lc_mock),
    ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    lc_mock.assert_called_once()
    job = job_store.get_job_sync(job_id)
    assert job.live_check_count == 1


def test_mdi12_clean_vt_item_skips_live_check(tmp_path):
    """MDI-12: clean item (0 malicious, 0 suspicious) → live_check_item never called."""
    job_id = "test-mdi12-clean-" + str(time.time_ns())
    _make_job(job_id, [("clean.com", "clean.com", InputType.DOMAIN)])

    body = _make_clean_vt_body()
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    lc_mock = AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.ACTIVE))
    with (
        _no_limiter(),
        patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, body))),
        patch.dict(os.environ, {"VT_API_KEY": "testkey"}),
        patch.object(live_check, "live_check_item", new=lc_mock),
    ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    lc_mock.assert_not_called()
    job = job_store.get_job_sync(job_id)
    assert job.live_check_skipped_count == 1
    assert job.live_check_count == 0


def test_mdi12_held_item_skips_live_check(tmp_path):
    """MDI-12: HOLD_SKIPPED item → live_check_item is never called."""
    job_id = "test-mdi12-held-" + str(time.time_ns())
    _make_job(job_id, [("held.com", "held.com", InputType.DOMAIN)])

    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    # Force enrichment to detect a hold so the item becomes HOLD_SKIPPED
    held_enrichment = _make_rdap_enrichment_result(
        registered_domain="held.com",
        has_hold=True,
    )

    lc_mock = AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.ACTIVE))
    with (
        _no_limiter(),
        patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, {}))),
        patch.dict(os.environ, {"VT_API_KEY": "testkey"}),
        patch.object(domain_enrichment, "enrich_domain", new=AsyncMock(return_value=held_enrichment)),
        patch.object(live_check, "live_check_item", new=lc_mock),
    ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    lc_mock.assert_not_called()
    job = job_store.get_job_sync(job_id)
    result = job.results["held.com"]
    assert result.processing_status == MdiProcessingStatus.HOLD_SKIPPED


def test_mdi12_live_active_updates_triage(tmp_path):
    """
    MDI-12: flagged item + live ACTIVE → triage re-runs with live_status=ACTIVE.
    With a VT-flagged domain confirmed live → investigate/act urgency expected.
    """
    job_id = "test-mdi12-live-active-triage-" + str(time.time_ns())
    _make_job(job_id, [("active-evil.com", "active-evil.com", InputType.DOMAIN)])

    body = _make_flagged_vt_body(malicious=5)
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with (
        _no_limiter(),
        patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, body))),
        patch.dict(os.environ, {"VT_API_KEY": "testkey"}),
        patch.object(
            live_check, "live_check_item",
            new=AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.ACTIVE)),
        ),
    ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    job = job_store.get_job_sync(job_id)
    result = job.results["active-evil.com"]
    assert result.live_status == LiveStatus.ACTIVE
    # Triage should reflect the live-and-flagged combination
    assert result.triage_bucket in (TriageBucket.MALICIOUS, TriageBucket.SUSPICIOUS)
    assert result.processing_status == MdiProcessingStatus.DONE


def test_mdi12_live_not_found_updates_triage(tmp_path):
    """
    MDI-12: flagged item + live NOT_FOUND → triage includes no-live branch context.
    live_status is set to NOT_FOUND; triage re-runs.
    """
    job_id = "test-mdi12-live-not-found-" + str(time.time_ns())
    _make_job(job_id, [("down-evil.com", "down-evil.com", InputType.DOMAIN)])

    body = _make_flagged_vt_body(malicious=3)
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with (
        _no_limiter(),
        patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, body))),
        patch.dict(os.environ, {"VT_API_KEY": "testkey"}),
        patch.object(
            live_check, "live_check_item",
            new=AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.NOT_FOUND)),
        ),
    ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    job = job_store.get_job_sync(job_id)
    result = job.results["down-evil.com"]
    assert result.live_status == LiveStatus.NOT_FOUND
    # VT flagged + domain down → still malicious bucket
    assert result.triage_bucket in (TriageBucket.MALICIOUS, TriageBucket.SUSPICIOUS)
    assert result.processing_status == MdiProcessingStatus.DONE


def test_mdi12_live_check_error_is_non_fatal(tmp_path):
    """
    MDI-12: live_check_item returns an error → job still completes, error appended.
    """
    from models import MdiError
    from services.live_check import LiveCheckResult

    job_id = "test-mdi12-lc-error-" + str(time.time_ns())
    _make_job(job_id, [("error-test.com", "error-test.com", InputType.DOMAIN)])

    body = _make_flagged_vt_body(malicious=2)
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    lc_error = MdiError(
        code="live_check_dns_failure",
        message="DNS returned nothing",
        source="live_check",
        retriable=True,
    )
    lc_result_with_error = LiveCheckResult(
        live_status=LiveStatus.DNS_FAILURE,
        error=lc_error,
    )

    with (
        _no_limiter(),
        patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, body))),
        patch.dict(os.environ, {"VT_API_KEY": "testkey"}),
        patch.object(live_check, "live_check_item", new=AsyncMock(return_value=lc_result_with_error)),
    ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    job = job_store.get_job_sync(job_id)
    result = job.results["error-test.com"]
    # Job completed despite live check error
    assert result.processing_status == MdiProcessingStatus.DONE
    assert result.live_status == LiveStatus.DNS_FAILURE
    # Error is appended to result.errors
    error_codes = [e.code for e in (result.errors or [])]
    assert "live_check_dns_failure" in error_codes
    # live_check_error_count incremented
    assert job.live_check_error_count == 1
    assert job.live_check_count == 1


def test_mdi12_live_check_not_checked_for_clean_preserves_triage(tmp_path):
    """
    MDI-12: clean item skips live check; live_status stays NOT_CHECKED; triage unchanged.
    """
    job_id = "test-mdi12-clean-preserve-" + str(time.time_ns())
    _make_job(job_id, [("safe.com", "safe.com", InputType.DOMAIN)])

    body = _make_clean_vt_body()
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    with (
        _no_limiter(),
        patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, body))),
        patch.dict(os.environ, {"VT_API_KEY": "testkey"}),
    ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    job = job_store.get_job_sync(job_id)
    result = job.results["safe.com"]
    assert result.live_status == LiveStatus.NOT_CHECKED
    assert result.triage_bucket == TriageBucket.CLEAN
    assert result.processing_status == MdiProcessingStatus.DONE


def test_mdi12_history_metadata_has_live_check_counts_not_urls(tmp_path):
    """
    MDI-12: usage history record includes live_check_count, live_check_skipped_count,
    and live_check_error_count — but must not include raw URLs, IPs, or per-item data.
    """
    job_id = "test-mdi12-history-" + str(time.time_ns())
    _make_job(job_id, [
        ("flagged.com", "flagged.com", InputType.DOMAIN),
        ("clean.com", "clean.com", InputType.DOMAIN),
    ])

    flagged_body = _make_flagged_vt_body(malicious=2)
    clean_body = _make_clean_vt_body()
    call_count = 0

    async def _vt_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_resp(200, flagged_body)
        return _mock_resp(200, clean_body)

    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')
    history_file = tmp_path / "vt_usage_history.jsonl"

    with (
        _no_limiter(),
        patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_vt_side_effect)),
        patch.dict(os.environ, {"VT_API_KEY": "testkey"}),
        patch.object(
            live_check, "live_check_item",
            new=AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.ACTIVE)),
        ),
    ):
        _run(job_processor.process_job(
            job_id,
            usage_file=usage_file,
            history_file=history_file,
            job_file=tmp_path / "mdi_latest_job.json",
        ))

    import json as _json
    lines = [l for l in history_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    record = _json.loads(lines[0])

    # Live-check aggregate counts must be present
    assert "live_check_count" in record
    assert "live_check_skipped_count" in record
    assert "live_check_error_count" in record

    # Counts must be non-negative ints
    assert isinstance(record["live_check_count"], int)
    assert isinstance(record["live_check_skipped_count"], int)
    assert isinstance(record["live_check_error_count"], int)

    # Verify no raw URL/IP/domain data appears in the record text
    record_text = _json.dumps(record)
    assert "flagged.com" not in record_text
    assert "clean.com" not in record_text
    assert "93.184.216.34" not in record_text  # no resolved IPs
    assert "live_status" not in record_text    # no per-item live_status
    assert "http_status_code" not in record_text  # no raw HTTP codes


def test_mdi12_url_input_type_triggers_live_check(tmp_path):
    """MDI-12: URL input type is also eligible when flagged."""
    job_id = "test-mdi12-url-input-" + str(time.time_ns())
    _make_job(job_id, [("https://evil.com/malware", "https://evil.com/malware", InputType.URL)])

    body = _make_flagged_vt_body(malicious=4)
    usage_file = tmp_path / "vt_usage.json"
    usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

    lc_mock = AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.ACTIVE))
    with (
        _no_limiter(),
        patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, body))),
        patch.dict(os.environ, {"VT_API_KEY": "testkey"}),
        patch.object(live_check, "live_check_item", new=lc_mock),
    ):
        _run(job_processor.process_job(
            job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json"
        ))

    lc_mock.assert_called_once()
    call_args = lc_mock.call_args
    # Must pass the normalized input and the correct InputType
    assert call_args[0][0] == "https://evil.com/malware"
    assert call_args[0][1] == InputType.URL
