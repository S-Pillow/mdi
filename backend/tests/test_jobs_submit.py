"""
Tests for job submission, job status endpoints, and the async processing loop.

Strategy:
  - Endpoint tests (submit / status) use FastAPI TestClient — test initial state.
  - Processing tests call job_processor.process_job() directly via asyncio.run()
    with mocked VT (_vt_request) and temp file paths (tmp_path).
  - Live /var/lib/dns-tool/vt_usage.json is never modified.
  - Live /var/lib/dns-tool/mdi_latest_job.json is never created or modified.
  - No real VT API calls are made.

MDI-08A isolation fix (two paths):
  1. Direct process_job() calls: all now pass job_file=tmp_path / "mdi_latest_job.json".
  2. Background tasks from POST /api/mdi/jobs/submit TestClient tests: cannot
     inject job_file= through the endpoint, so an autouse fixture redirects
     MDI_LATEST_JOB_FILE to tmp_path for every test in this module.
  Prior to this fix, both paths defaulted to /var/lib/dns-tool/mdi_latest_job.json
  and wrote test artifacts to the live recovery file during every test run.
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
    EvidenceStatus,
    Freshness,
    InputType,
    MdiProcessingStatus,
    RecommendedAction,
    TriageBucket,
    VtModeUsed,
)
from services import job_processor, job_store
from services.job_store import InMemoryJob
from services.quota_writer import increment_quota, read_remaining_quota

client = TestClient(app)


# ── Module-level test isolation ────────────────────────────────────────────────

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
    """
    monkeypatch.setenv("MDI_LATEST_JOB_FILE", str(tmp_path / "mdi_latest_job.json"))


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
              stale_threshold_days: int = 5) -> InMemoryJob:
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
    assert result.recommended_action == RecommendedAction.INVESTIGATE


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
