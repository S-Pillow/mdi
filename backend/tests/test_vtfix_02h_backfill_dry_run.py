"""
VTFIX-02H — daily-history backfill dry-run tests (temp/local files only).
"""

from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "vtfix-02h-daily-history-backfill-dry-run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("vtfix_02h_dry_run", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dry_run():
    return _load_module()


class TestJsonlAggregation:
    def test_tool_name_mdi_attribution(self, dry_run, tmp_path):
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text(
            json.dumps(
                {
                    "timestamp": "2026-06-11T10:00:00Z",
                    "tool_name": "mdi",
                    "quota_units_consumed": 2,
                    "job_id": "j1",
                    "status": "done",
                }
            )
            + "\n"
        )
        by_date, meta = dry_run.aggregate_jsonl(jsonl)
        assert by_date["2026-06-11"]["mdi"] == 2
        assert meta["tool_name"] == 1

    def test_tool_name_vt_bulk_attribution(self, dry_run, tmp_path):
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text(
            json.dumps(
                {
                    "timestamp": "2026-06-11T10:00:00Z",
                    "tool_name": "vt_bulk_check",
                    "quota_units_consumed": 3,
                    "job_id": "j2",
                    "status": "done",
                }
            )
            + "\n"
        )
        by_date, _ = dry_run.aggregate_jsonl(jsonl)
        assert by_date["2026-06-11"]["vt_bulk_check"] == 3

    def test_missing_tool_name_becomes_legacy(self, dry_run, tmp_path):
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text(
            json.dumps({"actual_lookups": 4, "job_id": "j3", "status": "done"}) + "\n"
        )
        by_date, meta = dry_run.aggregate_jsonl(jsonl)
        assert by_date["unknown"]["legacy"] == 4
        assert meta["legacy_or_missing_tool_lines"] == 1


class TestBackfillPlan:
    def test_legacy_integer_normalization(self, dry_run, tmp_path):
        daily = tmp_path / "vt_daily_history.json"
        daily.write_text(json.dumps({"2026-06-10": 242}))
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text("")
        result = dry_run.build_plan(daily, jsonl)
        row = result["plans"][0]
        assert row["current_shape"] == "legacy_int"
        assert row["proposed_total"] == 242
        assert row["proposed_legacy"] == 242
        assert row["proposed_mdi"] == 0
        assert row["confidence"] == "high"
        assert row["write_recommended"] is True

    def test_legacy_dict_mdi_normalization(self, dry_run, tmp_path):
        daily = tmp_path / "vt_daily_history.json"
        daily.write_text(json.dumps({"2026-06-09": {"quota_units": 4, "tool": "mdi"}}))
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text("")
        row = dry_run.build_plan(daily, jsonl)["plans"][0]
        assert row["proposed_mdi"] == 4
        assert row["proposed_legacy"] == 0
        assert row["confidence"] == "high"

    def test_v2_day_preserved_no_write(self, dry_run, tmp_path):
        daily = tmp_path / "vt_daily_history.json"
        daily.write_text(
            json.dumps(
                {
                    "2026-06-11": {
                        "schema_version": 2,
                        "total_quota_units": 4,
                        "tools": {
                            "mdi": {"quota_units": 2, "jobs": 1, "items_processed": 1},
                            "vt_bulk_check": {"quota_units": 2, "jobs": 1, "items_processed": 1},
                        },
                    }
                }
            )
        )
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text(
            json.dumps(
                {"timestamp": "2026-06-11T09:00:00Z", "tool_name": "mdi", "quota_units_consumed": 2}
            )
            + "\n"
            + json.dumps(
                {
                    "timestamp": "2026-06-11T09:05:00Z",
                    "tool_name": "vt_bulk_check",
                    "quota_units_consumed": 2,
                }
            )
            + "\n"
        )
        row = dry_run.build_plan(daily, jsonl)["plans"][0]
        assert row["current_shape"] == "v2_tools"
        assert row["write_recommended"] is False

    def test_conflicting_totals_manual_review(self, dry_run, tmp_path):
        daily = tmp_path / "vt_daily_history.json"
        daily.write_text(json.dumps({"2026-06-07": 5}))
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text(
            json.dumps(
                {
                    "timestamp": "2026-06-07T12:00:00Z",
                    "tool_name": "mdi",
                    "quota_units_consumed": 3,
                    "job_id": "x",
                    "status": "done",
                }
            )
            + "\n"
        )
        row = dry_run.build_plan(daily, jsonl)["plans"][0]
        assert row["confidence"] == "manual_review"
        assert row["write_recommended"] is False

    def test_default_dry_run_refuses_write_flag(self, dry_run):
        assert dry_run.main(["--write"]) == 2


class TestNoRuntimeWrite:
    def test_script_has_no_runtime_write_path(self):
        text = _SCRIPT.read_text()
        assert "save_history_file" not in text
        assert "os.replace" not in text
