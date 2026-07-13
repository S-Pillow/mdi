"""
MDI-54A — Lean 10-column CSV export contract tests.

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
    Freshness,
    InputType,
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
    TriageBucket,
    TriageConfidence,
    VtModeUsed,
)
from services import export_service, job_store
from services.export_service import (
    CSV_HEADERS,
    build_csv_export,
    format_checked_as,
    format_cloudflare_rank_popularity_bucket,
    format_detection_ratio_cell,
    format_export_result,
    format_hold_status,
    sanitize_csv_cell,
)
from services.job_store import InMemoryJob, clear_all_jobs

client = TestClient(app)


def _run(coro):
    return asyncio.run(coro)


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def _make_job(items: list[MdiResultItem]) -> InMemoryJob:
    return InMemoryJob(
        job_id="mdi54a-test",
        status="done",
        submitted_at=1_700_000_000.0,
        completed_at=1_700_000_100.0,
        total=len(items),
        processed=len(items),
        item_order=[i.input_normalized for i in items],
        results={i.input_normalized: i for i in items},
    )


class TestCsvContractHeaders:
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


class TestCsvRowFormatters:
    def test_url_report_domain_target(self):
        row = MdiResultItem(
            input_original="example.com",
            input_normalized="example.com",
            input_type=InputType.DOMAIN,
            position=1,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_hits=0,
            vt_suspicious=0,
            vt_total_engines=91,
            vt_ratio="0/91",
            vt_scan_date=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            triage_bucket=TriageBucket.CLEAN,
        )
        assert format_checked_as(row) == "url_report:http://example.com/"

    def test_domain_report_target(self):
        row = MdiResultItem(
            input_original="example.com",
            input_normalized="example.com",
            input_type=InputType.DOMAIN,
            position=1,
            vt_mode_used=VtModeUsed.DOMAIN_REPORT,
            vt_hits=1,
            vt_suspicious=0,
            vt_total_engines=91,
            vt_ratio="1/91",
            vt_scan_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            triage_bucket=TriageBucket.MALICIOUS,
        )
        assert format_checked_as(row) == "domain_report:example.com"

    def test_url_item_url_report(self):
        row = MdiResultItem(
            input_original="https://evil.example/path",
            input_normalized="https://evil.example/path",
            input_type=InputType.URL,
            position=1,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_hits=2,
            vt_total_engines=92,
            vt_ratio="2/92",
            vt_scan_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            triage_bucket=TriageBucket.MALICIOUS,
        )
        assert format_checked_as(row) == "url_report:https://evil.example/path"

    def test_held_row(self):
        row = MdiResultItem(
            input_original="held.example",
            input_normalized="held.example",
            input_type=InputType.DOMAIN,
            position=1,
            processing_status=MdiProcessingStatus.HOLD_SKIPPED,
            vt_mode_used=VtModeUsed.SKIPPED_HOLD,
            triage_bucket=TriageBucket.HELD,
            domain_hold=DomainHold(
                has_hold=True,
                hold_types=[DomainHoldType.CLIENT_HOLD],
                source=DomainStatusSource.RDAP,
            ),
        )
        assert format_checked_as(row) == "skipped_on_hold"
        assert format_export_result(row) == "on_hold"
        assert format_hold_status(row) == "clientHold"
        assert format_detection_ratio_cell(row) == ""

    def test_clean_and_flagged_results(self):
        clean = MdiResultItem(
            input_original="clean.example",
            input_normalized="clean.example",
            input_type=InputType.DOMAIN,
            position=1,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_hits=0,
            vt_suspicious=0,
            vt_total_engines=91,
            vt_ratio="0/91",
            vt_scan_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            triage_bucket=TriageBucket.CLEAN,
        )
        flagged = clean.model_copy(update={"vt_hits": 1, "vt_ratio": "1/91", "triage_bucket": TriageBucket.MALICIOUS})
        assert format_export_result(clean) == "clean"
        assert format_export_result(flagged) == "flagged"

    def test_detection_ratio_tab_prefix(self):
        row = MdiResultItem(
            input_original="x.example",
            input_normalized="x.example",
            input_type=InputType.DOMAIN,
            position=1,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_hits=1,
            vt_total_engines=91,
            vt_ratio="1/91",
            vt_scan_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert format_detection_ratio_cell(row) == "\t1/91"
        assert sanitize_csv_cell("=bad") == "'=bad"
        assert format_detection_ratio_cell(row).startswith("\t")

    def test_detection_ratio_blank_for_zero_over_zero(self):
        row = MdiResultItem(
            input_original="x.example",
            input_normalized="x.example",
            input_type=InputType.DOMAIN,
            position=1,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_ratio="0/0",
        )
        assert format_detection_ratio_cell(row) == ""

    def test_cloudflare_unranked_inequality_display(self):
        row = MdiResultItem(
            input_original="pop.example",
            input_normalized="pop.example",
            input_type=InputType.DOMAIN,
            position=1,
            cloudflare_rank_available=True,
            cloudflare_rank_bucket="UNRANKED",
            cloudflare_rank_raw_bucket=">200000",
        )
        assert format_cloudflare_rank_popularity_bucket(row) == ">200000 / UNRANKED"

    def test_quota_blocked_row(self):
        row = MdiResultItem(
            input_original="q.example",
            input_normalized="q.example",
            input_type=InputType.DOMAIN,
            position=1,
            processing_status=MdiProcessingStatus.ERROR,
            vt_mode_used=VtModeUsed.SKIPPED_QUOTA,
            triage_bucket=TriageBucket.ERROR,
            errors=[
                MdiError(
                    code="quota_exhausted",
                    message="VT daily quota exhausted before this item was processed.",
                    source="job_processor",
                )
            ],
        )
        assert format_checked_as(row) == "not_checked_quota_blocked"
        assert format_export_result(row) == "error"


class TestCsvExportIntegration:
    @pytest.fixture(autouse=True)
    def _clear(self):
        clear_all_jobs()
        yield
        clear_all_jobs()

    def _register(self, job: InMemoryJob) -> None:
        clear_all_jobs()
        _run(job_store.create_job(job))

    def test_export_all_twelve_columns(self):
        scan_dt = datetime(2026, 6, 1, 15, 30, tzinfo=timezone.utc)
        created = datetime(2020, 3, 15, tzinfo=timezone.utc)
        row = MdiResultItem(
            input_original="flagged.com",
            input_normalized="flagged.com",
            input_type=InputType.DOMAIN,
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
            triage_confidence=TriageConfidence.HIGH,
            cloudflare_rank_available=True,
            cloudflare_rank_bucket="UNRANKED",
            cloudflare_rank_raw_bucket=">200000",
        )
        self._register(_make_job([row]))
        resp = client.post(
            "/api/mdi/jobs/mdi54a-test/export",
            json={"format": "csv", "scope": "all"},
        )
        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert rows[0] == CSV_HEADERS
        assert len(rows[1]) == 12
        assert rows[1][0] == "flagged.com"
        assert rows[1][1] == "url_report:http://flagged.com/"
        assert rows[1][2] == "flagged.com"
        assert rows[1][3] == "Example Registrar"
        assert rows[1][4] == "2020-03-15"
        assert rows[1][6] == ">200000 / UNRANKED"
        assert rows[1][7] == "flagged"
        assert rows[1][8] == "\t2/91"
        assert rows[1][10] == "2026-06-01 15:30:00 UTC"

    def test_export_flagged_scope_unchanged(self):
        clean = MdiResultItem(
            input_original="clean.example",
            input_normalized="clean.example",
            input_type=InputType.DOMAIN,
            position=1,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_hits=0,
            vt_total_engines=91,
            vt_ratio="0/91",
            vt_scan_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            triage_bucket=TriageBucket.CLEAN,
        )
        bad = clean.model_copy(
            update={
                "input_original": "bad.example",
                "input_normalized": "bad.example",
                "position": 2,
                "vt_hits": 1,
                "vt_ratio": "1/91",
                "triage_bucket": TriageBucket.MALICIOUS,
            }
        )
        self._register(_make_job([clean, bad]))
        resp = client.post(
            "/api/mdi/jobs/mdi54a-test/export",
            json={"format": "csv", "scope": "flagged"},
        )
        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert len(rows) == 2
        assert "bad.example" in rows[1][0]
        assert "clean.example" not in rows[1][0]

    def test_export_selected_scope(self):
        a = MdiResultItem(
            input_original="one.example",
            input_normalized="one.example",
            input_type=InputType.DOMAIN,
            position=1,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_hits=0,
            vt_total_engines=91,
            vt_ratio="0/91",
            vt_scan_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        b = a.model_copy(
            update={"input_original": "two.example", "input_normalized": "two.example", "position": 2}
        )
        self._register(_make_job([a, b]))
        resp = client.post(
            "/api/mdi/jobs/mdi54a-test/export",
            json={"format": "csv", "scope": "selected", "positions": [2]},
        )
        assert resp.status_code == 200
        rows = _parse_csv(resp.text)
        assert len(rows) == 2
        assert rows[1][0] == "two.example"

    def test_no_external_calls(self):
        row = MdiResultItem(
            input_original="a.example",
            input_normalized="a.example",
            input_type=InputType.DOMAIN,
            position=1,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_hits=0,
            vt_total_engines=91,
            vt_ratio="0/91",
            vt_scan_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        self._register(_make_job([row]))
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
                        "/api/mdi/jobs/mdi54a-test/export",
                        json={"format": "csv", "scope": "all"},
                    )
        assert resp.status_code == 200

    def test_json_export_unchanged_schema(self):
        row = MdiResultItem(
            input_original="a.example",
            input_normalized="a.example",
            input_type=InputType.DOMAIN,
            position=1,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_targeted_brand="PayPal",
            vt_hits=0,
            vt_total_engines=91,
            vt_ratio="0/91",
            vt_scan_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        self._register(_make_job([row]))
        resp = client.post(
            "/api/mdi/jobs/mdi54a-test/export",
            json={"format": "json", "scope": "all"},
        )
        assert resp.status_code == 200
        import json

        data = json.loads(resp.text)
        assert data["schema_version"] == "mdi-evidence-v1"
        assert "vt_targeted_brand" in data["results"][0]
        assert "triage_bucket" in data["results"][0]
