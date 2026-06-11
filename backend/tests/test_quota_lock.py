"""
MDI-19 shared quota file locking tests.

All tests use tmp_path via conftest isolate_runtime_files (VT_QUOTA_LOCK_FILE redirected).
No live /var/lib/dns-tool/ access. No live VT calls.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from services import dashboard, quota_writer
from services.quota_lock import (
    QuotaLockTimeout,
    default_lock_path,
    ensure_lock_file,
    quota_lock,
)
from services.quota_writer import DAILY_QUOTA, _do_increment_unlocked


# ── Lock helper unit tests ─────────────────────────────────────────────────────

def test_lock_file_created_when_missing(tmp_path, monkeypatch):
    lock_path = tmp_path / "vt_usage.lock"
    monkeypatch.setenv("VT_QUOTA_LOCK_FILE", str(lock_path))
    assert not lock_path.exists()
    ensure_lock_file(lock_path)
    assert lock_path.exists()
    assert oct(lock_path.stat().st_mode & 0o777) == oct(0o660)


def test_shared_lock_allows_concurrent_readers(tmp_path, monkeypatch):
    lock_path = tmp_path / "vt_usage.lock"
    monkeypatch.setenv("VT_QUOTA_LOCK_FILE", str(lock_path))
    with quota_lock("shared"):
        with quota_lock("shared"):
            pass


def test_exclusive_lock_blocks_second_exclusive(tmp_path, monkeypatch):
    lock_path = tmp_path / "vt_usage.lock"
    monkeypatch.setenv("VT_QUOTA_LOCK_FILE", str(lock_path))
    with quota_lock("exclusive"):
        with pytest.raises(QuotaLockTimeout):
            with quota_lock("exclusive", timeout=0.2):
                pass


def test_lock_timeout_raises_without_mutation(tmp_path, monkeypatch):
    usage = tmp_path / "vt_usage.json"
    lock_path = tmp_path / "vt_usage.lock"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage.write_text(json.dumps({"date_utc": today, "daily_lookups_used": 3}))
    monkeypatch.setenv("VT_USAGE_FILE", str(usage))
    monkeypatch.setenv("VT_QUOTA_LOCK_FILE", str(lock_path))

    with quota_lock("exclusive"):
        with pytest.raises(QuotaLockTimeout):
            quota_writer.read_remaining_quota(usage)

    data = json.loads(usage.read_text())
    assert data["daily_lookups_used"] == 3


def test_read_remaining_quota_under_shared_lock(tmp_path, monkeypatch):
    usage = tmp_path / "vt_usage.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage.write_text(json.dumps({"date_utc": today, "daily_lookups_used": 10}))
    monkeypatch.setenv("VT_USAGE_FILE", str(usage))
    remaining = quota_writer.read_remaining_quota(usage)
    assert remaining == DAILY_QUOTA - 10


# ── Multiprocessing concurrency ────────────────────────────────────────────────

def _mp_increment_worker(usage_str: str, lock_str: str, count: int) -> None:
    """Child process: increment usage file count times under flock."""
    os.environ["VT_USAGE_FILE"] = usage_str
    os.environ["VT_QUOTA_LOCK_FILE"] = lock_str
    usage = Path(usage_str)
    for _ in range(count):
        with quota_lock("exclusive"):
            _do_increment_unlocked(usage, 1)


def test_concurrent_multiprocessing_increments_no_lost_updates(tmp_path, monkeypatch):
    usage = tmp_path / "vt_usage.json"
    lock_path = tmp_path / "vt_usage.lock"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage.write_text(json.dumps({"date_utc": today, "daily_lookups_used": 0}))
    lock_path.touch()

    n_procs = 4
    per_proc = 5
    procs = [
        multiprocessing.Process(
            target=_mp_increment_worker,
            args=(str(usage), str(lock_path), per_proc),
        )
        for _ in range(n_procs)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0

    data = json.loads(usage.read_text())
    assert data["daily_lookups_used"] == n_procs * per_proc


def test_quota_hard_stop_at_limit_under_lock(tmp_path, monkeypatch):
    usage = tmp_path / "vt_usage.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage.write_text(json.dumps({"date_utc": today, "daily_lookups_used": DAILY_QUOTA}))
    monkeypatch.setenv("VT_USAGE_FILE", str(usage))
    remaining = quota_writer.read_remaining_quota(usage)
    assert remaining == 0


def test_update_daily_history_under_lock(tmp_path, monkeypatch):
    daily = tmp_path / "vt_daily_history.json"
    monkeypatch.setenv("VT_DAILY_HISTORY_FILE", str(daily))
    quota_writer.update_daily_history(3, daily)
    quota_writer.update_daily_history(2, daily)
    data = json.loads(daily.read_text())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = data[today]
    assert day["total_quota_units"] == 5
    assert day["tools"]["mdi"]["quota_units"] == 5


def test_append_usage_history_valid_jsonl(tmp_path, monkeypatch):
    history = tmp_path / "vt_usage_history.jsonl"
    monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history))
    rec = quota_writer.build_usage_history_record(
        job_id="j1",
        items_attempted=1,
        items_completed=1,
        quota_units_consumed=1,
        quota_blocked_count=0,
        errors_count=0,
        held_skipped_count=0,
        processing_options_summary={},
        status="done",
    )
    quota_writer.append_usage_history(rec, history)
    lines = history.read_text().strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["tool_name"] == "mdi"


def test_dashboard_read_does_not_mutate_runtime(tmp_path, monkeypatch):
    usage = tmp_path / "vt_usage.json"
    history = tmp_path / "vt_usage_history.jsonl"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage.write_text(json.dumps({"date_utc": today, "daily_lookups_used": 0}))
    rec = quota_writer.build_usage_history_record(
        job_id="dash-j",
        items_attempted=1,
        items_completed=1,
        quota_units_consumed=0,
        quota_blocked_count=0,
        errors_count=0,
        held_skipped_count=0,
        processing_options_summary={},
        status="done",
    )
    history.write_text(json.dumps(rec) + "\n")
    monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history))
    monkeypatch.setenv("VT_DAILY_HISTORY_FILE", str(tmp_path / "vt_daily_history.json"))

    usage_mtime_before = usage.stat().st_mtime
    dashboard.build_dashboard_summary()
    assert usage.stat().st_mtime == usage_mtime_before


# ── Cross-service style writer (VT pattern) ───────────────────────────────────

def _vt_style_increment(usage: Path, lock_path: Path) -> None:
    """Mimic VT Bulk Check save under same flock."""
    with quota_lock("exclusive", lock_path=lock_path):
        data = json.loads(usage.read_text())
        data["daily_lookups_used"] = int(data.get("daily_lookups_used", 0)) + 1
        tmp = usage.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, usage)


def _cross_service_worker(usage_str: str, lock_str: str, style: str, count: int) -> None:
    os.environ["VT_USAGE_FILE"] = usage_str
    os.environ["VT_QUOTA_LOCK_FILE"] = lock_str
    usage = Path(usage_str)
    lock_path = Path(lock_str)
    for _ in range(count):
        if style == "mdi":
            with quota_lock("exclusive", lock_path=lock_path):
                _do_increment_unlocked(usage, 1)
        else:
            _vt_style_increment(usage, lock_path)


def test_cross_service_mdi_and_vt_writers(tmp_path):
    usage = tmp_path / "vt_usage.json"
    lock_path = tmp_path / "vt_usage.lock"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage.write_text(json.dumps({"date_utc": today, "daily_lookups_used": 0}))
    lock_path.touch()

    procs = [
        multiprocessing.Process(
            target=_cross_service_worker,
            args=(str(usage), str(lock_path), "mdi", 3),
        ),
        multiprocessing.Process(
            target=_cross_service_worker,
            args=(str(usage), str(lock_path), "vt", 4),
        ),
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0

    data = json.loads(usage.read_text())
    assert data["daily_lookups_used"] == 7


# ── Job path integration with mocks ───────────────────────────────────────────

def test_sequential_mdi_then_vt_style_increment(tmp_path, monkeypatch):
    """MDI increment then VT-style increment on same day reaches 2."""
    usage = tmp_path / "vt_usage.json"
    lock_path = tmp_path / "vt_usage.lock"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage.write_text(json.dumps({"date_utc": today, "daily_lookups_used": 0}))
    lock_path.touch()
    monkeypatch.setenv("VT_USAGE_FILE", str(usage))
    monkeypatch.setenv("VT_QUOTA_LOCK_FILE", str(lock_path))

    with quota_lock("exclusive", lock_path=lock_path):
        _do_increment_unlocked(usage, 1)
    _vt_style_increment(usage, lock_path)

    assert json.loads(usage.read_text())["daily_lookups_used"] == 2


def test_sequential_vt_then_mdi_increment(tmp_path, monkeypatch):
    """VT-style increment then MDI increment on same day reaches 2."""
    usage = tmp_path / "vt_usage.json"
    lock_path = tmp_path / "vt_usage.lock"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage.write_text(json.dumps({"date_utc": today, "daily_lookups_used": 0}))
    lock_path.touch()
    monkeypatch.setenv("VT_USAGE_FILE", str(usage))
    monkeypatch.setenv("VT_QUOTA_LOCK_FILE", str(lock_path))

    _vt_style_increment(usage, lock_path)
    with quota_lock("exclusive", lock_path=lock_path):
        _do_increment_unlocked(usage, 1)

    assert json.loads(usage.read_text())["daily_lookups_used"] == 2


def test_mdi_increment_after_external_vt_write_not_lost(tmp_path, monkeypatch):
    """MDI must not overwrite a newer VT-style counter with stale reads."""
    usage = tmp_path / "vt_usage.json"
    lock_path = tmp_path / "vt_usage.lock"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage.write_text(json.dumps({"date_utc": today, "daily_lookups_used": 0}))
    lock_path.touch()
    monkeypatch.setenv("VT_USAGE_FILE", str(usage))
    monkeypatch.setenv("VT_QUOTA_LOCK_FILE", str(lock_path))

    _vt_style_increment(usage, lock_path)
    import asyncio
    asyncio.run(quota_writer.increment_quota(1, usage))

    assert json.loads(usage.read_text())["daily_lookups_used"] == 2


def test_async_increment_quota_under_lock(tmp_path, monkeypatch):
    """increment_quota uses exclusive flock and updates counter."""
    import asyncio

    usage = tmp_path / "vt_usage.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage.write_text(json.dumps({"date_utc": today, "daily_lookups_used": 0}))
    monkeypatch.setenv("VT_USAGE_FILE", str(usage))
    asyncio.run(quota_writer.increment_quota(2, usage))
    data = json.loads(usage.read_text())
    assert data["daily_lookups_used"] == 2


def test_auto_rescan_skips_on_lock_timeout_before_vt(tmp_path, monkeypatch):
    """Auto-rescan does not call VT when quota read hits lock timeout."""
    import asyncio

    from models import InputType, MdiProcessingStatus, MdiResultItem
    from services import auto_rescan, job_store

    job = job_store.InMemoryJob(
        job_id="lock-ar",
        status="running",
        submitted_at=time.time(),
        total=1,
        item_order=["stale.com"],
        auto_rescan_stale=True,
        max_auto_rescans=5,
        use_domain_reports=False,
        stale_threshold_days=7,
    )
    job.results["stale.com"] = MdiResultItem(
        input_original="stale.com",
        input_normalized="stale.com",
        input_type=InputType.DOMAIN,
        position=1,
        processing_status=MdiProcessingStatus.DONE,
    )

    mock_vt = AsyncMock()
    with patch("services.auto_rescan.read_remaining_quota", side_effect=QuotaLockTimeout()), \
         patch("services.auto_rescan.vt_service.request_new_scan", mock_vt):
        asyncio.run(auto_rescan.maybe_auto_rescan_item(job, "stale.com"))

    mock_vt.assert_not_called()
    err_codes = [e.code for e in job.results["stale.com"].errors or []]
    assert "quota_lock_timeout" in err_codes


def test_conftest_redirects_lock_file(tmp_path, monkeypatch):
    """conftest sets VT_QUOTA_LOCK_FILE to tmp_path."""
    assert default_lock_path() == tmp_path / "vt_usage.lock"
