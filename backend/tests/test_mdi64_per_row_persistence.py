"""
MDI-64 — Per-row persistence during bulk refresh/scan actions.

All VT / live-check HTTP is mocked. No live /var/lib/dns-tool files touched.
"""
from __future__ import annotations

import asyncio
import json
import logging
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
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
    RefreshScanScope,
    TriageBucket,
    VtModeUsed,
)
from services import job_actions, job_persistence, job_store, live_check, triage_rules
from services.job_store import InMemoryJob, register_recovered_job
from services.live_check import LiveCheckResult
from services.pending_analysis import is_pending_refresh_eligible


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
        live_status=LiveStatus.NOT_CHECKED,
        errors=[pending_err],
        age_bucket=AgeBucket.UNKNOWN,
    )


def _make_job(
    items: list[MdiResultItem],
    *,
    use_domain_reports=False,
    stale_threshold_days=7,
    job_id="test-mdi64",
    vt_refresh_count=0,
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
        vt_refresh_count=vt_refresh_count,
    )
    for item in items:
        job.results[item.input_normalized] = item
        job.item_order.append(item.input_normalized)
    return job


def _read_result_field(job_file: Path, normalized: str, field: str):
    data = json.loads(job_file.read_text())
    return data["results"][normalized][field]


# ── 1. Per-row persist after refresh ─────────────────────────────────────────

def test_per_row_persist_after_each_refresh_row(tmp_path):
    items = [
        _make_result("row1.example.com", position=1, vt_hits=0),
        _make_result("row2.example.com", position=2, vt_hits=0),
        _make_result("row3.example.com", position=3, vt_hits=0),
    ]
    job = _make_job(items)
    job_file = tmp_path / "mdi_latest_job.json"
    persist_calls = []

    real_write = job_persistence.write_latest_job

    async def _spy_write(j, **kwargs):
        persist_calls.append(j.job_id)
        await real_write(j, **kwargs)

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(1)))), \
         patch.object(job_persistence, "write_latest_job", new=AsyncMock(side_effect=_spy_write)):
        _run(job_actions._run_items(
            job, items, "refresh",
            usage_file=tmp_path / "u.json",
            job_file=job_file,
        ))

    assert len(persist_calls) == 3


# ── 2. Per-row persist after scan ─────────────────────────────────────────────

def test_per_row_persist_after_each_scan_row(tmp_path):
    items = [
        _make_result(
            "https://scan1.example.com/",
            position=1,
            input_type=InputType.URL,
            freshness=Freshness.VERY_STALE,
        ),
        _make_result(
            "https://scan2.example.com/",
            position=2,
            input_type=InputType.URL,
            freshness=Freshness.VERY_STALE,
        ),
    ]
    job = _make_job(items)
    job_file = tmp_path / "mdi_latest_job.json"
    persist_calls = []

    real_write = job_persistence.write_latest_job

    async def _spy_write(j, **kwargs):
        persist_calls.append(j.job_id)
        await real_write(j, **kwargs)

    async def _vt_side_effect(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(200, {})
        return _mock_resp(200, _vt_body(malicious=0))

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_vt_side_effect)), \
         patch.object(job_persistence, "write_latest_job", new=AsyncMock(side_effect=_spy_write)):
        _run(job_actions._run_items(
            job, items, "scan",
            usage_file=tmp_path / "u.json",
            job_file=job_file,
        ))

    assert len(persist_calls) == 2


# ── 3. Crash simulation after row 1 ───────────────────────────────────────────

def test_crash_after_row_one_preserves_first_row(tmp_path):
    item1 = _make_result("saved.example.com", position=1, vt_hits=0)
    item2 = _make_result("unsaved.example.com", position=2, vt_hits=0)
    job = _make_job([item1, item2])
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(2)))):
        _run(job_actions._run_items(
            job, [item1], "refresh",
            usage_file=tmp_path / "u.json",
            job_file=job_file,
        ))

    recovered = job_persistence.read_latest_job(job_file=job_file)
    assert recovered is not None
    assert recovered.results["saved.example.com"].vt_hits == 2
    assert recovered.results["unsaved.example.com"].vt_hits == 0


# ── 4. No partial corrupt row ─────────────────────────────────────────────────

def test_unpersisted_row_remains_valid_json(tmp_path):
    item1 = _make_result("done.example.com", position=1, vt_hits=0)
    item2 = _make_result("pending.example.com", position=2, vt_hits=0)
    job = _make_job([item1, item2])
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(3)))):
        _run(job_actions._run_items(
            job, [item1], "refresh",
            usage_file=tmp_path / "u.json",
            job_file=job_file,
        ))

    raw = job_file.read_text()
    data = json.loads(raw)
    assert data["results"]["done.example.com"]["vt_hits"] == 3
    assert data["results"]["pending.example.com"]["vt_hits"] == 0
    assert set(data["results"].keys()) == {"done.example.com", "pending.example.com"}


# ── 5. Persist failure logs and continues ─────────────────────────────────────

def test_persist_failure_logs_and_continues(tmp_path, caplog):
    items = [
        _make_result("a.example.com", position=1),
        _make_result("b.example.com", position=2),
    ]
    job = _make_job(items)
    job_file = tmp_path / "mdi_latest_job.json"
    call_count = 0
    real_write = job_persistence.write_latest_job

    async def _fail_once(j, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("disk full")
        await real_write(j, **kwargs)

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(1)))), \
         patch.object(job_persistence, "write_latest_job", new=AsyncMock(side_effect=_fail_once)), \
         caplog.at_level(logging.ERROR):
        stats = _run(job_actions._run_items(
            job, items, "refresh",
            usage_file=tmp_path / "u.json",
            job_file=job_file,
        ))

    assert stats.items_completed == 2
    assert job.results["a.example.com"].vt_hits == 1
    assert job.results["b.example.com"].vt_hits == 1
    assert any("Failed to persist MDI job after action row" in r.message for r in caplog.records)
    assert job_file.exists()
    assert _read_result_field(job_file, "b.example.com", "vt_hits") == 1


# ── 6. Refresh counter consistency ────────────────────────────────────────────

def test_refresh_counter_persisted_per_row_no_double_count(tmp_path):
    items = [
        _make_result("c1.example.com", position=1),
        _make_result("c2.example.com", position=2),
    ]
    job = _make_job(items, vt_refresh_count=5)
    job_file = tmp_path / "mdi_latest_job.json"

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))):
        _run(job_actions._run_items(
            job, items, "refresh",
            usage_file=tmp_path / "u.json",
            job_file=job_file,
        ))

    assert job.vt_refresh_count == 7
    data = json.loads(job_file.read_text())
    assert data["vt_refresh_count"] == 7

    job_store._JOBS.clear()
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1, 2])
    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey", "MDI_LATEST_JOB_FILE": str(job_file)}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))):
        _run(job_actions.run_refresh_action(
            job.job_id, req,
            usage_file=tmp_path / "u2.json",
            job_file=job_file,
        ))

    final = json.loads(job_file.read_text())
    assert final["vt_refresh_count"] == 9


# ── 7. Final cleanup clears action flags ──────────────────────────────────────

def test_final_cleanup_clears_action_in_progress(tmp_path):
    item = _make_result("cleanup.example.com")
    job = _make_job([item])
    register_recovered_job(job)
    job_file = tmp_path / "mdi_latest_job.json"
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(0)))):
        _run(job_actions.run_refresh_action(
            job.job_id, req,
            usage_file=tmp_path / "u.json",
            job_file=job_file,
        ))

    assert job.action_in_progress is False
    data = json.loads(job_file.read_text())
    assert data["action_in_progress"] is False
    assert data["results"]["cleanup.example.com"]["vt_hits"] == 0


# ── 8. MDI-57B all-pending regression ─────────────────────────────────────────

def test_all_pending_refresh_eligibility_unchanged():
    pending = _pending_row("http://p1.example/", position=1)
    clean = _make_result("clean.example.com", position=2)
    job = _make_job([pending, clean])
    sel = job_actions.select_eligible_items(
        job, RefreshScanScope.PENDING, None, "refresh",
    )
    assert len(sel.eligible) == 1
    assert sel.eligible[0].input_normalized == "http://p1.example/"
    assert is_pending_refresh_eligible(sel.eligible[0])


# ── 9. MDI-63 selected-pending regression ─────────────────────────────────────

def test_selected_pending_eligibility_unchanged():
    pending = _pending_row("http://sp.example/", position=1)
    clean = _make_result("clean.example.com", position=2)
    job = _make_job([pending, clean])
    sel = job_actions.select_eligible_items(
        job, RefreshScanScope.SELECTED_PENDING, [1, 2], "refresh",
    )
    assert len(sel.eligible) == 1
    assert sel.skipped_count == 1
    assert sel.skipped_reasons.get("not_pending") == 1


# ── 10. MDI-62 scan completedness regression ──────────────────────────────────

def test_scan_completedness_unchanged(tmp_path):
    item = _make_result(
        "https://mdi62.example.com/",
        position=1,
        input_type=InputType.URL,
        freshness=Freshness.VERY_STALE,
    )
    job = _make_job([item])

    async def _vt_side_effect(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(200, {})
        return _mock_resp(200, _vt_body(malicious=0))

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_vt_side_effect)):
        _run(job_actions._run_items(
            job, [item], "scan",
            usage_file=tmp_path / "u.json",
        ))

    updated = job.results["https://mdi62.example.com/"]
    assert updated.vt_hits == 0
    assert job.vt_scan_requested_count == 1


# ── 11. Stale action sanitize compatibility ─────────────────────────────────────

def test_mid_action_disk_snapshot_sanitized_on_recovery(tmp_path):
    item = _make_result("mid.example.com", position=1, vt_hits=1)
    job = _make_job([item])
    job.action_in_progress = True
    job.last_action_type = "refresh"
    job.vt_refresh_count = 3
    job_file = tmp_path / "mdi_latest_job.json"
    _run(job_persistence.write_latest_job(job, job_file=job_file))

    raw = json.loads(job_file.read_text())
    assert raw["action_in_progress"] is True
    assert raw["vt_refresh_count"] == 3

    recovered = job_persistence.read_latest_job(job_file=job_file)
    assert recovered is not None
    assert recovered.action_in_progress is False
    assert recovered.vt_refresh_count == 3
    assert recovered.results["mid.example.com"].vt_hits == 1
