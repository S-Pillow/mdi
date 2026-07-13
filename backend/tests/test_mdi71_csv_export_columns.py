"""
MDI-71 — CSV export column reorder, domain column, reported_abuse tests.

No live VT/RDAP/WHOIS/DNS/Cloudflare calls. No quota consumed.
"""

from __future__ import annotations

import asyncio
import csv
import io
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from main import app
from models import (
    DomainHold,
    DomainHoldType,
    DomainStatusSource,
    ExportScope,
    InputType,
    MdiProcessingStatus,
    MdiResultItem,
    TriageBucket,
    VtModeUsed,
)
from services import job_store
from services.domain_enrichment import extract_registered_domain
from services.export_service import (
    CSV_HEADERS,
    build_csv_export,
    dominant_vt_result_label,
    format_export_domain,
    format_reported_abuse,
)
from services.job_store import InMemoryJob, clear_all_jobs

client = TestClient(app)


def _run(coro):
    return asyncio.run(coro)


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def _make_job(items: list[MdiResultItem]) -> InMemoryJob:
    return InMemoryJob(
        job_id="mdi71-test",
        status="done",
        submitted_at=1_700_000_000.0,
        completed_at=1_700_000_100.0,
        total=len(items),
        processed=len(items),
        item_order=[i.input_normalized for i in items],
        results={i.input_normalized: i for i in items},
    )


def _register(job: InMemoryJob) -> None:
    clear_all_jobs()
    _run(job_store.create_job(job))


def _base_row(**updates) -> MdiResultItem:
    row = MdiResultItem(
        input_original="example.com",
        input_normalized="example.com",
        input_type=InputType.DOMAIN,
        position=1,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_hits=1,
        vt_total_engines=92,
        vt_ratio="1/92",
        vt_scan_date=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        triage_bucket=TriageBucket.MALICIOUS,
    )
    return row.model_copy(update=updates) if updates else row


class TestCsvHeaderOrder:
    def test_exact_header_order(self):
        assert CSV_HEADERS == [
            "input",
            "checked_as",
            "domain",
            "registrar",
            "domain_created",
            "hold_status",
            "cloudflare_rank",
            "result",
            "detection_ratio",
            "reported_abuse",
            "last_scanned",
            "error",
        ]


class TestDomainColumn:
    def test_url_with_path(self):
        row = _base_row(
            input_original="https://orlvexa.vu/myparty",
            input_normalized="https://orlvexa.vu/myparty",
            input_type=InputType.URL,
        )
        assert format_export_domain(row) == "orlvexa.vu"
        assert extract_registered_domain(row.input_normalized, row.input_type) == "orlvexa.vu"

    def test_subdomain_url(self):
        row = _base_row(
            input_original="https://confirm.paperlessinvite.vu/",
            input_normalized="https://confirm.paperlessinvite.vu/",
            input_type=InputType.URL,
        )
        assert format_export_domain(row) == "paperlessinvite.vu"

    def test_multi_part_suffix(self):
        row = _base_row(
            input_original="https://sub.test.example.co.uk/path",
            input_normalized="https://sub.test.example.co.uk/path",
            input_type=InputType.URL,
        )
        assert format_export_domain(row) == "example.co.uk"

    def test_bare_domain(self):
        row = _base_row(
            input_original="example.com",
            input_normalized="example.com",
            input_type=InputType.DOMAIN,
        )
        assert format_export_domain(row) == "example.com"

    def test_invalid_ip_blank(self):
        row = _base_row(
            input_original="https://192.0.2.1/path",
            input_normalized="https://192.0.2.1/path",
            input_type=InputType.URL,
        )
        assert format_export_domain(row) == ""


class TestReportedAbuse:
    def test_phishing_majority(self):
        row = _base_row(
            vt_engine_results=[
                {"engine_name": "A", "category": "malicious", "result": "phishing"},
                {"engine_name": "B", "category": "malicious", "result": "phishing"},
                {"engine_name": "C", "category": "malicious", "result": "malicious"},
            ]
        )
        assert dominant_vt_result_label(row) == "phishing"
        assert format_reported_abuse(row) == "phishing"

    def test_malware_majority(self):
        row = _base_row(
            vt_engine_results=[
                {"engine_name": "A", "category": "malicious", "result": "malware"},
                {"engine_name": "B", "category": "malicious", "result": "phishing"},
                {"engine_name": "C", "category": "malicious", "result": "malware"},
                {"engine_name": "D", "category": "malicious", "result": "malware"},
            ]
        )
        assert format_reported_abuse(row) == "malware"

    def test_suspicious_majority(self):
        row = _base_row(
            vt_engine_results=[
                {"engine_name": "A", "category": "suspicious", "result": "Suspicious"},
                {"engine_name": "B", "category": "suspicious", "result": "suspicious"},
            ]
        )
        assert format_reported_abuse(row) == "suspicious"

    def test_tie_alphabetical(self):
        row = _base_row(
            vt_engine_results=[
                {"engine_name": "A", "category": "malicious", "result": "phishing"},
                {"engine_name": "B", "category": "malicious", "result": "malware"},
            ]
        )
        assert format_reported_abuse(row) == "malware"

    def test_clean_row_blank(self):
        row = _base_row(
            vt_hits=0,
            vt_ratio="0/92",
            triage_bucket=TriageBucket.CLEAN,
            vt_engine_results=[],
        )
        assert format_reported_abuse(row) == ""

    def test_held_row_blank(self):
        row = _base_row(
            processing_status=MdiProcessingStatus.HOLD_SKIPPED,
            vt_mode_used=VtModeUsed.SKIPPED_HOLD,
            triage_bucket=TriageBucket.HELD,
            domain_hold=DomainHold(
                has_hold=True,
                hold_types=[DomainHoldType.CLIENT_HOLD],
                source=DomainStatusSource.RDAP,
            ),
            vt_engine_results=None,
        )
        assert format_reported_abuse(row) == ""

    def test_missing_engine_results_blank(self):
        row = _base_row(vt_engine_results=None)
        assert format_reported_abuse(row) == ""

    def test_null_engine_results_ignored(self):
        row = _base_row(
            vt_engine_results=[
                {"engine_name": "A", "category": "malicious", "result": None},
                {"engine_name": "B", "category": "malicious", "result": "   "},
            ]
        )
        assert format_reported_abuse(row) == ""


class TestCsvExportIntegration:
    @pytest.fixture(autouse=True)
    def _clear(self):
        clear_all_jobs()
        yield
        clear_all_jobs()

    def test_export_all_twelve_columns(self):
        scan_dt = datetime(2026, 6, 1, 15, 30, tzinfo=timezone.utc)
        created = datetime(2020, 3, 15, tzinfo=timezone.utc)
        row = MdiResultItem(
            input_original="https://evil.evilcorp.com/path",
            input_normalized="https://evil.evilcorp.com/path",
            input_type=InputType.URL,
            position=1,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_hits=2,
            vt_suspicious=0,
            vt_total_engines=91,
            vt_ratio="2/91",
            vt_scan_date=scan_dt,
            created_at=created,
            registrar="Example Registrar",
            triage_bucket=TriageBucket.MALICIOUS,
            vt_engine_results=[
                {"engine_name": "E1", "category": "malicious", "result": "phishing"},
                {"engine_name": "E2", "category": "malicious", "result": "phishing"},
                {"engine_name": "E3", "category": "malicious", "result": "malware"},
            ],
        )
        _register(_make_job([row]))
        resp = client.post(
            "/api/mdi/jobs/mdi71-test/export",
            json={"format": "csv", "scope": "all"},
        )
        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert rows[0] == CSV_HEADERS
        assert len(rows[1]) == 12
        assert rows[1][0] == "https://evil.evilcorp.com/path"
        assert rows[1][1] == "url_report:https://evil.evilcorp.com/path"
        assert rows[1][2] == "evilcorp.com"
        assert rows[1][3] == "Example Registrar"
        assert rows[1][4] == "2020-03-15"
        assert rows[1][7] == "flagged"
        assert rows[1][8] == "\t2/91"
        assert rows[1][9] == "phishing"
        assert rows[1][10] == "2026-06-01 15:30:00 UTC"

    def test_export_flagged_scope(self):
        clean = _base_row(
            input_original="clean.example",
            input_normalized="clean.example",
            vt_hits=0,
            vt_ratio="0/91",
            triage_bucket=TriageBucket.CLEAN,
            vt_engine_results=[],
        )
        bad = clean.model_copy(
            update={
                "input_original": "bad.example",
                "input_normalized": "bad.example",
                "position": 2,
                "vt_hits": 1,
                "vt_ratio": "1/91",
                "triage_bucket": TriageBucket.MALICIOUS,
                "vt_engine_results": [
                    {"engine_name": "E1", "category": "malicious", "result": "malware"},
                ],
            }
        )
        _register(_make_job([clean, bad]))
        resp = client.post(
            "/api/mdi/jobs/mdi71-test/export",
            json={"format": "csv", "scope": "flagged"},
        )
        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert len(rows) == 2
        assert rows[1][0] == "bad.example"
        assert rows[1][9] == "malware"

    def test_export_selected_scope(self):
        a = _base_row(
            input_original="one.example",
            input_normalized="one.example",
            position=1,
            vt_hits=0,
            vt_ratio="0/91",
            triage_bucket=TriageBucket.CLEAN,
            vt_engine_results=[],
        )
        b = a.model_copy(
            update={"input_original": "two.example", "input_normalized": "two.example", "position": 2}
        )
        _register(_make_job([a, b]))
        resp = client.post(
            "/api/mdi/jobs/mdi71-test/export",
            json={"format": "csv", "scope": "selected", "positions": [2]},
        )
        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert len(rows) == 2
        assert rows[1][0] == "two.example"

    def test_no_external_calls(self):
        row = _base_row(
            input_original="a.example",
            input_normalized="a.example",
            vt_hits=0,
            vt_ratio="0/91",
            triage_bucket=TriageBucket.CLEAN,
            vt_engine_results=[],
        )
        _register(_make_job([row]))
        with patch("services.vt_service.fetch_report", side_effect=AssertionError("VT called")):
            with patch(
                "services.domain_enrichment.enrich_domain",
                side_effect=AssertionError("RDAP/WHOIS"),
            ):
                with patch(
                    "services.live_check.live_check_item",
                    side_effect=AssertionError("live"),
                ):
                    resp = client.post(
                        "/api/mdi/jobs/mdi71-test/export",
                        json={"format": "csv", "scope": "all"},
                    )
        assert resp.status_code == 200

    def test_build_csv_export_direct(self):
        row = _base_row(
            input_original="https://test.example.com/foo",
            input_normalized="https://test.example.com/foo",
            input_type=InputType.URL,
            vt_engine_results=[
                {"engine_name": "E1", "category": "malicious", "result": "phishing"},
            ],
        )
        text = build_csv_export(_make_job([row]), [row], ExportScope.ALL)
        rows = _parse_csv(text)
        assert rows[0] == CSV_HEADERS
        assert rows[1][2] == "example.com"
        assert rows[1][9] == "phishing"
