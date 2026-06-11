"""
VTFIX-02H — daily-history backfill dry-run and approved write tests (temp files only).
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


def _production_fixture_daily(tmp_path: Path) -> Path:
    """Mirror production shape for approved-write tests."""
    daily = tmp_path / "vt_daily_history.json"
    daily.write_text(
        json.dumps(
            {
                "2026-06-03": 138,
                "2026-06-05": 1,
                "2026-06-06": {"quota_units": 1478, "tool": "mdi"},
                "2026-06-07": 5,
                "2026-06-08": {"quota_units": 89, "tool": "mdi"},
                "2026-06-09": {"quota_units": 4, "tool": "mdi"},
                "2026-06-10": 242,
                "2026-06-11": {
                    "schema_version": 2,
                    "total_quota_units": 4,
                    "tools": {
                        "mdi": {"quota_units": 2, "jobs": 1, "items_processed": 1},
                        "vt_bulk_check": {"quota_units": 2, "jobs": 1, "items_processed": 1},
                    },
                },
            },
            indent=2,
        )
    )
    return daily


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


class TestApprovedWriteMode:
    def test_five_date_normalization_succeeds(self, dry_run, tmp_path):
        daily = _production_fixture_daily(tmp_path)
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text("")
        result = dry_run.execute_approved_normalization(daily, jsonl)
        assert result["status"] == "written"
        assert set(result["dates_written"]) == set(dry_run.APPROVED_WRITE_DATES.keys())
        loaded = json.loads(daily.read_text())
        assert loaded["2026-06-05"]["schema_version"] == 2
        assert loaded["2026-06-06"]["tools"]["mdi"]["quota_units"] == 1478
        assert loaded["2026-06-10"]["tools"]["legacy"]["quota_units"] == 242

    def test_manual_review_dates_preserved(self, dry_run, tmp_path):
        daily = _production_fixture_daily(tmp_path)
        before = json.loads(daily.read_text())
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text("")
        dry_run.execute_approved_normalization(daily, jsonl)
        after = json.loads(daily.read_text())
        assert after["2026-06-03"] == before["2026-06-03"]
        assert after["2026-06-07"] == before["2026-06-07"]

    def test_existing_v2_date_preserved(self, dry_run, tmp_path):
        daily = _production_fixture_daily(tmp_path)
        before_v2 = json.loads(daily.read_text())["2026-06-11"]
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text("")
        dry_run.execute_approved_normalization(daily, jsonl)
        after_v2 = json.loads(daily.read_text())["2026-06-11"]
        assert after_v2 == before_v2

    def test_totals_preserved(self, dry_run, tmp_path):
        daily = _production_fixture_daily(tmp_path)
        before = json.loads(daily.read_text())
        totals_before = {d: dry_run.current_day_total(v) for d, v in before.items()}
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text("")
        result = dry_run.execute_approved_normalization(daily, jsonl)
        assert result["totals_before"] == result["totals_after"] == totals_before

    def test_unexpected_totals_refused(self, dry_run, tmp_path):
        daily = _production_fixture_daily(tmp_path)
        data = json.loads(daily.read_text())
        data["2026-06-05"] = 99
        daily.write_text(json.dumps(data))
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text("")
        with pytest.raises(RuntimeError, match="validation failed"):
            dry_run.execute_approved_normalization(daily, jsonl)

    def test_missing_approved_date_refused(self, dry_run, tmp_path):
        daily = _production_fixture_daily(tmp_path)
        data = json.loads(daily.read_text())
        del data["2026-06-10"]
        daily.write_text(json.dumps(data))
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text("")
        with pytest.raises(RuntimeError, match="validation failed"):
            dry_run.execute_approved_normalization(daily, jsonl)

    def test_write_mode_creates_backup(self, dry_run, tmp_path):
        daily = _production_fixture_daily(tmp_path)
        jsonl = tmp_path / "history.jsonl"
        jsonl.write_text("")
        result = dry_run.execute_approved_normalization(daily, jsonl)
        backup = Path(result["backup_path"])
        assert backup.exists()
        assert backup.read_text() != daily.read_text() or json.loads(backup.read_text())["2026-06-05"] == 1

    def test_default_mode_remains_dry_run(self, dry_run, tmp_path):
        daily = _production_fixture_daily(tmp_path)
        mtime_before = daily.stat().st_mtime
        dry_run.main(["--daily-file", str(daily), "--jsonl-file", str(tmp_path / "x.jsonl")])
        assert daily.stat().st_mtime == mtime_before

    def test_production_path_required_in_write_main(self, dry_run, tmp_path):
        daily = _production_fixture_daily(tmp_path)
        rc = dry_run.main(
            [
                "--write-approved-normalization",
                "--daily-file",
                str(daily),
                "--jsonl-file",
                str(tmp_path / "history.jsonl"),
            ]
        )
        assert rc == 2
