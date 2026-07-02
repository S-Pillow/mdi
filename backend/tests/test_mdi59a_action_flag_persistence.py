"""
MDI-59A — action_in_progress persistence and recovery hardening tests.

Guarantees:
  - All file I/O uses tmp_path / MDI_LATEST_JOB_FILE injection.
  - No /var/lib/dns-tool access.
  - No VT quota consumed (VT HTTP mocked).
  - No external API calls.
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

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    AgeBucket,
    Freshness,
    InputType,
    JobActionRequest,
    LiveStatus,
    MdiProcessingStatus,
    MdiResultItem,
    RefreshScanScope,
    TriageBucket,
)
from services import job_actions, job_persistence, job_store
from services.job_store import InMemoryJob, clear_all_jobs, register_recovered_job
from services.live_check import LiveCheckResult


def _run(coro):
    return asyncio.run(coro)


def _mock_resp(status_code: int, body: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    return m


def _vt_body(malicious=0, suspicious=0, age_days=1):
    scan_ts = int(time.time()) - (age_days * 86400)
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
                "last_analysis_date": scan_ts,
            }
        }
    }


def _make_result(
    normalized: str,
    *,
    position: int = 1,
    freshness=Freshness.STALE,
    vt_hits: int = 1,
    age_days: int = 10,
) -> MdiResultItem:
    return MdiResultItem(
        input_original=normalized,
        input_normalized=normalized,
        input_type=InputType.DOMAIN,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        vt_hits=vt_hits,
        vt_suspicious=0,
        vt_total_engines=75,
        vt_ratio=f"{vt_hits}/75",
        freshness=freshness,
        age_bucket=AgeBucket.MATURE,
        triage_bucket=TriageBucket.MALICIOUS if vt_hits else TriageBucket.CLEAN,
    )


def _make_done_job(
    items: list[MdiResultItem],
    *,
    job_id: str = "mdi59a-job",
) -> InMemoryJob:
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


def _persisted_flag(job_file: Path) -> bool:
    data = json.loads(job_file.read_text())
    return bool(data.get("action_in_progress", False))


def _no_limiter():
    import services.vt_service as vt_svc

    return patch.object(vt_svc._VT_LIMITER, "acquire", new=AsyncMock())


@pytest.fixture(autouse=True)
def isolate():
    clear_all_jobs()
    old = os.environ.pop("MDI_LATEST_JOB_FILE", None)
    yield
    clear_all_jobs()
    if old is None:
        os.environ.pop("MDI_LATEST_JOB_FILE", None)
    else:
        os.environ["MDI_LATEST_JOB_FILE"] = old


def test_refresh_action_success_persists_cleared_flag(tmp_path):
    item = _make_result("refresh-ok.example")
    job = _make_done_job([item])
    register_recovered_job(job)
    job_file = tmp_path / "mdi_latest_job.json"
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(200, _vt_body(1)))), \
         patch("services.live_check.live_check_item", new=AsyncMock(return_value=LiveCheckResult(
             live_status=LiveStatus.NOT_CHECKED))):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=job_file,
        ))

    assert job.action_in_progress is False
    assert job.last_action_type == "refresh"
    assert job_file.exists()
    assert _persisted_flag(job_file) is False


def test_refresh_action_failure_persists_cleared_flag(tmp_path):
    item = _make_result("refresh-fail.example", vt_hits=3)
    job = _make_done_job([item])
    register_recovered_job(job)
    job_file = tmp_path / "mdi_latest_job.json"
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(500))):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=job_file,
        ))

    assert job.action_in_progress is False
    assert job_file.exists()
    assert _persisted_flag(job_file) is False
    updated = job.results["refresh-fail.example"]
    assert updated.vt_hits == 3
    assert any(e.code == "vt_server_error" for e in (updated.errors or []))


def test_scan_action_success_persists_cleared_flag(tmp_path):
    item = _make_result("scan-ok.example")
    job = _make_done_job([item])
    register_recovered_job(job)
    job_file = tmp_path / "mdi_latest_job.json"
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])

    async def _vt_side_effect(method, url, **kwargs):
        if method == "POST":
            return _mock_resp(200, {})
        return _mock_resp(200, _vt_body(malicious=2))

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(side_effect=_vt_side_effect)), \
         patch("services.live_check.live_check_item", new=AsyncMock(return_value=LiveCheckResult(
             live_status=LiveStatus.NOT_CHECKED))):
        _run(job_actions.run_scan_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=job_file,
        ))

    assert job.action_in_progress is False
    assert job.last_action_type == "scan"
    assert job_file.exists()
    assert _persisted_flag(job_file) is False


def test_scan_action_failure_persists_cleared_flag(tmp_path):
    item = _make_result("scan-fail.example")
    job = _make_done_job([item])
    register_recovered_job(job)
    job_file = tmp_path / "mdi_latest_job.json"
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])

    with _no_limiter(), patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("services.vt_service._vt_request", new=AsyncMock(return_value=_mock_resp(400))):
        _run(job_actions.run_scan_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=job_file,
        ))

    assert job.action_in_progress is False
    assert job_file.exists()
    assert _persisted_flag(job_file) is False
    assert any(
        e.code == "vt_submit_error"
        for e in (job.results["scan-fail.example"].errors or [])
    )


def test_recovery_hardening_clears_stale_terminal_flag(tmp_path):
    item = _make_result("stale-flag.example")
    job = _make_done_job([item], job_id="stale-recover-job")
    job.action_in_progress = True
    job.last_action_type = "refresh"
    job_file = tmp_path / "mdi_latest_job.json"
    _run(job_persistence.write_latest_job(job, job_file=job_file))

    raw = json.loads(job_file.read_text())
    assert raw["action_in_progress"] is True

    recovered = job_persistence.read_latest_job(job_file=job_file)
    assert recovered is not None
    assert recovered.status == "done"
    assert recovered.action_in_progress is False
    assert recovered.last_action_type == "refresh"


def test_recovery_hardening_running_job_keeps_flag(tmp_path):
    job = _make_done_job([_make_result("active.example")], job_id="running-job")
    job.status = "running"
    job.action_in_progress = True
    job.completed_at = None
    data = job_persistence.serialize_job(job)
    job_file = tmp_path / "mdi_latest_job.json"
    job_file.write_text(json.dumps(data))

    recovered = job_persistence.read_latest_job(job_file=job_file)
    assert recovered is not None
    assert recovered.status == "running"
    assert recovered.action_in_progress is True


def test_recovery_hardening_queued_job_keeps_flag(tmp_path):
    job = _make_done_job([_make_result("queued.example")], job_id="queued-job")
    job.status = "queued"
    job.action_in_progress = True
    job.completed_at = None
    data = job_persistence.serialize_job(job)
    job_file = tmp_path / "mdi_latest_job.json"
    job_file.write_text(json.dumps(data))

    recovered = job_persistence.read_latest_job(job_file=job_file)
    assert recovered is not None
    assert recovered.status == "queued"
    assert recovered.action_in_progress is True


def test_sanitize_terminal_action_state_in_memory_only():
    job = _make_done_job([_make_result("mem.example")])
    job.action_in_progress = True
    sanitized = job_persistence.sanitize_terminal_action_state(job)
    assert sanitized.action_in_progress is False

    running = _make_done_job([_make_result("run.example")], job_id="run-2")
    running.status = "running"
    running.action_in_progress = True
    unchanged = job_persistence.sanitize_terminal_action_state(running)
    assert unchanged.action_in_progress is True
