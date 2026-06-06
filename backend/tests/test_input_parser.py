"""
Tests for backend/services/input_parser.py and POST /api/mdi/jobs/parse-preview.

All tests are purely local — no network, no DNS, no VT, no WHOIS, no runtime files.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import InputType
from services.input_parser import (
    DEFAULT_MAX_ITEMS,
    ParseResult,
    normalize_token,
    parse_raw_input,
)


# ── normalize_token ────────────────────────────────────────────────────────────

class TestNormalizeToken:

    # ── Bare domains ──────────────────────────────────────────────────────────

    def test_bare_domain(self):
        norm, itype = normalize_token("example.com")
        assert norm == "example.com"
        assert itype == InputType.DOMAIN

    def test_bare_domain_uppercase(self):
        norm, itype = normalize_token("EXAMPLE.COM")
        assert norm == "example.com"
        assert itype == InputType.DOMAIN

    def test_bare_domain_subdomain(self):
        norm, _ = normalize_token("sub.example.com")
        assert norm == "sub.example.com"

    def test_bare_domain_trailing_fqdn_dot(self):
        norm, itype = normalize_token("example.com.")
        assert norm == "example.com"
        assert itype == InputType.DOMAIN

    def test_bare_domain_single_label(self):
        norm, itype = normalize_token("localhost")
        assert norm == "localhost"
        assert itype == InputType.DOMAIN

    def test_bare_ipv4(self):
        norm, itype = normalize_token("192.168.1.1")
        assert norm == "192.168.1.1"
        assert itype == InputType.DOMAIN

    # ── Full URLs ─────────────────────────────────────────────────────────────

    def test_full_https_url(self):
        norm, itype = normalize_token("https://example.com/path")
        assert norm == "https://example.com/path"
        assert itype == InputType.URL

    def test_full_http_url(self):
        norm, itype = normalize_token("http://example.com/path")
        assert norm == "http://example.com/path"
        assert itype == InputType.URL

    def test_url_uppercase_host(self):
        norm, itype = normalize_token("https://EXAMPLE.COM/Path")
        assert "example.com" in norm
        assert "/Path" in norm   # path case preserved
        assert itype == InputType.URL

    def test_url_with_query(self):
        norm, itype = normalize_token("https://example.com/search?q=Test&lang=EN")
        assert "example.com" in norm
        assert "q=Test" in norm      # query preserved as-is
        assert itype == InputType.URL

    def test_url_uppercase_scheme_normalised(self):
        # urlparse handles HTTPS:// gracefully
        norm, itype = normalize_token("HTTPS://example.com/")
        assert norm.startswith("https://")
        assert itype == InputType.URL

    # ── domain/path without scheme ────────────────────────────────────────────

    def test_domain_path_no_scheme(self):
        norm, itype = normalize_token("example.com/malware.zip")
        assert norm == "http://example.com/malware.zip"
        assert itype == InputType.URL

    def test_domain_path_uppercase(self):
        norm, itype = normalize_token("EXAMPLE.COM/path")
        assert "example.com" in norm
        assert itype == InputType.URL

    def test_domain_path_with_default_https(self):
        norm, itype = normalize_token("example.com/path", default_scheme="https")
        assert norm.startswith("https://")

    # ── Surrounding stripping ─────────────────────────────────────────────────

    def test_strip_double_quotes(self):
        norm, _ = normalize_token('"example.com"')
        assert norm == "example.com"

    def test_strip_single_quotes(self):
        norm, _ = normalize_token("'example.com'")
        assert norm == "example.com"

    def test_strip_angle_brackets(self):
        norm, _ = normalize_token("<example.com>")
        assert norm == "example.com"

    def test_strip_square_brackets(self):
        norm, _ = normalize_token("[example.com]")
        assert norm == "example.com"

    def test_strip_parens(self):
        norm, _ = normalize_token("(example.com)")
        assert norm == "example.com"

    def test_strip_backticks(self):
        norm, _ = normalize_token("`example.com`")
        assert norm == "example.com"

    def test_strip_surrounding_whitespace(self):
        norm, _ = normalize_token("  example.com  ")
        assert norm == "example.com"

    # ── Rejection cases ───────────────────────────────────────────────────────

    def test_reject_unsupported_scheme_ftp(self):
        with pytest.raises(ValueError, match="unsupported_scheme"):
            normalize_token("ftp://example.com/file")

    def test_reject_unsupported_scheme_file(self):
        with pytest.raises(ValueError, match="unsupported_scheme"):
            normalize_token("file:///etc/passwd")

    def test_reject_empty_after_strip(self):
        with pytest.raises(ValueError):
            normalize_token("")

    def test_reject_token_with_space(self):
        with pytest.raises(ValueError, match="token_contains_space"):
            normalize_token("not a domain")

    def test_reject_clearly_invalid_domain(self):
        with pytest.raises(ValueError):
            normalize_token("!!@@##$$")

    def test_reject_token_too_long(self):
        with pytest.raises(ValueError, match="token_too_long"):
            normalize_token("a" * 2049)


# ── parse_raw_input ────────────────────────────────────────────────────────────

class TestParseRawInput:

    def test_newline_separated(self):
        result = parse_raw_input("example.com\nexample.net")
        assert len(result.accepted) == 2
        assert result.accepted[0].input_normalized == "example.com"
        assert result.accepted[1].input_normalized == "example.net"

    def test_comma_separated(self):
        result = parse_raw_input("example.com,example.net")
        assert len(result.accepted) == 2

    def test_whitespace_separated(self):
        result = parse_raw_input("example.com example.net")
        assert len(result.accepted) == 2

    def test_mixed_delimiters(self):
        result = parse_raw_input("example.com\nexample.net, example.org  example.io")
        assert len(result.accepted) == 4

    def test_dedupe_exact_normalized(self):
        result = parse_raw_input("example.com\nexample.com")
        assert len(result.accepted) == 1
        assert len(result.duplicates) == 1
        assert result.duplicates[0].duplicate_of == "example.com"

    def test_dedupe_case_insensitive_domain(self):
        result = parse_raw_input("Example.COM\nexample.com")
        assert len(result.accepted) == 1
        assert len(result.duplicates) == 1

    def test_dedupe_preserves_first_seen_order(self):
        result = parse_raw_input("b.com\na.com\nb.com\nc.com")
        norms = [item.input_normalized for item in result.accepted]
        assert norms == ["b.com", "a.com", "c.com"]

    def test_position_reflects_raw_order(self):
        result = parse_raw_input("first.com\nsecond.com\nthird.com")
        positions = [item.position for item in result.accepted]
        assert positions == [1, 2, 3]

    def test_url_and_domain_mixed(self):
        result = parse_raw_input("example.com\nhttps://example.net/path")
        assert result.accepted[0].input_type == InputType.DOMAIN
        assert result.accepted[1].input_type == InputType.URL

    def test_invalid_items_go_to_rejected(self):
        result = parse_raw_input("example.com\nftp://bad.com\n!invalid!")
        assert len(result.accepted) == 1
        assert len(result.rejected) == 2
        codes = {r.error.code for r in result.rejected}
        assert "unsupported_scheme" in codes

    def test_empty_input(self):
        result = parse_raw_input("")
        assert len(result.accepted) == 0
        assert len(result.rejected) == 0
        assert len(result.duplicates) == 0

    def test_whitespace_only_input(self):
        result = parse_raw_input("   \n\n  ")
        assert len(result.accepted) == 0

    def test_max_items_enforced(self):
        raw = "\n".join(f"item{i}.com" for i in range(10))
        result = parse_raw_input(raw, max_items=5)
        assert len(result.accepted) == 5
        assert len(result.rejected) == 5
        for r in result.rejected:
            assert r.error.code == "max_items_exceeded"

    def test_input_too_large(self):
        raw = "a" * 100_001
        result = parse_raw_input(raw)
        assert len(result.accepted) == 0
        assert len(result.rejected) == 1
        assert result.rejected[0].error.code == "input_too_large"

    def test_trailing_fqdn_dot_stripped(self):
        result = parse_raw_input("example.com.")
        assert result.accepted[0].input_normalized == "example.com"

    def test_input_original_preserved(self):
        result = parse_raw_input('"Example.COM"')
        assert result.accepted[0].input_original == '"Example.COM"'
        assert result.accepted[0].input_normalized == "example.com"

    def test_no_network_calls(self):
        """
        Confirm parse_raw_input is purely local.
        We verify indirectly by mocking socket — if any network call occurs,
        the mock would raise.  Since no socket mock is needed here (function
        doesn't use it), this test simply documents the contract.
        """
        import socket
        original_getaddrinfo = socket.getaddrinfo
        call_count = []

        def patched(*args, **kwargs):
            call_count.append(args)
            return original_getaddrinfo(*args, **kwargs)

        socket.getaddrinfo = patched
        try:
            parse_raw_input("example.com\nhttps://example.net/path")
        finally:
            socket.getaddrinfo = original_getaddrinfo

        # No network calls should have been made
        assert call_count == [], f"Unexpected network calls: {call_count}"


# ── parse-preview endpoint ─────────────────────────────────────────────────────

class TestParsePreviewEndpoint:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def test_health_still_works(self, client):
        r = client.get("/api/mdi/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_parse_preview_basic(self, client):
        r = client.post("/api/mdi/jobs/parse-preview", json={
            "raw_input": "example.com\nhttps://example.net/path",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["accepted_count"] == 2
        assert data["rejected_count"] == 0
        assert data["duplicate_count"] == 0
        assert data["external_calls_made"] is False
        assert data["quota_consumed"] is False

    def test_parse_preview_deduplication(self, client):
        r = client.post("/api/mdi/jobs/parse-preview", json={
            "raw_input": "example.com\nexample.com\nexample.net",
        })
        data = r.json()
        assert data["accepted_count"] == 2
        assert data["duplicate_count"] == 1

    def test_parse_preview_rejected(self, client):
        r = client.post("/api/mdi/jobs/parse-preview", json={
            "raw_input": "example.com\nftp://bad.com",
        })
        data = r.json()
        assert data["accepted_count"] == 1
        assert data["rejected_count"] == 1
        assert data["rejected"][0]["error"]["code"] == "unsupported_scheme"

    def test_parse_preview_empty(self, client):
        r = client.post("/api/mdi/jobs/parse-preview", json={"raw_input": ""})
        data = r.json()
        assert data["accepted_count"] == 0
        assert data["external_calls_made"] is False
        assert data["quota_consumed"] is False

    def test_parse_preview_does_not_touch_live_vt_file(self, client):
        """Confirm that calling parse-preview does not modify the live VT usage file."""
        import os
        live_path = Path("/var/lib/dns-tool/vt_usage.json")
        mtime_before = live_path.stat().st_mtime if live_path.exists() else None

        client.post("/api/mdi/jobs/parse-preview", json={
            "raw_input": "example.com\nhttps://example.net/path",
        })

        mtime_after = live_path.stat().st_mtime if live_path.exists() else None
        assert mtime_before == mtime_after, (
            "vt_usage.json was modified by parse-preview — this must not happen"
        )

    def test_usage_endpoint_not_mutated(self, client):
        r = client.get("/api/mdi/usage")
        assert r.status_code == 200
        assert r.json()["mutated"] is False

    def test_schema_summary_still_works(self, client):
        r = client.get("/api/mdi/schema-summary")
        assert r.status_code == 200
        assert "InputType" in r.json()["enums"]
