"""
MDI-17 — Operational dashboard tests.

Read-only dashboard; no VT/RDAP/live calls; runtime isolated via conftest.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from main import app
from models import (
    AgeBucket,
    DomainHold,
    DomainHoldType,
    DomainStatusSource,
    Freshness,
    InputType,
    LiveStatus,
    MdiProcessingStatus,
    MdiResultItem,
    TriageBucket,
)
from services import dashboard, job_processor, quota_writer
from services.job_store import InMemoryJob, clear_all_jobs

client = TestClient(app)

MALICIOUS_DOMAIN = "super-evil-malware.example"
MALICIOUS_URL = "https://phish-login.example/path"


def _iso_days_ago(days: int) -> str:
    ts = datetime.now(timezone.utc) - timedelta(days=days)
    return ts.isoformat()


def _history_line(**overrides) -> str:
    base = {
        "timestamp": _iso_days_ago(1),
        "tool_name": "mdi",
        "job_id": "job-1",
        "operation": "report_lookup",
        "items_attempted": 10,
        "items_completed": 10,
        "quota_units_consumed": 5,
        "quota_blocked_count": 0,
        "errors_count": 1,
        "held_skipped_count": 2,
        "status": "done",
        "rdap_enriched_count": 3,
        "rdap_failed_count": 1,
        "whois_fallback_count": 1,
        "live_check_count": 4,
        "live_check_skipped_count": 1,
        "live_check_error_count": 1,
        "refresh_count": 0,
        "scan_requested_count": 0,
        "scan_completed_count": 0,
        "scan_failed_count": 0,
        "auto_rescan_attempted_count": 1,
        "auto_rescan_completed_count": 1,
        "auto_rescan_failed_count": 0,
        "auto_rescan_skipped_count": 0,
        "auto_rescan_quota_blocked_count": 0,
        "flagged_count": 2,
        "clean_count": 7,
        "unknown_count": 0,
        "error_item_count": 1,
        "held_count": 2,
        "triage_bucket_counts": {"clean": 7, "malicious": 2, "held": 2},
        "job_duration_seconds": 12.5,
        "error_code_counts": {"vt_429": 1},
    }
    base.update(overrides)
    return json.dumps(base)


def _make_result(normalized: str, *, bucket=TriageBucket.CLEAN, position=1):
    return MdiResultItem(
        input_original=normalized,
        input_normalized=normalized,
        input_type=InputType.DOMAIN,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        triage_bucket=bucket,
        freshness=Freshness.FRESH,
        age_bucket=AgeBucket.MATURE,
        live_status=LiveStatus.NOT_CHECKED,
    )


def _make_job(items: list[MdiResultItem], **kwargs) -> InMemoryJob:
    return InMemoryJob(
        job_id=kwargs.get("job_id", "dash-job"),
        status=kwargs.get("status", "done"),
        submitted_at=kwargs.get("submitted_at", 1_700_000_000.0),
        completed_at=kwargs.get("completed_at", 1_700_000_012.5),
        total=len(items),
        processed=len(items),
        item_order=[i.input_normalized for i in items],
        results={i.input_normalized: i for i in items},
        lookups_used=3,
        **{k: v for k, v in kwargs.items() if k not in ("job_id", "status", "submitted_at", "completed_at")},
    )


@pytest.fixture
def history_file(tmp_path):
    return tmp_path / "vt_usage_history.jsonl"


class TestDashboardEndpoint:
    def test_missing_history_returns_empty_with_note(self, tmp_path, monkeypatch):
        missing = tmp_path / "missing.jsonl"
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(missing))
        resp = client.get("/api/mdi/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_quality"]["history_file_present"] is False
        assert data["windows"]["last_7_days"]["jobs_run"] == 0
        assert any("not found" in n.lower() for n in data["data_quality"]["notes"])

    def test_malformed_line_skipped_still_200(self, history_file, monkeypatch):
        history_file.write_text(_history_line() + "\n{bad json\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        resp = client.get("/api/mdi/dashboard")
        assert resp.status_code == 200
        assert resp.json()["data_quality"]["records_skipped"] == 1

    def test_non_mdi_records_skipped(self, history_file, monkeypatch):
        history_file.write_text(
            json.dumps({"timestamp": _iso_days_ago(0), "tool_name": "vt-bulk-check"}) + "\n"
            + _history_line() + "\n"
        )
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        data = client.get("/api/mdi/dashboard").json()
        assert data["data_quality"]["records_non_mdi_skipped"] == 1
        assert data["windows"]["all_time"]["jobs_run"] == 1

    def test_window_aggregation_7d_30d_all(self, history_file, monkeypatch):
        lines = [
            _history_line(timestamp=_iso_days_ago(3), job_id="recent"),
            _history_line(timestamp=_iso_days_ago(20), job_id="mid"),
            _history_line(timestamp=_iso_days_ago(60), job_id="old"),
        ]
        history_file.write_text("\n".join(lines) + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        data = client.get("/api/mdi/dashboard").json()
        assert data["windows"]["last_7_days"]["jobs_run"] == 1
        assert data["windows"]["last_30_days"]["jobs_run"] == 2
        assert data["windows"]["all_time"]["jobs_run"] == 3

    def test_job_count_report_lookup_only(self, history_file, monkeypatch):
        history_file.write_text(
            _history_line(operation="report_lookup", job_id="j1") + "\n"
            + _history_line(operation="refresh", job_id="j1", refresh_count=2) + "\n"
            + _history_line(operation="force_scan", job_id="j1", scan_requested_count=1) + "\n"
        )
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        win = client.get("/api/mdi/dashboard").json()["windows"]["all_time"]
        assert win["jobs_run"] == 1
        assert win["operation_counts"]["refresh"] == 1
        assert win["operation_counts"]["force_scan"] == 1

    def test_quota_and_errors_aggregate(self, history_file, monkeypatch):
        history_file.write_text(
            _history_line(quota_units_consumed=4, errors_count=2) + "\n"
            + _history_line(quota_units_consumed=6, errors_count=3) + "\n"
        )
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        win = client.get("/api/mdi/dashboard").json()["windows"]["all_time"]
        assert win["quota_units_consumed"] == 10
        assert win["errors_count"] == 5

    def test_held_rdap_live_autorescan_aggregate(self, history_file, monkeypatch):
        history_file.write_text(_history_line() + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        win = client.get("/api/mdi/dashboard").json()["windows"]["all_time"]
        assert win["held_skipped_count"] == 2
        assert win["rdap_enriched_count"] == 3
        assert win["whois_fallback_count"] == 1
        assert win["live_check_count"] == 4
        assert win["auto_rescan_attempted_count"] == 1

    def test_missing_triage_fields_counted(self, history_file, monkeypatch):
        old = _history_line()
        parsed = json.loads(old)
        for key in ("flagged_count", "clean_count", "triage_bucket_counts"):
            parsed.pop(key, None)
        history_file.write_text(json.dumps(parsed) + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        data = client.get("/api/mdi/dashboard").json()
        assert data["data_quality"]["records_missing_triage_fields"] >= 1
        assert data["windows"]["all_time"]["triage_metrics_available"] is False

    def test_missing_duration_fields_counted(self, history_file, monkeypatch):
        old = json.loads(_history_line())
        old.pop("job_duration_seconds", None)
        history_file.write_text(json.dumps(old) + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        data = client.get("/api/mdi/dashboard").json()
        assert data["data_quality"]["records_missing_duration_fields"] >= 1

    def test_history_domain_not_echoed(self, history_file, monkeypatch):
        leaky = json.loads(_history_line())
        leaky["input_normalized"] = MALICIOUS_DOMAIN
        leaky["input_original"] = MALICIOUS_URL
        history_file.write_text(json.dumps(leaky) + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        text = json.dumps(client.get("/api/mdi/dashboard").json())
        assert MALICIOUS_DOMAIN not in text
        assert MALICIOUS_URL not in text

    def test_history_file_not_modified(self, history_file, monkeypatch):
        history_file.write_text(_history_line() + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        before = history_file.stat().st_size
        client.get("/api/mdi/dashboard")
        assert history_file.stat().st_size == before

    def test_no_external_service_calls(self, history_file, monkeypatch):
        history_file.write_text(_history_line() + "\n")
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history_file))
        with patch("services.vt_service.fetch_report", side_effect=AssertionError("VT")):
            with patch("services.domain_enrichment.enrich_domain", side_effect=AssertionError("RDAP")):
                with patch("services.live_check.live_check_item", side_effect=AssertionError("live")):
                    assert client.get("/api/mdi/dashboard").status_code == 200


class TestDashboardService:
    def test_current_job_summary_aggregates_triage(self):
        items = [
            _make_result("a.example", bucket=TriageBucket.CLEAN, position=1),
            _make_result("b.example", bucket=TriageBucket.MALICIOUS, position=2),
        ]
        job = _make_job(items)
        summary = dashboard.build_current_job_summary(job)
        assert summary["available"] is True
        assert summary["triage_bucket_counts"]["clean"] == 1
        assert summary["triage_bucket_counts"]["malicious"] == 1
        assert summary["flagged_count"] == 1

    def test_current_job_hides_raw_domains(self):
        job = _make_job([_make_result(MALICIOUS_DOMAIN)])
        summary = dashboard.build_current_job_summary(job)
        dumped = json.dumps(summary)
        assert MALICIOUS_DOMAIN not in dumped
        assert "input_normalized" not in dumped

    def test_aggregate_window_avg_runtime(self):
        records = [
            json.loads(_history_line(job_duration_seconds=10)),
            json.loads(_history_line(job_duration_seconds=20)),
        ]
        summary, _ = dashboard.aggregate_window(records)
        assert summary["avg_runtime_seconds"] == 15.0


class TestWriterExtension:
    def test_write_history_includes_aggregate_fields(self, tmp_path):
        items = [
            _make_result("clean.example", bucket=TriageBucket.CLEAN),
            _make_result(MALICIOUS_DOMAIN, bucket=TriageBucket.MALICIOUS, position=2),
        ]
        job = _make_job(items)
        history = tmp_path / "history.jsonl"
        job_processor._write_history(job, history_file=history, daily_file=tmp_path / "daily.json")
        record = json.loads(history.read_text().strip())
        assert "triage_bucket_counts" in record
        assert record["flagged_count"] == 1
        assert record["clean_count"] == 1
        assert "error_code_counts" in record
        assert "job_duration_seconds" in record
        assert MALICIOUS_DOMAIN not in json.dumps(record)
        assert "item_order" not in record
        assert "results" not in record

    def test_build_usage_history_record_aggregate_only(self):
        record = quota_writer.build_usage_history_record(
            job_id="j",
            items_attempted=1,
            items_completed=1,
            quota_units_consumed=1,
            quota_blocked_count=0,
            errors_count=0,
            held_skipped_count=0,
            processing_options_summary={},
            status="done",
            triage_bucket_counts={"clean": 1},
            flagged_count=0,
            error_code_counts={"vt_429": 1},
        )
        assert record["triage_bucket_counts"] == {"clean": 1}
        assert record["error_code_counts"] == {"vt_429": 1}
