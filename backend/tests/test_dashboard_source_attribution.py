"""
VTFIX-02C — Dashboard shared VT usage source attribution tests.

Uses temp JSONL fixtures only; never touches /var/lib/dns-tool runtime files.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from main import app
from services import dashboard

client = TestClient(app)


def _iso_days_ago(days: int) -> str:
    ts = datetime.now(timezone.utc) - timedelta(days=days)
    return ts.isoformat()


def _mdi_line(**overrides) -> str:
    base = {
        "timestamp": _iso_days_ago(1),
        "tool_name": "mdi",
        "job_id": "mdi-job-1",
        "operation": "report_lookup",
        "items_attempted": 10,
        "items_completed": 10,
        "quota_units_consumed": 5,
        "status": "done",
        "job_duration_seconds": 12.0,
        "flagged_count": 1,
        "clean_count": 9,
        "triage_bucket_counts": {"clean": 9, "malicious": 1},
    }
    base.update(overrides)
    return json.dumps(base)


def _vt_bulk_line(**overrides) -> str:
    base = {
        "tool_name": "vt_bulk_check",
        "timestamp": _iso_days_ago(1),
        "job_id": "bulk-job-1",
        "status": "done",
        "quota_units_consumed": 221,
        "processed": 221,
        "total": 221,
        "actual_lookups": 221,
        "submitted_at": 1_700_000_000.0,
        "completed_at": 1_700_000_100.0,
    }
    base.update(overrides)
    return json.dumps(base)


def _legacy_line(**overrides) -> str:
    base = {
        "ts": (datetime.now(timezone.utc) - timedelta(days=1)).timestamp(),
        "job_id": "legacy-job-1",
        "status": "done",
        "actual_lookups": 50,
        "processed": 50,
        "total": 50,
        "submitted_at": 1_700_000_000.0,
        "completed_at": 1_700_000_050.0,
    }
    base.update(overrides)
    return json.dumps(base)


@pytest.fixture
def history_file(tmp_path: Path) -> Path:
    return tmp_path / "vt_usage_history.jsonl"


class TestNormalizeUsageHistoryRecord:
    def test_mdi_record(self):
        raw = json.loads(_mdi_line())
        norm = dashboard.normalize_usage_history_record(raw)
        assert norm["source_tool"] == "mdi"
        assert norm["source_label"] == "MDI"
        assert norm["quota_units_consumed"] == 5
        assert norm["job_id"] == "mdi-job-1"
        assert norm["status"] == "done"
        assert norm["timestamp"] is not None

    def test_vt_bulk_check_record(self):
        raw = json.loads(_vt_bulk_line())
        norm = dashboard.normalize_usage_history_record(raw)
        assert norm["source_tool"] == "vt_bulk_check"
        assert norm["source_label"] == "VT Bulk Check"
        assert norm["quota_units_consumed"] == 221
        assert norm["operation"] == "report_lookup"
        assert norm["items_completed"] == 221
        assert norm["job_duration_seconds"] == 100.0

    def test_legacy_untagged_record(self):
        raw = json.loads(_legacy_line())
        norm = dashboard.normalize_usage_history_record(raw)
        assert norm["source_tool"] == "legacy"
        assert norm["source_label"] == "Legacy / Unattributed"
        assert norm["quota_units_consumed"] == 50
        assert norm["operation"] == "report_lookup"
        assert norm["timestamp"] is not None

    def test_malformed_line_skipped_by_parser(self):
        assert dashboard.parse_history_line("{bad json") is None


class TestFilterBySource:
    def test_filters(self):
        records = [
            dashboard.normalize_usage_history_record(json.loads(_mdi_line())),
            dashboard.normalize_usage_history_record(json.loads(_vt_bulk_line())),
            dashboard.normalize_usage_history_record(json.loads(_legacy_line())),
        ]
        assert len(dashboard.filter_by_source(records, "mdi")) == 1
        assert len(dashboard.filter_by_source(records, "vt_bulk_check")) == 1
        assert len(dashboard.filter_by_source(records, "all")) == 3


class TestDashboardSourceFilterApi:
    def test_default_mdi_only(self, history_file, monkeypatch):
        history_file.write_text(
            "\n".join([_mdi_line(), _vt_bulk_line(), _legacy_line()]) + "\n"
        )
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        data = client.get("/api/mdi/dashboard").json()
        assert data["source_filter"] == "mdi"
        assert data["windows"]["all_time"]["jobs_run"] == 1
        assert data["data_quality"]["records_non_mdi_skipped"] == 2

    def test_vt_bulk_check_only(self, history_file, monkeypatch):
        history_file.write_text(
            "\n".join([_mdi_line(), _vt_bulk_line(), _legacy_line()]) + "\n"
        )
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        data = client.get("/api/mdi/dashboard?source=vt_bulk_check").json()
        assert data["source_filter"] == "vt_bulk_check"
        assert data["windows"]["all_time"]["jobs_run"] == 1
        assert data["windows"]["all_time"]["quota_units_consumed"] == 221

    def test_all_vt_tools_includes_legacy_labeled(self, history_file, monkeypatch):
        history_file.write_text(
            "\n".join([_mdi_line(), _vt_bulk_line(), _legacy_line()]) + "\n"
        )
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        data = client.get("/api/mdi/dashboard?source=all").json()
        assert data["source_filter"] == "all"
        assert data["windows"]["all_time"]["jobs_run"] == 3
        assert data["data_quality"]["records_by_source"]["legacy"] == 1
        assert any("Legacy / Unattributed" in n for n in data["data_quality"]["notes"])

    def test_legacy_not_counted_as_mdi(self, history_file, monkeypatch):
        history_file.write_text(_legacy_line() + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        mdi_data = client.get("/api/mdi/dashboard?source=mdi").json()
        all_data = client.get("/api/mdi/dashboard?source=all").json()
        assert mdi_data["windows"]["all_time"]["jobs_run"] == 0
        assert all_data["windows"]["all_time"]["jobs_run"] == 1
        assert all_data["windows"]["all_time"]["quota_units_consumed"] == 50

    def test_malformed_line_skipped(self, history_file, monkeypatch):
        history_file.write_text(_mdi_line() + "\n{bad\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        data = client.get("/api/mdi/dashboard?source=all").json()
        assert data["data_quality"]["records_skipped"] == 1
        assert data["windows"]["all_time"]["jobs_run"] == 1


class TestDashboardMetricOwnership:
    def test_vt_bulk_does_not_alter_mdi_triage_under_all(self, history_file, monkeypatch):
        bulk_with_fake_triage = _vt_bulk_line(
            flagged_count=999,
            clean_count=999,
            triage_bucket_counts={"malicious": 999},
            live_check_count=888,
            rdap_enriched_count=777,
            auto_rescan_attempted_count=666,
        )
        history_file.write_text("\n".join([_mdi_line(), bulk_with_fake_triage]) + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        win = client.get("/api/mdi/dashboard?source=all").json()["windows"]["all_time"]
        assert win["jobs_run"] == 2
        assert win["quota_units_consumed"] == 5 + 221
        assert win["items_completed"] == 10 + 221
        assert win["triage_metrics_applicable"] is True
        assert win["triage_metrics_label"] == "MDI only"
        assert win["flagged_count"] == 1
        assert win["clean_count"] == 9
        assert win["live_check_count"] == 0
        assert win["rdap_enriched_count"] == 0
        assert win["auto_rescan_attempted_count"] == 0

    def test_all_shared_cards_include_vt_bulk(self, history_file, monkeypatch):
        history_file.write_text("\n".join([_mdi_line(), _vt_bulk_line()]) + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        win = client.get("/api/mdi/dashboard?source=all").json()["windows"]["all_time"]
        assert win["jobs_run"] == 2
        assert win["quota_units_consumed"] == 226
        assert win["items_completed"] == 231
        assert win["avg_items_per_job"] == round(231 / 2, 2)

    def test_vt_bulk_only_hides_mdi_triage(self, history_file, monkeypatch):
        history_file.write_text(
            "\n".join([_mdi_line(), _vt_bulk_line(flagged_count=50)]) + "\n"
        )
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        win = client.get("/api/mdi/dashboard?source=vt_bulk_check").json()["windows"]["all_time"]
        assert win["jobs_run"] == 1
        assert win["quota_units_consumed"] == 221
        assert win["triage_metrics_applicable"] is False
        assert win["flagged_percent"] is None
        assert win["live_check_count"] is None
        assert win["triage_bucket_counts"] is None

    def test_legacy_not_in_mdi_triage_percentages(self, history_file, monkeypatch):
        legacy_with_triage = _legacy_line(
            flagged_count=100,
            clean_count=100,
            triage_bucket_counts={"malicious": 100},
        )
        history_file.write_text("\n".join([_mdi_line(), legacy_with_triage]) + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        win = client.get("/api/mdi/dashboard?source=all").json()["windows"]["all_time"]
        assert win["jobs_run"] == 2
        assert win["flagged_count"] == 1
        assert win["clean_count"] == 9

    def test_mdi_only_triage_under_mdi_filter(self, history_file, monkeypatch):
        history_file.write_text(
            "\n".join([_mdi_line(), _vt_bulk_line(flagged_count=999)]) + "\n"
        )
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        win = client.get("/api/mdi/dashboard?source=mdi").json()["windows"]["all_time"]
        assert win["jobs_run"] == 1
        assert win["flagged_count"] == 1
        assert win["triage_metrics_applicable"] is True
        assert win.get("triage_metrics_label") is None
