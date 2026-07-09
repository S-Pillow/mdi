"""
MDI-65 — Server-side action completion summary tests.

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
from fastapi.testclient import TestClient
from main import app
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
from services import job_actions, job_persistence, job_store
from services.job_store import InMemoryJob, register_recovered_job
from services.pending_analysis import is_pending_analysis
from services.quota_writer import QuotaLockTimeout

client = TestClient(app)


def _run(coro):
    return asyncio.run(coro)


def _mock_resp(status_code: int, body: dict = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    return m


def _no_limiter():
    return patch.object(vt_svc._VT_LIMITER, "acquire", new=AsyncMock())


def _vt_body(malicious=0, suspicious=0, age_days=1):
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


def _clean_row(normalized: str, *, position: int = 1) -> MdiResultItem:
    return MdiResultItem(
        input_original=normalized,
        input_normalized=normalized,
        input_type=InputType.URL,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=92,
        vt_ratio="0/92",
        vt_scan_date="2026-07-01T00:00:00Z",
        freshness=Freshness.FRESH,
        triage_bucket=TriageBucket.CLEAN,
        live_status=LiveStatus.NOT_CHECKED,
        age_bucket=AgeBucket.MATURE,
    )


def _pending_row(url: str, *, position: int = 1) -> MdiResultItem:
    pending_err = vt_svc._pending_error(vt_svc._PENDING_SUBMITTED_MSG)
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
        live_status=LiveStatus.NOT_CHECKED,
        errors=[pending_err],
        age_bucket=AgeBucket.UNKNOWN,
    )


def _make_job(items: list[MdiResultItem], job_id: str = "mdi65-job") -> InMemoryJob:
    job = InMemoryJob(
        job_id=job_id,
        status="done",
        submitted_at=time.time() - 100,
        completed_at=time.time() - 50,
        total=len(items),
        processed=len(items),
    )
    for item in items:
        job.results[item.input_normalized] = item
        job.item_order.append(item.input_normalized)
    return job


def _summary_dict(job: InMemoryJob) -> dict:
    assert job.last_action_summary is not None
    return job.last_action_summary


# ── 1. Selected Refresh Report two clean rows ───────────────────────────────

def test_selected_refresh_two_clean_rows_summary(tmp_path):
    items = [_clean_row("a.example.com", position=1), _clean_row("b.example.com", position=2)]
    job = _make_job(items)
    register_recovered_job(job)
    job_file = tmp_path / "mdi_latest_job.json"
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1, 2])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=job_file,
        ))

    s = _summary_dict(job)
    assert s["action"] == "refresh"
    assert s["scope"] == "selected"
    assert s["status"] == "completed"
    assert s["items_completed"] == 2
    assert s["items_skipped"] == 0
    assert s["items_failed"] == 0
    assert s["quota_units_consumed"] == 2

    resp = client.get(f"/api/mdi/jobs/{job.job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_action_summary"]["items_completed"] == 2


# ── 2. Refresh Pending mixed outcomes ─────────────────────────────────────────

def test_refresh_pending_mixed_outcomes(tmp_path):
    pending1 = _pending_row("http://p1.example/", position=1)
    pending2 = _pending_row("http://p2.example/", position=2)
    pending3 = _pending_row("http://p3.example/", position=3)
    job = _make_job([pending1, pending2, pending3])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.PENDING)

    call_count = 0

    async def _vt_side_effect(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_resp(200, _vt_body(0))
        if call_count == 2:
            return _mock_resp(200, _empty_pending_body())
        return _mock_resp(400)

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_vt_side_effect)):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    s = _summary_dict(job)
    assert s["scope"] == "pending"
    assert s["items_processed"] == 3
    assert s["items_completed"] == 1
    assert s["items_still_pending"] == 2
    assert s["items_failed"] == 0


def _empty_pending_body():
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


# ── 3. Refresh Selected Pending mixed selection ───────────────────────────────

def test_selected_pending_mixed_selection_summary(tmp_path):
    pending = _pending_row("http://sp.example/", position=1)
    clean = _clean_row("https://clean.example/", position=2)
    job = _make_job([pending, clean])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.SELECTED_PENDING, positions=[1, 2])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    s = _summary_dict(job)
    assert s["items_eligible"] == 1
    assert s["items_skipped"] == 1
    assert s["items_completed"] == 1
    assert s["skipped_reasons_summary"].get("not_pending") == 1


# ── 4. Pending remains pending ────────────────────────────────────────────────

def test_pending_remains_pending_counts_still_pending(tmp_path):
    pending = _pending_row("http://still-pending.example/", position=1)
    job = _make_job([pending])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.PENDING)

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _empty_pending_body()))):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    s = _summary_dict(job)
    assert s["items_still_pending"] == 1
    assert s["items_completed"] == 0
    assert is_pending_analysis(job.results["http://still-pending.example/"])


# ── 5. VT error path ──────────────────────────────────────────────────────────

def test_vt_error_path_failed_without_evidence(tmp_path):
    row = MdiResultItem(
        input_original="http://fail.example/",
        input_normalized="http://fail.example/",
        input_type=InputType.URL,
        position=1,
        processing_status=MdiProcessingStatus.DONE,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=0,
        vt_ratio="",
        vt_scan_date=None,
        freshness=Freshness.UNKNOWN,
        triage_bucket=TriageBucket.ERROR,
        live_status=LiveStatus.NOT_CHECKED,
        errors=[],
        age_bucket=AgeBucket.UNKNOWN,
    )
    job = _make_job([row])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(500))):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    s = _summary_dict(job)
    assert s["items_failed"] == 1
    assert s["items_completed"] == 0


# ── 6. Quota mid-action stop ──────────────────────────────────────────────────

def test_quota_mid_action_stop(tmp_path):
    items = [_clean_row(f"q{i}.example.com", position=i) for i in range(1, 4)]
    job = _make_job(items)
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1, 2, 3])
    usage_file = tmp_path / "u.json"
    usage_file.write_text(json.dumps({"date": "2026-07-09", "count": 0}))

    remaining_values = [2, 1, 0]

    def _remaining(*_args, **_kwargs):
        return remaining_values.pop(0) if remaining_values else 0

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))), \
         patch("services.job_actions.read_remaining_quota", side_effect=_remaining):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=usage_file, job_file=tmp_path / "j.json",
        ))

    s = _summary_dict(job)
    assert s["items_processed"] == 2
    assert s["items_completed"] == 2
    assert s["items_quota_blocked"] == 1
    assert s["items_failed"] == 0


def test_quota_lock_timeout_counts_quota_blocked(tmp_path):
    row = _clean_row("lock.example.com")
    job = _make_job([row])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.job_actions.read_remaining_quota", side_effect=QuotaLockTimeout()):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    s = _summary_dict(job)
    assert s["items_quota_blocked"] == 1
    assert s["items_processed"] == 0


# ── 7. Request New Scan selected ──────────────────────────────────────────────

def test_scan_selected_summary(tmp_path):
    row = _clean_row("https://scan.example/", position=1)
    job = _make_job([row])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1], confirm=True)

    async def _vt_side_effect(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(200, {})
        return _mock_resp(200, _vt_body(0))

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_vt_side_effect)):
        _run(job_actions.run_scan_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    s = _summary_dict(job)
    assert s["action"] == "scan"
    assert s["items_completed"] == 1
    assert s["items_failed"] == 0


# ── 8. MDI-64 regression — per-row persist still called ───────────────────────

def test_mdi64_per_row_persist_still_called(tmp_path):
    items = [_clean_row("p1.example.com", position=1), _clean_row("p2.example.com", position=2)]
    job = _make_job(items)
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1, 2])
    persist_calls = []

    real_write = job_persistence.write_latest_job

    async def _spy_write(j, **kwargs):
        persist_calls.append(j.job_id)
        await real_write(j, **kwargs)

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))), \
         patch.object(job_persistence, "write_latest_job", new=AsyncMock(side_effect=_spy_write)):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    assert len(persist_calls) >= 3
    assert job.last_action_summary is not None


# ── 9. Old job deserialize ────────────────────────────────────────────────────

def test_old_job_without_summary_deserializes(tmp_path):
    job = _make_job([_clean_row("old.example.com")])
    job_file = tmp_path / "mdi_latest_job.json"
    data = job_persistence.serialize_job(job)
    assert "last_action_summary" not in data or data.get("last_action_summary") is None
    job_file.write_text(json.dumps(data))

    recovered = job_persistence.read_latest_job(job_file=job_file)
    assert recovered is not None
    assert recovered.last_action_summary is None


# ── 10. Summary persisted on disk ───────────────────────────────────────────

def test_summary_persisted_on_disk(tmp_path):
    job = _make_job([_clean_row("disk.example.com")])
    register_recovered_job(job)
    job_file = tmp_path / "mdi_latest_job.json"
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=job_file,
        ))

    on_disk = json.loads(job_file.read_text())
    assert on_disk["last_action_summary"]["items_completed"] == 1


# ── 11. History record summary fields ─────────────────────────────────────────

def test_history_record_includes_summary_fields(tmp_path):
    job = _make_job([_clean_row("hist.example.com")])
    register_recovered_job(job)
    history = tmp_path / "history.jsonl"
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))):
        _run(job_actions.run_refresh_action(
            job.job_id, req,
            usage_file=tmp_path / "u.json",
            history_file=history,
            job_file=tmp_path / "j.json",
        ))

    rec = json.loads(history.read_text().strip())
    assert rec["action_summary_scope"] == "selected"
    assert rec["summary_items_completed"] == 1
    assert rec["items_processed"] == 1
    assert rec["items_quota_blocked"] == 0


# ── Classifier unit tests ─────────────────────────────────────────────────────

def test_classify_completed_clean_row():
    row = _clean_row("c.example.com")
    assert job_actions._classify_action_row_outcome(row) == "completed"


def test_classify_still_pending_row():
    row = _pending_row("http://p.example/")
    assert job_actions._classify_action_row_outcome(row) == "still_pending"
