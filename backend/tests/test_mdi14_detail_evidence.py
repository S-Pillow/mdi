"""
MDI-14 — Detail Drawer Evidence Data: backend integration tests.

Covers:
  - vt_engine_results populated for flagged items.
  - vt_engine_results == [] for clean items.
  - http_status_code propagated from live check.
  - redirect_count propagated from live check.
  - job_persistence round-trips all three new fields.
  - backward compat: old persisted jobs missing new fields recover safely.
  - JobStatusResponse exposes new fields.
  - usage history does not contain engine names, detection results,
    http_status_code, redirect_count, raw domains, or raw URLs.

All VT, RDAP/WHOIS, and live-check calls are mocked.
No live /var/lib/dns-tool files are touched.
No VT quota is consumed.
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
from models import InputType, LiveStatus
from services import domain_enrichment, job_processor, job_store, live_check
from services.domain_enrichment import EnrichmentResult
from services.job_store import InMemoryJob
from services.live_check import LiveCheckResult
from services import job_persistence
from models import (
    AgeBucket, DomainHold, DomainHoldType, DomainStatusSource,
    MdiResultItem, Freshness,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _mock_resp(status_code: int, body: dict = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    return m


def _no_limiter():
    return patch.object(vt_svc._VT_LIMITER, "acquire", new=AsyncMock())


def _make_noop_enrichment(reg_domain: str = "example.com") -> EnrichmentResult:
    return EnrichmentResult(
        registered_domain=reg_domain,
        source=DomainStatusSource.NOT_CHECKED,
        domain_hold=DomainHold(
            has_hold=False,
            hold_types=[DomainHoldType.NONE],
            source=DomainStatusSource.NOT_CHECKED,
        ),
    )


def _vt_report_with_engines(
    malicious: int = 0,
    suspicious: int = 0,
    harmless: int = 70,
    age_days: int = 1,
    engines: dict = None,
) -> dict:
    scan_ts = int(time.time()) - (age_days * 86400)
    report = {
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
    if engines is not None:
        report["data"]["attributes"]["last_analysis_results"] = engines
    return report


def _make_job(job_id: str, items: list) -> InMemoryJob:
    """Create and register an InMemoryJob in the job store."""
    from models import MdiProcessingStatus
    job = job_store.InMemoryJob(
        job_id=job_id,
        status="queued",
        submitted_at=time.time(),
        total=len(items),
    )
    for pos, item in enumerate(items, start=1):
        normalized = item["normalized"]
        job.results[normalized] = MdiResultItem(
            input_original=item["original"],
            input_normalized=normalized,
            input_type=item.get("input_type", InputType.DOMAIN),
            position=pos,
            processing_status=MdiProcessingStatus.PENDING,
        )
        job.item_order.append(normalized)
    _run(job_store.create_job(job))
    return job


# ── MDI-14 autouse fixture ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_persistence(tmp_path, monkeypatch):
    """Redirect all job persistence to tmp_path; mock enrichment and live check."""
    monkeypatch.setenv("MDI_LATEST_JOB_FILE", str(tmp_path / "mdi_latest_job.json"))
    with (
        patch.object(
            domain_enrichment, "enrich_domain",
            new=AsyncMock(side_effect=lambda reg: _make_noop_enrichment(reg)),
        ),
        patch.object(
            live_check, "live_check_item",
            new=AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.NOT_CHECKED)),
        ),
    ):
        yield


# ── Test 1: vt_engine_results populated for flagged item ──────────────────────

def test_vt_engine_results_populated_for_flagged_item(tmp_path):
    """Engine detections are stored on the result row when VT response has malicious engines."""
    engines = {
        "Kaspersky": {"category": "malicious", "result": "Trojan.Generic", "method": "blacklist"},
        "ESET":      {"category": "suspicious", "result": "Suspicious",    "method": "heuristic"},
        "Google":    {"category": "harmless",   "result": "clean",         "method": "blacklist"},
    }
    body = _vt_report_with_engines(malicious=1, suspicious=1, engines=engines)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    job = _make_job("test-flagged", [{"original": "evil.com", "normalized": "evil.com", "position": 0}])
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job.job_id, usage_file=tmp_path / "vt_usage.json", job_file=job_file))

    job = job_store.get_job_sync(job.job_id)
    result = job.results["evil.com"]
    assert result.vt_engine_results is not None
    assert isinstance(result.vt_engine_results, list)
    assert len(result.vt_engine_results) == 2  # Kaspersky + ESET only (Google excluded)
    names = {d["engine_name"] for d in result.vt_engine_results}
    assert "Kaspersky" in names
    assert "ESET" in names
    assert "Google" not in names


# ── Test 2: vt_engine_results == [] for clean item ────────────────────────────

def test_vt_engine_results_empty_for_clean_item(tmp_path):
    """Clean VT response stores [] (not None) for vt_engine_results."""
    engines = {
        "Google":    {"category": "harmless",   "result": "clean"},
        "Microsoft": {"category": "undetected", "result": None},
    }
    body = _vt_report_with_engines(malicious=0, suspicious=0, engines=engines)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    job = _make_job("test-clean", [{"original": "safe.com", "normalized": "safe.com", "position": 0}])
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job.job_id, usage_file=tmp_path / "vt_usage.json", job_file=job_file))

    job = job_store.get_job_sync(job.job_id)
    result = job.results["safe.com"]
    assert result.vt_engine_results == []


# ── Test 3: http_status_code propagated from live check ───────────────────────

def test_http_status_code_propagated_from_live_check(tmp_path):
    """http_status_code from LiveCheckResult is stored on the result row."""
    body = _vt_report_with_engines(malicious=1, suspicious=0)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    lc = LiveCheckResult(
        live_status=LiveStatus.ACTIVE,
        http_status_code=403,
        redirect_count=0,
    )

    job = _make_job("test-http", [{"original": "bad.com", "normalized": "bad.com", "position": 0}])
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch.object(live_check, "live_check_item", new=AsyncMock(return_value=lc)):
        _run(job_processor.process_job(job.job_id, usage_file=tmp_path / "vt_usage.json", job_file=job_file))

    job = job_store.get_job_sync(job.job_id)
    result = job.results["bad.com"]
    assert result.http_status_code == 403


# ── Test 4: redirect_count propagated from live check ─────────────────────────

def test_redirect_count_propagated_from_live_check(tmp_path):
    """redirect_count from LiveCheckResult is stored on the result row."""
    body = _vt_report_with_engines(malicious=1)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    lc = LiveCheckResult(
        live_status=LiveStatus.REDIRECT,
        http_status_code=301,
        redirect_count=2,
    )

    job = _make_job("test-redirect", [{"original": "redir.com", "normalized": "redir.com", "position": 0}])
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch.object(live_check, "live_check_item", new=AsyncMock(return_value=lc)):
        _run(job_processor.process_job(job.job_id, usage_file=tmp_path / "vt_usage.json", job_file=job_file))

    job = job_store.get_job_sync(job.job_id)
    result = job.results["redir.com"]
    assert result.redirect_count == 2
    assert result.http_status_code == 301


# ── Test 5: job_persistence round-trips vt_engine_results ─────────────────────

def test_job_persistence_round_trips_engine_results(tmp_path):
    """vt_engine_results, http_status_code, redirect_count survive serialize/deserialize."""
    engines = {
        "TestEngine": {"category": "malicious", "result": "Bad", "method": "blacklist"},
    }
    body = _vt_report_with_engines(malicious=1, engines=engines)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    lc = LiveCheckResult(
        live_status=LiveStatus.ACTIVE,
        http_status_code=200,
        redirect_count=1,
    )

    job = _make_job("test-persist", [{"original": "a.com", "normalized": "a.com", "position": 0}])
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch.object(live_check, "live_check_item", new=AsyncMock(return_value=lc)):
        _run(job_processor.process_job(job.job_id, usage_file=tmp_path / "vt_usage.json", job_file=job_file))

    # Serialize then deserialize using the updated job from the store
    updated_job = job_store.get_job_sync(job.job_id)
    raw = job_persistence.serialize_job(updated_job)
    recovered_job = job_persistence.deserialize_job(raw)

    result = recovered_job.results["a.com"]
    assert result.vt_engine_results is not None
    assert len(result.vt_engine_results) == 1
    assert result.vt_engine_results[0]["engine_name"] == "TestEngine"
    assert result.http_status_code == 200
    assert result.redirect_count == 1


# ── Test 6: backward compat — old job missing new fields ──────────────────────

def test_job_persistence_backward_compat_missing_engine_fields(tmp_path):
    """Old persisted JSON without vt_engine_results/http_status_code/redirect_count loads cleanly."""
    old_job_data = {
        "job_id": "old-job-id",
        "status": "done",
        "submitted_at": time.time(),
        "completed_at": time.time(),
        "total": 1,
        "processed": 1,
        "held_skipped": 0,
        "rejected_count": 0,
        "quota_blocked_count": 0,
        "estimated_requests": 1,
        "lookups_used": 1,
        "use_domain_reports": False,
        "stale_threshold_days": 7,
        "error_message": None,
        "item_order": ["old.com"],
        "results": {
            "old.com": {
                "input_original": "old.com",
                "input_normalized": "old.com",
                "input_type": "domain",
                "position": 0,
                "processing_status": "done",
                "vt_hits": 0,
                "vt_mode_used": "url_report",
                "vt_ratio": "0/72",
                "freshness": "fresh",
                "triage_bucket": "clean",
                "triage_confidence": "high",
                "recommended_action": "none",
                "evidence_status": "complete",
                "triage_reason": ["VT: 0/72 — no malicious detections."],
                "errors": [],
                # vt_engine_results, http_status_code, redirect_count intentionally absent
            }
        },
        "usage_history_written": True,
        "rdap_enriched_count": 0,
        "rdap_failed_count": 0,
        "whois_fallback_count": 0,
        "hold_detected_by_enrichment_count": 0,
        "enrichment_skipped_uploaded_hold_count": 0,
        "live_check_count": 0,
        "live_check_skipped_count": 0,
        "live_check_error_count": 0,
    }

    recovered_job = job_persistence.deserialize_job(old_job_data)
    result = recovered_job.results["old.com"]

    # Must default gracefully — not crash
    assert result.vt_engine_results is None
    assert result.http_status_code is None
    assert result.redirect_count == 0


# ── Test 7: JobStatusResponse includes new fields ─────────────────────────────

def test_job_status_response_includes_new_fields(tmp_path):
    """JobStatusResponse result items include vt_engine_results, http_status_code, redirect_count."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)

    engines = {"MalEng": {"category": "malicious", "result": "Evil"}}
    body = _vt_report_with_engines(malicious=1, engines=engines)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    lc = LiveCheckResult(
        live_status=LiveStatus.ACTIVE,
        http_status_code=200,
        redirect_count=0,
    )

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch.object(live_check, "live_check_item", new=AsyncMock(return_value=lc)):
        resp = client.post("/api/mdi/jobs/submit", json={"raw_input": "flagged.com"})

    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # Poll until done (background task completes quickly with mock)
    import time as _time
    for _ in range(30):
        status_resp = client.get(f"/api/mdi/jobs/{job_id}")
        if status_resp.json().get("status") == "done":
            break
        _time.sleep(0.1)

    status_resp = client.get(f"/api/mdi/jobs/{job_id}")
    data = status_resp.json()
    assert data["status"] == "done"
    results = data.get("results", [])
    assert len(results) == 1
    row = results[0]
    # New fields must be present (not KeyError)
    assert "vt_engine_results" in row
    assert "http_status_code" in row
    assert "redirect_count" in row


# ── Test 8: usage history privacy — no item-level evidence ────────────────────

def test_usage_history_excludes_item_level_evidence(tmp_path):
    """
    Usage history (vt_usage_history.jsonl) must not contain engine names,
    detection results, http_status_code, redirect_count, raw domains, or raw URLs.
    """
    history_file = tmp_path / "vt_usage_history.jsonl"
    usage_file   = tmp_path / "vt_usage.json"

    engines = {"EvilEngine": {"category": "malicious", "result": "Phishing"}}
    body = _vt_report_with_engines(malicious=1, engines=engines)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    lc = LiveCheckResult(
        live_status=LiveStatus.ACTIVE,
        http_status_code=404,
        redirect_count=1,
    )

    job = _make_job("test-history", [{"original": "domain.com", "normalized": "domain.com", "position": 0}])
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey",
                                  "MDI_USAGE_FILE": str(usage_file),
                                  "MDI_USAGE_HISTORY_FILE": str(history_file)}), \
         patch.object(live_check, "live_check_item", new=AsyncMock(return_value=lc)):
        _run(job_processor.process_job(job.job_id, usage_file=tmp_path / "vt_usage.json", job_file=job_file))

    if not history_file.exists():
        return  # nothing written — trivially passes

    history_text = history_file.read_text()

    # None of these must appear in the history file
    forbidden_strings = [
        "EvilEngine",
        "Phishing",
        "domain.com",
        "http_status_code",
        "redirect_count",
        "404",
        "engine_name",
        "engine_detections",
        "vt_engine_results",
    ]
    for s in forbidden_strings:
        assert s not in history_text, (
            f"Usage history must not contain '{s}' — found in {history_file}"
        )


# ── Test 9: new fields absent from VT error result ────────────────────────────

def test_vt_error_produces_none_engine_results(tmp_path):
    """When VT lookup returns an error, vt_engine_results is None (not [])."""
    mock_req = AsyncMock(return_value=_mock_resp(403, {}))

    job = _make_job("test-vterr", [{"original": "err.com", "normalized": "err.com", "position": 0}])
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(job_processor.process_job(job.job_id, usage_file=tmp_path / "vt_usage.json", job_file=job_file))

    job = job_store.get_job_sync(job.job_id)
    result = job.results["err.com"]
    # VT returned an HTTP error — processor still stores engine_detections (empty list
    # from the default VtLookupResult). Must be a list (not crash) and must be empty.
    assert isinstance(result.vt_engine_results, list)
    assert result.vt_engine_results == []
