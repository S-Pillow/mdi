"""
VTFIX-02D — Unified daily history schema tests (temp files only).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import daily_history, dashboard, quota_writer


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class TestDailyHistoryNormalization:
    def test_empty_file_initializes_on_write(self, tmp_path):
        path = tmp_path / "vt_daily_history.json"
        data: dict = {}
        daily_history.record_tool_usage(data, _today(), "mdi", quota_delta=2, jobs_delta=1, items_delta=5)
        daily_history.save_history_file(path, data)
        loaded = json.loads(path.read_text())
        day = loaded[_today()]
        assert day["schema_version"] == 2
        assert day["total_quota_units"] == 2
        assert day["tools"]["mdi"]["quota_units"] == 2
        assert day["tools"]["mdi"]["jobs"] == 1
        assert day["tools"]["mdi"]["items_processed"] == 5

    def test_legacy_integer_normalizes_to_legacy_bucket(self):
        entry = daily_history.normalize_day_entry(42)
        assert entry["total_quota_units"] == 42
        assert entry["tools"]["legacy"]["quota_units"] == 42
        assert "mdi" not in entry["tools"]

    def test_legacy_mdi_dict_normalizes(self):
        entry = daily_history.normalize_day_entry({"quota_units": 7, "tool": "mdi"})
        assert entry["tools"]["mdi"]["quota_units"] == 7
        assert entry["total_quota_units"] == 7

    def test_corrupt_file_loads_empty(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        assert daily_history.load_history_file(path) == {}


class TestDailyHistoryWrites:
    def test_mdi_write_increments_mdi_only(self, tmp_path, monkeypatch):
        path = tmp_path / "vt_daily_history.json"
        monkeypatch.setenv("VT_DAILY_HISTORY_FILE", str(path))
        quota_writer.update_daily_history(4, path, items_processed=10)
        day = json.loads(path.read_text())[_today()]
        assert day["tools"]["mdi"]["quota_units"] == 4
        assert day["tools"]["mdi"]["items_processed"] == 10
        assert day["total_quota_units"] == 4

    def test_vt_bulk_write_does_not_overwrite_mdi(self, tmp_path):
        path = tmp_path / "vt_daily_history.json"
        data: dict = {}
        daily_history.record_tool_usage(data, _today(), "mdi", quota_delta=3, jobs_delta=1, items_delta=8)
        daily_history.record_tool_usage(data, _today(), "vt_bulk_check", quota_delta=5, jobs_delta=1, items_delta=20)
        daily_history.save_history_file(path, data)
        day = json.loads(path.read_text())[_today()]
        assert day["tools"]["mdi"]["quota_units"] == 3
        assert day["tools"]["vt_bulk_check"]["quota_units"] == 5
        assert day["total_quota_units"] == 8

    def test_same_day_both_tools_additive(self, tmp_path):
        path = tmp_path / "vt_daily_history.json"
        data = {_today(): 100}
        daily_history.record_tool_usage(data, _today(), "mdi", quota_delta=2, jobs_delta=1, items_delta=4)
        daily_history.record_tool_usage(data, _today(), "vt_bulk_check", quota_delta=1, jobs_delta=1, items_delta=2)
        daily_history.save_history_file(path, data)
        day = json.loads(path.read_text())[_today()]
        assert day["tools"]["legacy"]["quota_units"] == 100
        assert day["tools"]["mdi"]["quota_units"] == 2
        assert day["tools"]["vt_bulk_check"]["quota_units"] == 1
        assert day["total_quota_units"] == 103


class TestDashboardReader:
    def test_mixed_legacy_and_unified_shapes(self, tmp_path, monkeypatch):
        path = tmp_path / "vt_daily_history.json"
        today = _today()
        path.write_text(
            json.dumps(
                {
                    "2020-01-01": 10,
                    "2020-01-02": {"quota_units": 5, "tool": "mdi"},
                    today: {
                        "schema_version": 2,
                        "total_quota_units": 9,
                        "tools": {
                            "mdi": {"quota_units": 4, "jobs": 1, "items_processed": 4},
                            "vt_bulk_check": {"quota_units": 5, "jobs": 1, "items_processed": 5},
                        },
                    },
                }
            )
        )
        monkeypatch.setenv("VT_DAILY_HISTORY_FILE", str(path))
        trend = dashboard.build_quota_trend(path, days=1)
        assert trend["available"] is True
        row = trend["last_7_days"][-1]
        assert row["quota_units"] == 9
        assert row["mdi_quota_units"] == 4
        assert row["vt_bulk_check_quota_units"] == 5
        assert row["legacy_quota_units"] == 0
        assert row["schema_version"] == 2
