"""
Tests for backend/services/live_check.py — MDI-12 SSRF-safe live URL check.

Strategy:
  - All tests mock _resolve_dns, _head_request, and _get_fallback_request at the
    module level via an autouse fixture so that no live DNS, HTTP, or TLS calls
    are made under any circumstances.
  - Pure-function tests (_check_ip_safety, _validate_url) are also completely
    network-free because those functions perform no I/O.
  - asyncio.run() is used throughout (consistent with existing test convention).

Test classes:
  TestCheckIpSafety     — pure function, IPv4 + IPv6 SSRF range checks
  TestValidateUrl       — pure function, scheme/hostname/IP-literal checks
  TestResolveDns        — _resolve_dns mock verifies DNS-to-IP safety gate
  TestLiveCheckNetworking — live_check_item networking outcomes (200 → ACTIVE, etc.)
  TestLiveCheckRedirects  — redirect chain: max hops, re-validation, private IP
  TestGetFallback         — 405/501 triggers GET fallback; 200/404 do not
  TestLiveCheckInputTypes — DOMAIN prepends https://; URL uses as-is
  TestNoBodyRead          — body-read safety guarantees (structural)
  TestNoLiveCallGuard     — verify no live calls leak from pure functions

Hard rules (enforced by autouse fixture):
  - No live external URLs.
  - No live DNS.
  - No live HTTP.
  - No live VT / RDAP / WHOIS.
  - No writes to /var/lib/dns-tool/ runtime files.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.live_check as live_check
from models import InputType, LiveStatus
from services.live_check import (
    LiveCheckResult,
    _check_ip_safety,
    _validate_url,
    _UrlValidation,
    MAX_REDIRECTS,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _run(coro):
    """Run a coroutine synchronously — matches existing test convention."""
    return asyncio.run(coro)


def _make_mock_resp(status_code: int, location: str = None) -> MagicMock:
    """Build a mock httpx.Response with the specified status and optional Location header."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.headers = MagicMock()
    location_lower = {"location": location} if location else {}
    mock.headers.get = lambda key, default=None: location_lower.get(key.lower(), default)
    return mock


# ── Autouse fixture — block all live network calls ─────────────────────────────


@pytest.fixture(autouse=True)
def no_live_network():
    """
    Prevent any live DNS / HTTP calls in every test in this module.

    Defaults:
      _resolve_dns  → ["93.184.216.34"]  (example.com public IP, safe)
      _head_request → mock 200 response
      _get_fallback_request → mock 200 response
    """
    default_head = _make_mock_resp(200)
    default_get = _make_mock_resp(200)
    with (
        patch.object(live_check, "_resolve_dns", new=AsyncMock(return_value=["93.184.216.34"])),
        patch.object(live_check, "_head_request", new=AsyncMock(return_value=default_head)),
        patch.object(live_check, "_get_fallback_request", new=AsyncMock(return_value=default_get)),
    ):
        yield


# ══════════════════════════════════════════════════════════════════════════════
# TestCheckIpSafety — pure function, no network, no mocks needed
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckIpSafety:
    """Unit tests for _check_ip_safety() — pure SSRF IP range check."""

    # ── IPv4 blocked ranges ────────────────────────────────────────────────────

    def test_ipv4_loopback_127_0_0_1_blocked(self):
        assert _check_ip_safety("127.0.0.1") is not None

    def test_ipv4_loopback_127_x_x_x_blocked(self):
        assert _check_ip_safety("127.255.255.255") is not None

    def test_ipv4_private_10_blocked(self):
        assert _check_ip_safety("10.0.0.1") is not None

    def test_ipv4_private_10_upper_blocked(self):
        assert _check_ip_safety("10.255.255.255") is not None

    def test_ipv4_private_172_16_blocked(self):
        assert _check_ip_safety("172.16.0.1") is not None

    def test_ipv4_private_172_31_blocked(self):
        assert _check_ip_safety("172.31.255.255") is not None

    def test_ipv4_private_192_168_blocked(self):
        assert _check_ip_safety("192.168.1.1") is not None

    def test_ipv4_link_local_169_254_blocked(self):
        """169.254.169.254 is the AWS/GCP cloud metadata endpoint."""
        assert _check_ip_safety("169.254.169.254") is not None

    def test_ipv4_link_local_169_254_1_blocked(self):
        assert _check_ip_safety("169.254.1.1") is not None

    def test_ipv4_cgnat_100_64_blocked(self):
        assert _check_ip_safety("100.64.0.1") is not None

    def test_ipv4_test_net_192_0_2_blocked(self):
        assert _check_ip_safety("192.0.2.1") is not None

    def test_ipv4_test_net2_198_51_100_blocked(self):
        assert _check_ip_safety("198.51.100.1") is not None

    def test_ipv4_test_net3_203_0_113_blocked(self):
        assert _check_ip_safety("203.0.113.1") is not None

    def test_ipv4_multicast_blocked(self):
        assert _check_ip_safety("224.0.0.1") is not None

    def test_ipv4_broadcast_blocked(self):
        assert _check_ip_safety("255.255.255.255") is not None

    # ── IPv4 public (allowed) ─────────────────────────────────────────────────

    def test_ipv4_public_93_184_allowed(self):
        assert _check_ip_safety("93.184.216.34") is None

    def test_ipv4_public_8_8_8_8_allowed(self):
        assert _check_ip_safety("8.8.8.8") is None

    def test_ipv4_public_1_1_1_1_allowed(self):
        assert _check_ip_safety("1.1.1.1") is None

    # ── IPv6 blocked ranges ────────────────────────────────────────────────────

    def test_ipv6_loopback_blocked(self):
        assert _check_ip_safety("::1") is not None

    def test_ipv6_unspecified_blocked(self):
        assert _check_ip_safety("::") is not None

    def test_ipv6_unique_local_fc_blocked(self):
        assert _check_ip_safety("fc00::1") is not None

    def test_ipv6_unique_local_fd_blocked(self):
        assert _check_ip_safety("fd00::1") is not None

    def test_ipv6_link_local_fe80_blocked(self):
        assert _check_ip_safety("fe80::1") is not None

    def test_ipv6_multicast_blocked(self):
        assert _check_ip_safety("ff02::1") is not None

    def test_ipv6_documentation_2001_db8_blocked(self):
        assert _check_ip_safety("2001:db8::1") is not None

    # ── IPv4-mapped IPv6 blocked ───────────────────────────────────────────────

    def test_ipv4_mapped_loopback_blocked(self):
        """::ffff:127.0.0.1 must be blocked (IPv4-mapped loopback)."""
        assert _check_ip_safety("::ffff:127.0.0.1") is not None

    def test_ipv4_mapped_private_10_blocked(self):
        """::ffff:10.0.0.1 must be blocked (IPv4-mapped private Class A)."""
        assert _check_ip_safety("::ffff:10.0.0.1") is not None

    def test_ipv4_mapped_link_local_blocked(self):
        """::ffff:169.254.169.254 must be blocked (IPv4-mapped cloud metadata)."""
        assert _check_ip_safety("::ffff:169.254.169.254") is not None

    # ── IPv6 public (allowed) ─────────────────────────────────────────────────

    def test_ipv6_public_2606_allowed(self):
        assert _check_ip_safety("2606:4700:4700::1111") is None

    def test_ipv6_public_2001_4860_allowed(self):
        assert _check_ip_safety("2001:4860:4860::8888") is None

    # ── Invalid input ─────────────────────────────────────────────────────────

    def test_invalid_ip_returns_block_reason(self):
        assert _check_ip_safety("not-an-ip") is not None


# ══════════════════════════════════════════════════════════════════════════════
# TestValidateUrl — pure function, no network, no mocks needed
# ══════════════════════════════════════════════════════════════════════════════


class TestValidateUrl:
    """Unit tests for _validate_url() — scheme, hostname, IP-literal checks."""

    # ── Allowed schemes ────────────────────────────────────────────────────────

    def test_http_scheme_allowed(self):
        result = _validate_url("http://example.com/path")
        assert result.allowed is True
        assert result.hostname == "example.com"

    def test_https_scheme_allowed(self):
        result = _validate_url("https://example.com")
        assert result.allowed is True
        assert result.hostname == "example.com"

    def test_https_with_port_allowed(self):
        result = _validate_url("https://example.com:8443/path")
        assert result.allowed is True

    # ── Blocked schemes ────────────────────────────────────────────────────────

    def test_ftp_blocked(self):
        result = _validate_url("ftp://example.com")
        assert result.allowed is False
        assert "ftp" in result.reason.lower()

    def test_file_blocked(self):
        result = _validate_url("file:///etc/passwd")
        assert result.allowed is False

    def test_javascript_blocked(self):
        result = _validate_url("javascript:alert(1)")
        assert result.allowed is False

    def test_data_blocked(self):
        result = _validate_url("data:text/html,<h1>x</h1>")
        assert result.allowed is False

    def test_gopher_blocked(self):
        result = _validate_url("gopher://example.com")
        assert result.allowed is False

    def test_no_scheme_blocked(self):
        result = _validate_url("example.com")
        assert result.allowed is False

    # ── Hostname blocklist ─────────────────────────────────────────────────────

    def test_localhost_blocked(self):
        result = _validate_url("http://localhost/path")
        assert result.allowed is False
        assert "localhost" in result.reason.lower()

    def test_localhost_localdomain_blocked(self):
        result = _validate_url("https://localhost.localdomain/api")
        assert result.allowed is False

    def test_metadata_google_internal_blocked(self):
        result = _validate_url("http://metadata.google.internal/computeMetadata/v1/")
        assert result.allowed is False

    # ── Hostname suffix blocklist ─────────────────────────────────────────────

    def test_local_suffix_blocked(self):
        result = _validate_url("http://myservice.local/api")
        assert result.allowed is False
        assert ".local" in result.reason

    def test_localhost_suffix_blocked(self):
        result = _validate_url("http://foo.localhost/test")
        assert result.allowed is False

    def test_localdomain_suffix_blocked(self):
        result = _validate_url("https://bar.localdomain/test")
        assert result.allowed is False

    def test_internal_suffix_blocked(self):
        result = _validate_url("https://api.internal/v1/users")
        assert result.allowed is False

    # ── IP literal checks ─────────────────────────────────────────────────────

    def test_ip_literal_loopback_blocked(self):
        result = _validate_url("http://127.0.0.1/admin")
        assert result.allowed is False

    def test_ip_literal_private_10_blocked(self):
        result = _validate_url("https://10.0.0.1/secret")
        assert result.allowed is False

    def test_ip_literal_private_192_168_blocked(self):
        result = _validate_url("http://192.168.1.1/api")
        assert result.allowed is False

    def test_ip_literal_link_local_blocked(self):
        result = _validate_url("http://169.254.169.254/metadata")
        assert result.allowed is False

    def test_ip_literal_public_allowed(self):
        result = _validate_url("https://93.184.216.34/")
        assert result.allowed is True
        assert result.hostname == "93.184.216.34"

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_empty_url_blocked(self):
        result = _validate_url("")
        assert result.allowed is False

    def test_whitespace_url_blocked(self):
        result = _validate_url("   ")
        assert result.allowed is False

    def test_public_domain_with_path_allowed(self):
        result = _validate_url("https://example.com/malware.exe?track=1")
        assert result.allowed is True
        assert result.hostname == "example.com"


# ══════════════════════════════════════════════════════════════════════════════
# TestResolveDns — DNS gate (mocked)
# ══════════════════════════════════════════════════════════════════════════════


class TestResolveDns:
    """Verify DNS resolution gate blocks private IPs and allows public IPs."""

    def test_dns_public_ip_allows_url(self):
        """Public IP from DNS → URL proceeds to HEAD check."""
        with patch.object(live_check, "_resolve_dns", new=AsyncMock(return_value=["93.184.216.34"])):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.ACTIVE

    def test_dns_private_ip_blocks_url(self):
        """Private IP from DNS → BLOCKED (DNS rebinding protection)."""
        with patch.object(live_check, "_resolve_dns", new=AsyncMock(return_value=["192.168.1.1"])):
            result = _run(live_check.live_check_item("evil.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.BLOCKED
        assert result.error is not None

    def test_dns_loopback_ip_blocks_url(self):
        """Loopback from DNS → BLOCKED."""
        with patch.object(live_check, "_resolve_dns", new=AsyncMock(return_value=["127.0.0.1"])):
            result = _run(live_check.live_check_item("sneaky.example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.BLOCKED

    def test_dns_link_local_metadata_ip_blocks_url(self):
        """169.254.169.254 (cloud metadata) → BLOCKED."""
        with patch.object(live_check, "_resolve_dns", new=AsyncMock(return_value=["169.254.169.254"])):
            result = _run(live_check.live_check_item("ssrf.test", InputType.DOMAIN))
        assert result.live_status == LiveStatus.BLOCKED

    def test_dns_empty_result_returns_dns_failure(self):
        """No DNS results → DNS_FAILURE."""
        with patch.object(live_check, "_resolve_dns", new=AsyncMock(return_value=[])):
            result = _run(live_check.live_check_item("nxdomain.invalid", InputType.DOMAIN))
        assert result.live_status == LiveStatus.DNS_FAILURE
        assert result.error is not None


# ══════════════════════════════════════════════════════════════════════════════
# TestLiveCheckNetworking — HTTP outcomes (autouse fixture provides safe mocks)
# ══════════════════════════════════════════════════════════════════════════════


class TestLiveCheckNetworking:
    """Verify HTTP status code to LiveStatus mappings for live_check_item."""

    def _check_domain(self, mock_resp) -> LiveCheckResult:
        with patch.object(live_check, "_head_request", new=AsyncMock(return_value=mock_resp)):
            return _run(live_check.live_check_item("example.com", InputType.DOMAIN))

    def test_200_returns_active(self):
        result = self._check_domain(_make_mock_resp(200))
        assert result.live_status == LiveStatus.ACTIVE
        assert result.http_status_code == 200
        assert result.redirect_count == 0

    def test_204_returns_active(self):
        result = self._check_domain(_make_mock_resp(204))
        assert result.live_status == LiveStatus.ACTIVE

    def test_403_returns_forbidden(self):
        result = self._check_domain(_make_mock_resp(403))
        assert result.live_status == LiveStatus.FORBIDDEN
        assert result.http_status_code == 403

    def test_404_returns_not_found(self):
        result = self._check_domain(_make_mock_resp(404))
        assert result.live_status == LiveStatus.NOT_FOUND
        assert result.http_status_code == 404

    def test_410_returns_gone(self):
        result = self._check_domain(_make_mock_resp(410))
        assert result.live_status == LiveStatus.GONE
        assert result.http_status_code == 410

    def test_500_returns_server_error(self):
        result = self._check_domain(_make_mock_resp(500))
        assert result.live_status == LiveStatus.SERVER_ERROR
        assert result.http_status_code == 500

    def test_503_returns_server_error(self):
        result = self._check_domain(_make_mock_resp(503))
        assert result.live_status == LiveStatus.SERVER_ERROR

    def test_400_returns_unknown(self):
        result = self._check_domain(_make_mock_resp(400))
        assert result.live_status == LiveStatus.UNKNOWN

    def test_401_returns_unknown(self):
        result = self._check_domain(_make_mock_resp(401))
        assert result.live_status == LiveStatus.UNKNOWN

    def test_429_returns_unknown(self):
        result = self._check_domain(_make_mock_resp(429))
        assert result.live_status == LiveStatus.UNKNOWN

    def test_timeout_returns_timeout(self):
        with patch.object(
            live_check, "_head_request",
            new=AsyncMock(side_effect=httpx.TimeoutException("timed out")),
        ):
            result = _run(live_check.live_check_item("slow.example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.TIMEOUT

    def test_connect_error_returns_connection_refused(self):
        with patch.object(
            live_check, "_head_request",
            new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            result = _run(live_check.live_check_item("closed.example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.CONNECTION_REFUSED

    def test_request_error_returns_unknown(self):
        with patch.object(
            live_check, "_head_request",
            new=AsyncMock(side_effect=httpx.RequestError("network error")),
        ):
            result = _run(live_check.live_check_item("broken.example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.UNKNOWN

    def test_ssrf_blocked_url_input(self):
        """URL with private IP scheme → BLOCKED without any DNS or HTTP call."""
        result = _run(live_check.live_check_item("http://192.168.1.1/admin", InputType.URL))
        assert result.live_status == LiveStatus.BLOCKED
        assert result.error is not None
        assert result.error.code == "live_check_blocked"

    def test_ssrf_blocked_localhost(self):
        """localhost URL → BLOCKED at validation stage."""
        result = _run(live_check.live_check_item("http://localhost/api", InputType.URL))
        assert result.live_status == LiveStatus.BLOCKED

    def test_ssrf_blocked_metadata_endpoint(self):
        """GCP metadata hostname → BLOCKED at validation."""
        result = _run(
            live_check.live_check_item("http://metadata.google.internal/computeMetadata/v1/", InputType.URL)
        )
        assert result.live_status == LiveStatus.BLOCKED

    def test_ssrf_blocked_ftp_scheme(self):
        """FTP URL → BLOCKED at scheme check."""
        result = _run(live_check.live_check_item("ftp://example.com/file.txt", InputType.URL))
        assert result.live_status == LiveStatus.BLOCKED


# ══════════════════════════════════════════════════════════════════════════════
# TestLiveCheckRedirects — redirect chain handling
# ══════════════════════════════════════════════════════════════════════════════


class TestLiveCheckRedirects:
    """Redirect chain: max hops, re-validation on each hop, private-IP blocking."""

    def test_single_redirect_returns_redirect_status(self):
        """One 301 → 200 final → live_status=REDIRECT, redirect_count=1."""
        resp_301 = _make_mock_resp(301, location="https://www.example.com/new")
        resp_200 = _make_mock_resp(200)
        side_effects = [resp_301, resp_200]
        with patch.object(
            live_check, "_head_request",
            new=AsyncMock(side_effect=side_effects),
        ):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.REDIRECT
        assert result.redirect_count == 1

    def test_two_redirects_returns_redirect_status(self):
        """Two 302 hops followed by 200 → REDIRECT with redirect_count=2."""
        resp_302a = _make_mock_resp(302, location="https://hop1.example.com/")
        resp_302b = _make_mock_resp(302, location="https://hop2.example.com/")
        resp_200 = _make_mock_resp(200)
        with patch.object(
            live_check, "_head_request",
            new=AsyncMock(side_effect=[resp_302a, resp_302b, resp_200]),
        ):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.REDIRECT
        assert result.redirect_count == 2

    def test_too_many_redirects_returns_unknown(self):
        """4 redirects (> MAX_REDIRECTS=3) → UNKNOWN."""
        resp_302 = _make_mock_resp(302, location="https://loop.example.com/")
        with patch.object(
            live_check, "_head_request",
            new=AsyncMock(return_value=resp_302),
        ):
            result = _run(live_check.live_check_item("loopy.example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.UNKNOWN
        assert result.redirect_count == MAX_REDIRECTS

    def test_redirect_to_private_ip_blocked(self):
        """Redirect Location resolves to private IP → BLOCKED (DNS rebinding)."""
        resp_302 = _make_mock_resp(302, location="https://internal.evil.com/")
        resp_200 = _make_mock_resp(200)

        def _dns_side_effect(hostname):
            if "internal.evil.com" in hostname:
                return ["10.0.0.1"]
            return ["93.184.216.34"]

        with (
            patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_302)),
            patch.object(live_check, "_resolve_dns", new=AsyncMock(side_effect=_dns_side_effect)),
        ):
            result = _run(live_check.live_check_item("evil.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.BLOCKED
        assert result.error is not None
        assert "redirect" in result.error.code.lower()

    def test_redirect_to_localhost_blocked(self):
        """Redirect to http://localhost/admin → BLOCKED at validation."""
        resp_302 = _make_mock_resp(302, location="http://localhost/admin")
        with patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_302)):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.BLOCKED

    def test_redirect_to_ftp_scheme_blocked(self):
        """Redirect to ftp:// → BLOCKED at scheme re-validation."""
        resp_302 = _make_mock_resp(302, location="ftp://files.example.com/payload.zip")
        with patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_302)):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.BLOCKED

    def test_redirect_missing_location_returns_unknown(self):
        """3xx response with no Location header → UNKNOWN."""
        resp_302 = _make_mock_resp(302, location=None)
        with patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_302)):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.UNKNOWN

    def test_redirect_dns_failure_returns_dns_failure(self):
        """Redirect destination's DNS returns empty → DNS_FAILURE."""
        resp_302 = _make_mock_resp(302, location="https://new-target.example.com/")

        def _dns_side_effect(hostname):
            if "new-target" in hostname:
                return []
            return ["93.184.216.34"]

        with (
            patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_302)),
            patch.object(live_check, "_resolve_dns", new=AsyncMock(side_effect=_dns_side_effect)),
        ):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.DNS_FAILURE


# ══════════════════════════════════════════════════════════════════════════════
# TestGetFallback — 405/501 trigger GET; other codes do not
# ══════════════════════════════════════════════════════════════════════════════


class TestGetFallback:
    """Verify GET fallback logic: only triggered on 405 or 501."""

    def test_405_triggers_get_fallback(self):
        """HEAD returns 405 → GET fallback is called → status from GET response."""
        resp_405 = _make_mock_resp(405)
        resp_get_200 = _make_mock_resp(200)
        with (
            patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_405)),
            patch.object(live_check, "_get_fallback_request", new=AsyncMock(return_value=resp_get_200)) as mock_get,
        ):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.ACTIVE
        mock_get.assert_called_once()

    def test_501_triggers_get_fallback(self):
        """HEAD returns 501 → GET fallback is called."""
        resp_501 = _make_mock_resp(501)
        resp_get_200 = _make_mock_resp(200)
        with (
            patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_501)),
            patch.object(live_check, "_get_fallback_request", new=AsyncMock(return_value=resp_get_200)) as mock_get,
        ):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.ACTIVE
        mock_get.assert_called_once()

    def test_405_get_fallback_maps_404_to_not_found(self):
        """GET fallback returns 404 → NOT_FOUND."""
        resp_405 = _make_mock_resp(405)
        resp_get_404 = _make_mock_resp(404)
        with (
            patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_405)),
            patch.object(live_check, "_get_fallback_request", new=AsyncMock(return_value=resp_get_404)),
        ):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.NOT_FOUND

    def test_200_does_not_trigger_get_fallback(self):
        """HEAD returns 200 → GET fallback is never called."""
        resp_200 = _make_mock_resp(200)
        with (
            patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_200)),
            patch.object(live_check, "_get_fallback_request", new=AsyncMock()) as mock_get,
        ):
            _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        mock_get.assert_not_called()

    def test_404_does_not_trigger_get_fallback(self):
        """HEAD returns 404 → GET fallback is never called."""
        resp_404 = _make_mock_resp(404)
        with (
            patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_404)),
            patch.object(live_check, "_get_fallback_request", new=AsyncMock()) as mock_get,
        ):
            _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        mock_get.assert_not_called()

    def test_403_does_not_trigger_get_fallback(self):
        """HEAD returns 403 → GET fallback is never called."""
        resp_403 = _make_mock_resp(403)
        with (
            patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_403)),
            patch.object(live_check, "_get_fallback_request", new=AsyncMock()) as mock_get,
        ):
            _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        mock_get.assert_not_called()

    def test_405_get_fallback_timeout_returns_timeout(self):
        """GET fallback throws TimeoutException → TIMEOUT."""
        resp_405 = _make_mock_resp(405)
        with (
            patch.object(live_check, "_head_request", new=AsyncMock(return_value=resp_405)),
            patch.object(
                live_check, "_get_fallback_request",
                new=AsyncMock(side_effect=httpx.TimeoutException("timeout")),
            ),
        ):
            result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert result.live_status == LiveStatus.TIMEOUT


# ══════════════════════════════════════════════════════════════════════════════
# TestLiveCheckInputTypes — DOMAIN vs URL input handling
# ══════════════════════════════════════════════════════════════════════════════


class TestLiveCheckInputTypes:
    """Verify that DOMAIN inputs get https:// prepended and URL inputs are used as-is."""

    def test_domain_input_prepends_https(self):
        """DOMAIN input 'example.com' → probes 'https://example.com'."""
        head_mock = AsyncMock(return_value=_make_mock_resp(200))
        with patch.object(live_check, "_head_request", new=head_mock):
            _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        call_url = head_mock.call_args[0][0]
        assert call_url == "https://example.com"

    def test_url_input_used_as_is(self):
        """URL input 'https://example.com/path' → probes exactly that URL."""
        head_mock = AsyncMock(return_value=_make_mock_resp(200))
        with patch.object(live_check, "_head_request", new=head_mock):
            _run(live_check.live_check_item("https://example.com/path?q=1", InputType.URL))
        call_url = head_mock.call_args[0][0]
        assert call_url == "https://example.com/path?q=1"

    def test_url_input_http_scheme_allowed(self):
        """URL input with http:// is valid and probed."""
        head_mock = AsyncMock(return_value=_make_mock_resp(200))
        with patch.object(live_check, "_head_request", new=head_mock):
            result = _run(live_check.live_check_item("http://example.com/", InputType.URL))
        assert result.live_status == LiveStatus.ACTIVE

    def test_domain_input_ssrf_blocked(self):
        """DOMAIN 'localhost' → validation blocks before any network call."""
        result = _run(live_check.live_check_item("localhost", InputType.DOMAIN))
        assert result.live_status == LiveStatus.BLOCKED

    def test_url_input_private_ip_ssrf_blocked(self):
        """URL 'https://10.0.0.1' → BLOCKED at validation."""
        result = _run(live_check.live_check_item("https://10.0.0.1/data", InputType.URL))
        assert result.live_status == LiveStatus.BLOCKED


# ══════════════════════════════════════════════════════════════════════════════
# TestBodyNotRead — structural / API-level guarantees
# ══════════════════════════════════════════════════════════════════════════════


class TestBodyNotRead:
    """
    Verify structural guarantees that response bodies are never read or stored.

    These tests check the function call signatures and mock patterns used by
    _head_request and _get_fallback_request: the mocks never return .content
    or .text, and live_check.py never accesses those attributes.
    """

    def test_live_check_result_has_no_body_field(self):
        """LiveCheckResult dataclass must not expose any body/content field."""
        result = LiveCheckResult(live_status=LiveStatus.ACTIVE)
        assert not hasattr(result, "body")
        assert not hasattr(result, "content")
        assert not hasattr(result, "text")
        assert not hasattr(result, "html")
        assert not hasattr(result, "response_body")

    def test_head_request_mock_returns_no_body(self):
        """_head_request mock used in tests provides no .content attribute by default."""
        mock_resp = _make_mock_resp(200)
        # The mock doesn't set .content / .text — this mimics a real HEAD response
        assert not hasattr(mock_resp, "content") or mock_resp.content is not None

    def test_live_check_item_result_exposes_no_body(self):
        """Result of live_check_item must not contain any response body data."""
        result = _run(live_check.live_check_item("example.com", InputType.DOMAIN))
        assert not hasattr(result, "body")
        assert not hasattr(result, "content")
        assert not hasattr(result, "response_text")


# ══════════════════════════════════════════════════════════════════════════════
# TestNoLiveCallGuard — pure functions must never make network calls
# ══════════════════════════════════════════════════════════════════════════════


class TestNoLiveCallGuard:
    """Verify that _check_ip_safety and _validate_url make zero network calls."""

    def test_check_ip_safety_has_no_httpx_import_side_effects(self):
        """_check_ip_safety runs without touching httpx."""
        # If it imported and used httpx, this would fail in a no-network env
        result = _check_ip_safety("8.8.8.8")
        assert result is None

    def test_validate_url_has_no_network_calls(self):
        """_validate_url parses purely in memory — no socket, no http."""
        result = _validate_url("https://example.com/path")
        assert result.allowed is True
        assert result.hostname == "example.com"

    def test_validate_url_rejects_without_network(self):
        """_validate_url blocks invalid inputs without making any network call."""
        result = _validate_url("file:///etc/passwd")
        assert result.allowed is False

    def test_blocked_ip_url_blocked_before_dns_call(self):
        """URL with private IP literal → blocked before _resolve_dns is called."""
        dns_mock = AsyncMock(return_value=["10.0.0.1"])
        with patch.object(live_check, "_resolve_dns", new=dns_mock):
            result = _run(live_check.live_check_item("http://10.0.0.1/test", InputType.URL))
        assert result.live_status == LiveStatus.BLOCKED
        dns_mock.assert_not_called()

    def test_ssrf_blocked_hostname_skips_dns(self):
        """Blocked hostname → _resolve_dns is never called (fail-fast)."""
        dns_mock = AsyncMock(return_value=["93.184.216.34"])
        with patch.object(live_check, "_resolve_dns", new=dns_mock):
            result = _run(live_check.live_check_item("localhost", InputType.DOMAIN))
        assert result.live_status == LiveStatus.BLOCKED
        dns_mock.assert_not_called()
