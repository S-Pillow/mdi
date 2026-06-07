"""
MDI-16 — CSV and JSON evidence export tests.

No live VT/RDAP/WHOIS/DNS calls. Runtime files isolated via conftest.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
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
    ExportFormat,
    ExportRequest,
    ExportScope,
    Freshness,
    InputType,
    LiveStatus,
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
    TriageBucket,
    TriageConfidence,
)
from services import export_service, job_store
from services.export_service import CSV_HEADERS, sanitize_csv_cell
from services.job_store import InMemoryJob, clear_all_jobs

client = TestClient(app)


def _run(coro):
    return asyncio.run(coro)


def _make_result(
    normalized: str,
    *,
    position: int = 1,
    triage_bucket=TriageBucket.CLEAN,
    vt_hits=0,
    vt_suspicious=0,
    held=False,
    vt_engine_results=None,
    epp_status=None,
    nameservers=None,
    triage_reason=None,
    errors=None,
    input_original=None,
):
    hold = DomainHold(
        has_hold=held,
        hold_types=[DomainHoldType.CLIENT_HOLD] if held else [DomainHoldType.NONE],
        source=DomainStatusSource.RDAP if held else DomainStatusSource.NOT_CHECKED,
    )
    return MdiResultItem(
        input_original=input_original or normalized,
        input_normalized=normalized,
        input_type=InputType.DOMAIN,
        position=position,
        processing_status=MdiProcessingStatus.HOLD_SKIPPED if held else MdiProcessingStatus.DONE,
        domain_hold=hold,
        vt_hits=vt_hits,
        vt_suspicious=vt_suspicious,
        vt_total_engines=75 if not held else 0,
        vt_ratio=f"{vt_hits}/75",
        freshness=Freshness.FRESH,
        age_bucket=AgeBucket.MATURE,
        triage_bucket=triage_bucket,
        triage_confidence=TriageConfidence.HIGH,
        live_status=LiveStatus.NOT_CHECKED,
        vt_engine_results=vt_engine_results,
        epp_status=epp_status or [],
        nameservers=nameservers or [],
        triage_reason=triage_reason or [],
        errors=errors or [],
    )


def _make_job(
    items: list[MdiResultItem],
    *,
    job_id: str = "export-test-job",
    status: str = "done",
    action_in_progress: bool = False,
) -> InMemoryJob:
    job = InMemoryJob(
        job_id=job_id,
        status=status,
        submitted_at=1_700_000_000.0,
        completed_at=1_700_000_100.0,
        total=len(items),
        processed=len(items),
        item_order=[i.input_normalized for i in items],
        results={i.input_normalized: i for i in items},
        lookups_used=3,
        estimated_requests=3,
        action_in_progress=action_in_progress,
    )
    return job


def _register_job(job: InMemoryJob) -> None:
    clear_all_jobs()
    _run(job_store.create_job(job))


def _export(job_id: str, payload: dict):
    return client.post(f"/api/mdi/jobs/{job_id}/export", json=payload)


@pytest.fixture(autouse=True)
def _clear_jobs():
    clear_all_jobs()
    yield
    clear_all_jobs()


class TestCsvExport:
    def test_csv_all_returns_attachment(self):
        items = [
            _make_result("clean.example", position=1),
            _make_result("bad.example", position=2, triage_bucket=TriageBucket.MALICIOUS, vt_hits=3),
        ]
        _register_job(_make_job(items))
        resp = _export("export-test-job", {"format": "csv", "scope": "all"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_csv_all_stable_headers(self):
        _register_job(_make_job([_make_result("a.example")]))
        resp = _export("export-test-job", {"format": "csv", "scope": "all"})
        first_line = resp.text.splitlines()[0]
        assert first_line == ",".join(CSV_HEADERS)

    def test_csv_all_row_count(self):
        items = [_make_result(f"d{i}.example", position=i) for i in range(1, 4)]
        _register_job(_make_job(items))
        resp = _export("export-test-job", {"format": "csv", "scope": "all"})
        assert len(resp.text.splitlines()) == 4  # header + 3 rows

    def test_csv_selected_positions_only(self):
        items = [
            _make_result("one.example", position=1),
            _make_result("two.example", position=2),
            _make_result("three.example", position=3),
        ]
        _register_job(_make_job(items))
        resp = _export(
            "export-test-job",
            {"format": "csv", "scope": "selected", "positions": [2]},
        )
        lines = resp.text.splitlines()
        assert len(lines) == 2
        assert "two.example" in lines[1]
        assert "one.example" not in lines[1]

    def test_csv_flagged_only(self):
        items = [
            _make_result("clean.example", position=1),
            _make_result(
                "bad.example",
                position=2,
                triage_bucket=TriageBucket.MALICIOUS,
                vt_hits=2,
            ),
        ]
        _register_job(_make_job(items))
        resp = _export("export-test-job", {"format": "csv", "scope": "flagged"})
        lines = resp.text.splitlines()
        assert len(lines) == 2
        assert "bad.example" in lines[1]
        assert "clean.example" not in resp.text.splitlines()[1]

    def test_csv_flagged_excludes_clean(self):
        items = [_make_result("clean.example", position=1, vt_hits=0, vt_suspicious=0)]
        _register_job(_make_job(items))
        resp = _export("export-test-job", {"format": "csv", "scope": "flagged"})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "no_flagged_rows"
        assert detail["category"] == "export"

    def test_csv_flagged_excludes_held_unless_selected_or_all(self):
        held_flagged = _make_result(
            "held.example",
            position=1,
            held=True,
            triage_bucket=TriageBucket.MALICIOUS,
            vt_hits=5,
        )
        _register_job(_make_job([held_flagged]))
        flagged_resp = _export("export-test-job", {"format": "csv", "scope": "flagged"})
        assert flagged_resp.status_code == 422

        all_resp = _export("export-test-job", {"format": "csv", "scope": "all"})
        assert all_resp.status_code == 200
        assert "held.example" in all_resp.text

        selected_resp = _export(
            "export-test-job",
            {"format": "csv", "scope": "selected", "positions": [1]},
        )
        assert selected_resp.status_code == 200
        assert "held.example" in selected_resp.text

    def test_csv_quoting_commas_newlines_quotes(self):
        item = _make_result(
            'say,"hello"',
            position=1,
            input_original='line1\nline2, quoted',
        )
        _register_job(_make_job([item]))
        resp = _export("export-test-job", {"format": "csv", "scope": "all"})
        assert resp.status_code == 200
        assert '"' in resp.text

    @pytest.mark.parametrize(
        "raw,expected_prefix",
        [
            ("=cmd|", "'"),
            ("+123", "'"),
            ("-1+1", "'"),
            ("@SUM()", "'"),
            ("\tvalue", "'"),
            ("\rvalue", "'"),
        ],
    )
    def test_csv_formula_injection_mitigation(self, raw, expected_prefix):
        assert sanitize_csv_cell(raw).startswith(expected_prefix)


class TestJsonExport:
    def test_json_schema_version(self):
        _register_job(_make_job([_make_result("a.example")]))
        resp = _export(
            "export-test-job",
            {"format": "json", "scope": "selected", "positions": [1]},
        )
        data = json.loads(resp.text)
        assert data["schema_version"] == "mdi-evidence-v1"

    def test_json_includes_job_metadata(self):
        _register_job(_make_job([_make_result("a.example")]))
        resp = _export("export-test-job", {"format": "json", "scope": "all"})
        data = json.loads(resp.text)
        job = data["job"]
        assert job["job_id"] == "export-test-job"
        assert job["lookups_used"] == 3
        assert "auto_rescan_attempted_count" in job
        assert "held_skipped" in job

    def test_json_includes_vt_engine_results(self):
        engines = [{"engine": "ESET", "category": "malicious", "result": "phishing"}]
        item = _make_result("bad.example", vt_hits=1, vt_engine_results=engines)
        _register_job(_make_job([item]))
        resp = _export("export-test-job", {"format": "json", "scope": "all"})
        result = json.loads(resp.text)["results"][0]
        assert result["vt_engine_results"] == engines

    def test_json_triage_reason_list(self):
        item = _make_result("a.example", triage_reason=["reason one", "reason two"])
        _register_job(_make_job([item]))
        resp = _export("export-test-job", {"format": "json", "scope": "all"})
        result = json.loads(resp.text)["results"][0]
        assert result["triage_reason"] == ["reason one", "reason two"]

    def test_json_sanitized_errors(self):
        err = MdiError(code="vt_429", message="rate limited", source="vt", retriable=True)
        item = _make_result("a.example", errors=[err])
        _register_job(_make_job([item]))
        resp = _export("export-test-job", {"format": "json", "scope": "all"})
        errors = json.loads(resp.text)["results"][0]["errors"]
        assert errors[0]["code"] == "vt_429"
        assert errors[0]["message"] == "rate limited"
        assert errors[0]["category"] == "vt_lookup"
        assert errors[0]["severity"] == "error"
        assert errors[0]["blocks_triage"] is True

    def test_json_epp_status_and_nameservers(self):
        item = _make_result(
            "a.example",
            epp_status=["clientTransferProhibited"],
            nameservers=["ns1.example", "ns2.example"],
        )
        _register_job(_make_job([item]))
        resp = _export("export-test-job", {"format": "json", "scope": "all"})
        result = json.loads(resp.text)["results"][0]
        assert result["epp_status"] == ["clientTransferProhibited"]
        assert result["nameservers"] == ["ns1.example", "ns2.example"]

    def test_json_selected_only_requested_rows(self):
        items = [
            _make_result("one.example", position=1),
            _make_result("two.example", position=2),
        ]
        _register_job(_make_job(items))
        resp = _export(
            "export-test-job",
            {"format": "json", "scope": "selected", "positions": [2]},
        )
        data = json.loads(resp.text)
        assert data["positions"] == [2]
        assert len(data["results"]) == 1
        assert data["results"][0]["input_normalized"] == "two.example"

    def test_json_missing_vt_engine_results_graceful(self):
        item = _make_result("legacy.example")
        item.vt_engine_results = None
        _register_job(_make_job([item]))
        resp = _export("export-test-job", {"format": "json", "scope": "all"})
        result = json.loads(resp.text)["results"][0]
        assert result["vt_engine_results"] is None


class TestExportValidation:
    def test_invalid_job_id_404(self):
        resp = _export("missing-job", {"format": "csv", "scope": "all"})
        assert resp.status_code == 404

    def test_empty_selected_positions_422(self):
        _register_job(_make_job([_make_result("a.example")]))
        resp = _export(
            "export-test-job",
            {"format": "csv", "scope": "selected", "positions": []},
        )
        assert resp.status_code == 422

    def test_invalid_positions_422(self):
        _register_job(_make_job([_make_result("a.example", position=1)]))
        resp = _export(
            "export-test-job",
            {"format": "csv", "scope": "selected", "positions": [99]},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "invalid_selection"
        assert "Invalid positions" in detail["message"]

    def test_no_flagged_rows_422(self):
        _register_job(_make_job([_make_result("clean.example")]))
        resp = _export("export-test-job", {"format": "csv", "scope": "flagged"})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "no_flagged_rows"
        assert detail["category"] == "export"

    @pytest.mark.parametrize("status", ["queued", "running"])
    def test_in_progress_job_status_422(self, status):
        _register_job(_make_job([_make_result("a.example")], status=status))
        resp = _export("export-test-job", {"format": "csv", "scope": "all"})
        assert resp.status_code == 422

    def test_action_in_progress_422(self):
        _register_job(
            _make_job([_make_result("a.example")], action_in_progress=True)
        )
        resp = _export("export-test-job", {"format": "csv", "scope": "all"})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "action_in_progress"


class TestExportIsolation:
    def test_recovered_latest_job_export(self, tmp_path, monkeypatch):
        items = [_make_result("recovered.example")]
        job = _make_job(items, job_id="recovered-job")
        job_file = tmp_path / "mdi_latest_job.json"
        monkeypatch.setenv("MDI_LATEST_JOB_FILE", str(job_file))
        from services import job_persistence

        _run(job_persistence.write_latest_job(job, job_file=job_file))
        clear_all_jobs()
        resp = _export("recovered-job", {"format": "csv", "scope": "all"})
        assert resp.status_code == 200
        assert "recovered.example" in resp.text

    def test_no_vt_calls(self):
        items = [_make_result("a.example")]
        _register_job(_make_job(items))
        with patch("services.vt_service.fetch_report", side_effect=AssertionError("VT called")):
            resp = _export("export-test-job", {"format": "csv", "scope": "all"})
        assert resp.status_code == 200

    def test_no_rdap_whois_calls(self):
        items = [_make_result("a.example")]
        _register_job(_make_job(items))
        with patch(
            "services.domain_enrichment.enrich_domain",
            side_effect=AssertionError("RDAP/WHOIS"),
        ):
            resp = _export("export-test-job", {"format": "json", "scope": "all"})
        assert resp.status_code == 200

    def test_no_live_check_calls(self):
        items = [_make_result("a.example")]
        _register_job(_make_job(items))
        with patch(
            "services.live_check.live_check_item",
            side_effect=AssertionError("live"),
        ):
            resp = _export("export-test-job", {"format": "csv", "scope": "all"})
        assert resp.status_code == 200

    def test_runtime_files_not_modified(self, tmp_path, monkeypatch):
        paths = {
            "MDI_LATEST_JOB_FILE": tmp_path / "mdi_latest_job.json",
            "VT_USAGE_FILE": tmp_path / "vt_usage.json",
            "VT_USAGE_HISTORY_FILE": tmp_path / "vt_usage_history.jsonl",
            "VT_DAILY_HISTORY_FILE": tmp_path / "vt_daily_history.json",
        }
        for key, path in paths.items():
            monkeypatch.setenv(key, str(path))
            path.write_text("{}" if path.suffix == ".json" else "")
        before = {p: p.stat().st_size for p in paths.values()}

        _register_job(_make_job([_make_result("a.example")]))
        resp = _export("export-test-job", {"format": "csv", "scope": "all"})
        assert resp.status_code == 200

        for path in paths.values():
            assert path.stat().st_size == before[path]

    def test_usage_history_line_count_unchanged(self, tmp_path, monkeypatch):
        history = tmp_path / "vt_usage_history.jsonl"
        history.write_text('{"tool_name":"mdi"}\n' * 3)
        monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(history))
        lines_before = sum(1 for _ in history.open())

        _register_job(_make_job([_make_result("a.example")]))
        _export("export-test-job", {"format": "json", "scope": "all"})

        lines_after = sum(1 for _ in history.open())
        assert lines_after == lines_before


class TestExportServiceUnit:
    def test_select_export_rows_ignores_positions_for_all(self):
        items = [
            _make_result("one.example", position=1),
            _make_result("two.example", position=2),
        ]
        job = _make_job(items)
        req = ExportRequest(format=ExportFormat.CSV, scope=ExportScope.ALL, positions=[99])
        rows, err = export_service.select_export_rows(job, req)
        assert err is None
        assert len(rows) == 2
