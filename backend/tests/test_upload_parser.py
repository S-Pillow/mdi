"""
Tests for:
  - backend/services/hold_detection.py
  - backend/services/upload_parser.py
  - POST /api/mdi/jobs/upload-preview endpoint

All tests are purely local — no network, no DNS, no VT, no WHOIS, no runtime files.
Fixture CSV files live in backend/tests/fixtures/.
XLSX fixtures are generated in-memory using openpyxl.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
import openpyxl

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    AgeBucket,
    DomainHoldType,
    DomainStatusSource,
    InputType,
)
from services.hold_detection import detect_hold, hold_type_display
from services.upload_parser import parse_upload


FIXTURES = Path(__file__).parent / "fixtures"


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _csv_bytes(content: str) -> bytes:
    return content.encode("utf-8")


def _xlsx_bytes(rows: list[list]) -> bytes:
    """Build a minimal XLSX in memory from a list-of-lists (first row = headers)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── hold_detection ─────────────────────────────────────────────────────────────

class TestHoldDetection:

    def test_client_hold_detected(self):
        dh = detect_hold("clientHold")
        assert dh.has_hold is True
        assert DomainHoldType.CLIENT_HOLD in dh.hold_types

    def test_server_hold_detected(self):
        dh = detect_hold("serverHold")
        assert dh.has_hold is True
        assert DomainHoldType.SERVER_HOLD in dh.hold_types

    def test_both_holds_detected(self):
        dh = detect_hold("clientHold, serverHold")
        assert dh.has_hold is True
        assert DomainHoldType.CLIENT_HOLD in dh.hold_types
        assert DomainHoldType.SERVER_HOLD in dh.hold_types

    def test_both_holds_semicolon(self):
        dh = detect_hold("clientHold; serverHold")
        assert dh.has_hold is True
        assert len([t for t in dh.hold_types if t != DomainHoldType.NONE]) == 2

    def test_both_holds_newline_separated(self):
        dh = detect_hold("clientHold\nserverHold")
        assert dh.has_hold is True

    def test_case_insensitive_client(self):
        for variant in ["CLIENTHOLD", "ClientHold", "clienthold"]:
            dh = detect_hold(variant)
            assert dh.has_hold is True, f"case variant failed: {variant}"

    def test_case_insensitive_server(self):
        for variant in ["SERVERHOLD", "ServerHold", "serverhold"]:
            dh = detect_hold(variant)
            assert dh.has_hold is True, f"case variant failed: {variant}"

    def test_status_present_no_hold(self):
        dh = detect_hold("clientTransferProhibited clientDeleteProhibited")
        assert dh.has_hold is False
        assert DomainHoldType.NONE in dh.hold_types

    def test_missing_status_returns_unk(self):
        dh = detect_hold(None)
        assert dh.has_hold is False
        assert dh.source == DomainStatusSource.NOT_CHECKED

    def test_empty_status_returns_unk(self):
        dh = detect_hold("   ")
        assert dh.has_hold is False
        assert dh.source == DomainStatusSource.NOT_CHECKED

    def test_icann_url_suffix_stripped(self):
        dh = detect_hold(
            "clientHold https://icann.org/epp#clientHold"
            " serverHold https://icann.org/epp#serverHold"
        )
        assert dh.has_hold is True
        assert DomainHoldType.CLIENT_HOLD in dh.hold_types
        assert DomainHoldType.SERVER_HOLD in dh.hold_types

    def test_display_both_holds(self):
        dh = detect_hold("clientHold serverHold")
        assert hold_type_display(dh) == "clientHold + serverHold"

    def test_display_no_hold(self):
        dh = detect_hold("clientTransferProhibited")
        assert hold_type_display(dh) == "none"

    def test_display_unknown(self):
        dh = detect_hold(None)
        assert hold_type_display(dh) == "unknown"

    def test_source_preserved(self):
        dh = detect_hold("clientHold", source=DomainStatusSource.UPLOADED_FILE)
        assert dh.source == DomainStatusSource.UPLOADED_FILE


# ── upload_parser — CSV ────────────────────────────────────────────────────────

class TestUploadParserCSV:

    def test_parse_csv_dns_form_column(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        # example.com accepted first; second occurrence is a duplicate
        norms = [i.input_normalized for i in result.accepted]
        assert "example.com" in norms

    def test_parse_csv_domain_column(self):
        data = FIXTURES / "sample_domain_col.csv"
        result = parse_upload(data.read_bytes(), "sample_domain_col.csv")
        assert result.columns_detected.domain == "Domain"
        norms = [i.input_normalized for i in result.accepted]
        assert "good-domain.com" in norms

    def test_extract_create_date(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        example = next(i for i in result.accepted if i.input_normalized == "example.com")
        assert example.created_at == "2021-03-15"

    def test_extract_registrar(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        example = next(i for i in result.accepted if i.input_normalized == "example.com")
        assert example.registrar == "Example Registrar Inc."

    def test_extract_assigned_nameservers(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        example = next(i for i in result.accepted if i.input_normalized == "example.com")
        assert "ns1.example.com" in example.assigned_nameservers
        assert "ns2.example.com" in example.assigned_nameservers

    def test_extract_epp_status(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        example = next(i for i in result.accepted if i.input_normalized == "example.com")
        assert "clientTransferProhibited" in example.epp_status

    def test_detect_client_hold_in_csv(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        phishing = next(i for i in result.accepted if i.input_normalized == "phishing.net")
        assert phishing.domain_hold.has_hold is True
        assert DomainHoldType.CLIENT_HOLD in phishing.domain_hold.hold_types

    def test_detect_server_hold_from_domain_column(self):
        data = FIXTURES / "sample_domain_col.csv"
        result = parse_upload(data.read_bytes(), "sample_domain_col.csv")
        srv = next(i for i in result.accepted if i.input_normalized == "server-held.net")
        assert srv.domain_hold.has_hold is True
        assert DomainHoldType.SERVER_HOLD in srv.domain_hold.hold_types

    def test_detect_both_holds_in_csv(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        double = next(i for i in result.accepted if i.input_normalized == "double-held.org")
        assert double.domain_hold.has_hold is True
        assert DomainHoldType.CLIENT_HOLD in double.domain_hold.hold_types
        assert DomainHoldType.SERVER_HOLD in double.domain_hold.hold_types

    def test_status_present_but_no_hold(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        clean = next(i for i in result.accepted if i.input_normalized == "clean.biz")
        assert clean.domain_hold.has_hold is False
        assert clean.domain_hold.source == DomainStatusSource.UPLOADED_FILE

    def test_missing_status_column_gives_unk(self):
        csv_content = "Domain\nexample.com\n"
        result = parse_upload(_csv_bytes(csv_content), "test.csv")
        item = result.accepted[0]
        assert item.domain_hold.has_hold is False
        assert item.domain_hold.source == DomainStatusSource.NOT_CHECKED

    def test_missing_create_date_gives_unknown_age_bucket(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        nodate = next(i for i in result.accepted if i.input_normalized == "nodate.net")
        assert nodate.age_bucket == AgeBucket.UNKNOWN

    def test_age_bucket_derived_from_old_date(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        # double-held.org created 2019-05-20 → > 2 years ago → MATURE
        double = next(i for i in result.accepted if i.input_normalized == "double-held.org")
        assert double.age_bucket == AgeBucket.MATURE

    def test_age_bucket_very_new(self):
        # new-domain.io created 2026-05-30 → < 30 days → VERY_NEW
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        new_d = next((i for i in result.accepted if i.input_normalized == "new-domain.io"), None)
        assert new_d is not None
        assert new_d.age_bucket == AgeBucket.VERY_NEW

    def test_uppercase_domain_normalized(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        norms = [i.input_normalized for i in result.accepted]
        assert "uppercase.com" in norms
        assert "UPPERCASE.COM" not in norms

    def test_dedupe_preserves_first_seen(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        # example.com appears twice; only once in accepted, once in duplicates
        accepted_norms = [i.input_normalized for i in result.accepted]
        assert accepted_norms.count("example.com") == 1
        dup_ofs = [d.duplicate_of for d in result.duplicates]
        assert "example.com" in dup_ofs

    def test_invalid_domain_rejected(self):
        data = FIXTURES / "sample_domain_col.csv"
        result = parse_upload(data.read_bytes(), "sample_domain_col.csv")
        rej_originals = [r.input_original for r in result.rejected]
        assert "bad@@invalid!domain" in rej_originals

    def test_csv_ip_address_rejected(self):
        csv_content = (
            "Domain,Created,Domain Status,Registrar,Nameservers\n"
            "8.8.8.8,2020-01-01,ok,Test Registrar,ns1.test.com\n"
        ).encode()
        result = parse_upload(csv_content, "ip_only.csv")
        assert len(result.accepted) == 0
        assert len(result.rejected) == 1
        assert result.rejected[0].error.code == "ip_address_not_supported"

    def test_csv_domain_accepted(self):
        csv_content = (
            "Domain,Created,Domain Status,Registrar,Nameservers\n"
            "example.com,2020-01-01,ok,Test Registrar,ns1.test.com\n"
        ).encode()
        result = parse_upload(csv_content, "domain_only.csv")
        assert len(result.accepted) == 1
        assert result.accepted[0].input_normalized == "example.com"
        assert len(result.rejected) == 0

    def test_csv_mixed_ip_and_domain(self):
        csv_content = (
            "Domain,Created,Domain Status,Registrar,Nameservers\n"
            "8.8.8.8,2020-01-01,ok,Test Registrar,ns1.test.com\n"
            "example.com,2021-01-01,ok,Test Registrar,ns2.test.com\n"
            "192.168.1.1,2022-01-01,ok,Test Registrar,ns3.test.com\n"
        ).encode()
        result = parse_upload(csv_content, "mixed_ip_domain.csv")
        assert len(result.accepted) == 1
        assert result.accepted[0].input_normalized == "example.com"
        assert len(result.rejected) == 2
        assert all(r.error.code == "ip_address_not_supported" for r in result.rejected)

    def test_no_domain_column_rejected(self):
        data = FIXTURES / "no_domain_col.csv"
        result = parse_upload(data.read_bytes(), "no_domain_col.csv")
        assert len(result.accepted) == 0
        assert any(r.error.code == "missing_domain_column" for r in result.rejected)

    def test_position_order(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        positions = [i.position for i in result.accepted]
        assert positions == list(range(1, len(positions) + 1))

    def test_triage_fields_held_item(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        from models import (
            EvidenceStatus, RecommendedAction, TriageBucket,
            TriageConfidence, VtModeUsed,
        )
        phishing = next(i for i in result.accepted if i.input_normalized == "phishing.net")
        # PRD contract: held items must map to "Domain On Hold / Action Already Taken / Skipped - On Hold"
        assert phishing.triage_bucket == TriageBucket.HELD                         # Domain On Hold
        assert phishing.recommended_action == RecommendedAction.ACTION_ALREADY_TAKEN  # Action Already Taken
        assert phishing.evidence_status == EvidenceStatus.SKIPPED_HOLD             # Skipped - On Hold
        assert phishing.triage_confidence == TriageConfidence.HIGH
        assert phishing.vt_mode_used == VtModeUsed.SKIPPED_HOLD

    def test_url_entry_accepted_as_url_type(self):
        data = FIXTURES / "sample_domain_col.csv"
        result = parse_upload(data.read_bytes(), "sample_domain_col.csv")
        url_item = next((i for i in result.accepted if "url-entry.org" in i.input_normalized), None)
        assert url_item is not None
        assert url_item.input_type == InputType.URL

    def test_domain_status_source_uploaded(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        for item in result.accepted:
            if item.domain_hold.source != DomainStatusSource.NOT_CHECKED:
                assert item.domain_status_source == DomainStatusSource.UPLOADED_FILE

    def test_unsupported_format(self):
        result = parse_upload(b"some content", "file.txt")
        assert len(result.accepted) == 0
        assert any(r.error.code == "unsupported_format" for r in result.rejected)

    def test_columns_detected_structure(self):
        data = FIXTURES / "sample_dns_form.csv"
        result = parse_upload(data.read_bytes(), "sample_dns_form.csv")
        cd = result.columns_detected
        assert cd.domain == "DNS Form"
        assert cd.created_at == "Create Date"
        assert cd.epp_status == "EPP Status"
        assert cd.registrar == "Registrar Name"
        assert cd.nameservers == "Assigned Nameservers"

    def test_missing_optional_columns_reported(self):
        csv_content = "Domain\nexample.com\n"
        result = parse_upload(_csv_bytes(csv_content), "test.csv")
        assert "created_at" in result.missing_optional_columns
        assert "epp_status" in result.missing_optional_columns
        assert "domain_state" in result.missing_optional_columns
        assert "registrar" in result.missing_optional_columns
        assert "nameservers" in result.missing_optional_columns


# ── upload_parser — XLSX ───────────────────────────────────────────────────────

class TestUploadParserXLSX:

    def test_parse_xlsx_dns_form_column(self):
        xlsx = _xlsx_bytes([
            ["DNS Form", "Create Date", "EPP Status", "Registrar Name", "Assigned Nameservers"],
            ["example.com", "2021-03-15", "clientTransferProhibited", "Test Registrar", "ns1.test.com"],
            ["phishing.net", "2024-11-01", "clientHold", "Bad Registrar", ""],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        norms = [i.input_normalized for i in result.accepted]
        assert "example.com" in norms
        assert "phishing.net" in norms

    def test_parse_xlsx_domain_column(self):
        xlsx = _xlsx_bytes([
            ["Domain", "Created"],
            ["good.com", "2020-01-01"],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        assert result.columns_detected.domain == "Domain"
        assert result.accepted[0].input_normalized == "good.com"

    def test_xlsx_detect_client_hold(self):
        xlsx = _xlsx_bytes([
            ["Domain", "EPP Status"],
            ["held.com", "clientHold"],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        assert result.accepted[0].domain_hold.has_hold is True

    def test_xlsx_detect_server_hold(self):
        xlsx = _xlsx_bytes([
            ["Domain", "Domain Status"],
            ["srv.com", "serverHold"],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        assert result.accepted[0].domain_hold.has_hold is True
        assert DomainHoldType.SERVER_HOLD in result.accepted[0].domain_hold.hold_types

    def test_xlsx_both_holds(self):
        xlsx = _xlsx_bytes([
            ["Domain", "EPP Status"],
            ["both.com", "clientHold serverHold"],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        dh = result.accepted[0].domain_hold
        assert DomainHoldType.CLIENT_HOLD in dh.hold_types
        assert DomainHoldType.SERVER_HOLD in dh.hold_types

    def test_xlsx_extract_create_date(self):
        xlsx = _xlsx_bytes([
            ["DNS Form", "Create Date"],
            ["example.com", "2019-07-04"],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        assert result.accepted[0].created_at == "2019-07-04"

    def test_xlsx_extract_registrar(self):
        xlsx = _xlsx_bytes([
            ["Domain", "Registrar"],
            ["reg.com", "My Registrar"],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        assert result.accepted[0].registrar == "My Registrar"

    def test_xlsx_extract_nameservers(self):
        xlsx = _xlsx_bytes([
            ["Domain", "Nameservers"],
            ["ns.com", "ns1.ns.com ns2.ns.com"],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        ns = result.accepted[0].assigned_nameservers
        assert "ns1.ns.com" in ns and "ns2.ns.com" in ns

    def test_xlsx_dedupe(self):
        xlsx = _xlsx_bytes([
            ["Domain"],
            ["dup.com"],
            ["dup.com"],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        assert len(result.accepted) == 1
        assert len(result.duplicates) == 1

    def test_xlsx_missing_age_bucket_unk(self):
        xlsx = _xlsx_bytes([
            ["Domain", "Create Date"],
            ["no-date.com", ""],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        assert result.accepted[0].age_bucket == AgeBucket.UNKNOWN

    def test_xlsx_invalid_domain_rejected(self):
        xlsx = _xlsx_bytes([
            ["Domain"],
            ["!!not-valid!!"],
        ])
        result = parse_upload(xlsx, "test.xlsx")
        assert len(result.accepted) == 0
        assert len(result.rejected) == 1


# ── upload-preview endpoint ───────────────────────────────────────────────────

class TestUploadPreviewEndpoint:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def test_upload_preview_csv(self, client):
        data = FIXTURES / "sample_dns_form.csv"
        r = client.post(
            "/api/mdi/jobs/upload-preview",
            files={"file": ("sample_dns_form.csv", data.read_bytes(), "text/csv")},
            data={"default_scheme": "http", "max_items": "500"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["accepted_count"] > 0
        assert body["external_calls_made"] is False
        assert body["quota_consumed"] is False

    def test_upload_preview_xlsx(self, client):
        xlsx = _xlsx_bytes([
            ["DNS Form", "EPP Status"],
            ["example.com", "clientHold"],
            ["clean.net", "clientTransferProhibited"],
        ])
        r = client.post(
            "/api/mdi/jobs/upload-preview",
            files={"file": ("test.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"default_scheme": "http", "max_items": "500"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["accepted_count"] == 2
        assert body["held_count"] == 1

    def test_upload_preview_held_items_count(self, client):
        data = FIXTURES / "sample_dns_form.csv"
        r = client.post(
            "/api/mdi/jobs/upload-preview",
            files={"file": ("sample_dns_form.csv", data.read_bytes(), "text/csv")},
            data={"default_scheme": "http"},
        )
        body = r.json()
        # phishing.net (clientHold) and double-held.org (both holds) are held
        assert body["held_count"] >= 2
        held_norms = [h["input_normalized"] for h in body["held_items"]]
        assert "phishing.net" in held_norms
        assert "double-held.org" in held_norms

    def test_upload_preview_external_calls_false(self, client):
        xlsx = _xlsx_bytes([["Domain"], ["example.com"]])
        r = client.post(
            "/api/mdi/jobs/upload-preview",
            files={"file": ("t.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={},
        )
        assert r.json()["external_calls_made"] is False
        assert r.json()["quota_consumed"] is False

    def test_upload_preview_does_not_touch_vt_file(self, client):
        live_path = Path("/var/lib/dns-tool/vt_usage.json")
        mtime_before = live_path.stat().st_mtime if live_path.exists() else None
        data = FIXTURES / "sample_dns_form.csv"
        client.post(
            "/api/mdi/jobs/upload-preview",
            files={"file": ("sample_dns_form.csv", data.read_bytes(), "text/csv")},
            data={},
        )
        mtime_after = live_path.stat().st_mtime if live_path.exists() else None
        assert mtime_before == mtime_after

    def test_parse_preview_still_works(self, client):
        r = client.post("/api/mdi/jobs/parse-preview",
                        json={"raw_input": "example.com\nhttps://example.net/path"})
        assert r.status_code == 200
        assert r.json()["accepted_count"] == 2

    def test_health_still_works(self, client):
        r = client.get("/api/mdi/health")
        assert r.status_code == 200

    def test_no_network_calls_during_upload(self, client):
        import socket
        call_log = []
        orig = socket.getaddrinfo
        def patched(*a, **kw):
            call_log.append(a)
            return orig(*a, **kw)
        socket.getaddrinfo = patched
        try:
            data = FIXTURES / "sample_dns_form.csv"
            client.post(
                "/api/mdi/jobs/upload-preview",
                files={"file": ("s.csv", data.read_bytes(), "text/csv")},
                data={},
            )
        finally:
            socket.getaddrinfo = orig
        assert call_log == [], f"Unexpected network calls: {call_log}"
