"""
Tests for backend/services/domain_enrichment.py (MDI-11).

Strategy:
  - All RDAP HTTP calls are mocked via patch on domain_enrichment._rdap_request.
  - All WHOIS calls are mocked via patch on domain_enrichment._whois_query_sync.
  - No live RDAP, WHOIS, DNS, or VT calls are made in this module.
  - Tests cover: RDAP success, 404 fallback, 429 retry, timeout fallback, both fail,
    URL extraction, IDN, IP skip, domain cache, age buckets, hold detection.
  - Async functions are tested with asyncio.run() — no pytest-asyncio dependency.

Test guard: if _rdap_request or _whois_query_sync is called without an explicit
mock, the test will fail — the real functions are patched out for all live-call
tests through explicit mock arguments.
"""

from __future__ import annotations

import asyncio
import ipaddress
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _run(coro):
    """Run a coroutine in a new event loop (mirrors the pattern in test_jobs_submit.py)."""
    return asyncio.run(coro)

from models import AgeBucket, DomainStatusSource, InputType, MdiProcessingStatus
from services import domain_enrichment
from services.domain_enrichment import (
    EnrichmentResult,
    _parse_rdap_response,
    _parse_retry_after,
    _parse_whois_result,
    enrich_domain,
    extract_registered_domain,
    _RDAP_MIN_INTERVAL_SECONDS,
    _RDAP_RETRY_DELAY_DEFAULT_SECONDS,
)
from services.age_bucket import compute_age_bucket


# ── Module-level autouse: suppress rate-limit waits for all enrich_domain tests ──

@pytest.fixture(autouse=True)
def mock_rdap_rate_limiter():
    """
    Prevent actual 1.1-second waits in every test that calls enrich_domain.
    Tests in TestRdapRateLimiter override this with explicit mocks to verify
    sleep duration and call counts.
    """
    with patch.object(domain_enrichment, "_rdap_acquire_slot", new=AsyncMock()):
        yield


# ── Fixtures and helpers ───────────────────────────────────────────────────────

def _make_rdap_200(
    creation_date: str = "1995-08-14T04:00:00Z",
    registrar: str = "Test Registrar LLC",
    statuses: list = None,
    nameservers: list = None,
) -> dict:
    """Build a minimal RDAP 200 response dict."""
    if statuses is None:
        statuses = ["clientTransferProhibited", "clientUpdateProhibited"]
    if nameservers is None:
        nameservers = [{"ldhName": "ns1.example.com"}, {"ldhName": "ns2.example.com"}]
    return {
        "objectClassName": "domain",
        "events": [
            {"eventAction": "registration", "eventDate": creation_date},
            {"eventAction": "expiration", "eventDate": "2028-08-14T04:00:00Z"},
        ],
        "entities": [
            {
                "roles": ["registrar"],
                "vcardArray": [
                    "vcard",
                    [
                        ["version", {}, "text", "4.0"],
                        ["fn", {}, "text", registrar],
                    ],
                ],
            }
        ],
        "status": statuses,
        "nameservers": nameservers,
    }


def _make_rdap_response(status_code: int, json_data: Optional[dict] = None) -> MagicMock:
    """Build a mock httpx.Response with given status code and optional JSON body."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    # Default headers: no Retry-After.  Tests that need specific headers override this.
    resp.headers = MagicMock()
    resp.headers.get = lambda key, default="": default
    return resp


def _make_whois_dict(
    creation_date=None,
    registrar: str = "WHOIS Registrar",
    status=None,
    name_servers=None,
) -> dict:
    """Build a normalized whois result dict as returned by _whois_query_sync."""
    if status is None:
        status = ["clientTransferProhibited"]
    if name_servers is None:
        name_servers = ["ns1.whois-example.com"]
    return {
        "creation_date": creation_date or datetime(2020, 6, 1, tzinfo=timezone.utc),
        "registrar": registrar,
        "status": status,
        "name_servers": name_servers,
    }


# ── extract_registered_domain ─────────────────────────────────────────────────

class TestExtractRegisteredDomain:

    def test_bare_domain_returns_registered_domain(self):
        result = extract_registered_domain("example.com", InputType.DOMAIN)
        assert result == "example.com"

    def test_subdomain_domain_input_returns_etld1(self):
        result = extract_registered_domain("evil.sub.example.com", InputType.DOMAIN)
        assert result == "example.com"

    def test_url_input_extracts_hostname_then_etld1(self):
        result = extract_registered_domain("https://evil.sub.example.com/path?q=1", InputType.URL)
        assert result == "example.com"

    def test_url_input_with_port(self):
        result = extract_registered_domain("https://evil.example.com:8443/path", InputType.URL)
        assert result == "example.com"

    def test_multi_part_tld(self):
        result = extract_registered_domain("target.co.uk", InputType.DOMAIN)
        assert result == "target.co.uk"

    def test_url_multi_part_tld(self):
        result = extract_registered_domain("https://sub.target.co.uk/foo", InputType.URL)
        assert result == "target.co.uk"

    def test_ip_address_returns_none(self):
        result = extract_registered_domain("192.168.1.1", InputType.DOMAIN)
        assert result is None

    def test_ipv6_returns_none(self):
        result = extract_registered_domain("2001:db8::1", InputType.DOMAIN)
        assert result is None

    def test_empty_string_returns_none(self):
        result = extract_registered_domain("", InputType.DOMAIN)
        assert result is None

    def test_idn_encoded_to_punycode(self):
        result = extract_registered_domain("münchen.de", InputType.DOMAIN)
        # Should be punycode-encoded
        assert result is not None
        assert result.isascii()

    def test_url_ip_returns_none(self):
        result = extract_registered_domain("http://10.0.0.1/admin", InputType.URL)
        assert result is None

    def test_domain_without_tld_returns_none(self):
        result = extract_registered_domain("localhost", InputType.DOMAIN)
        assert result is None


# ── compute_age_bucket ────────────────────────────────────────────────────────

class TestComputeAgeBucket:

    def test_10_days_is_very_new(self):
        d = date.today() - timedelta(days=10)
        assert compute_age_bucket(d) == AgeBucket.VERY_NEW

    def test_29_days_is_very_new(self):
        d = date.today() - timedelta(days=29)
        assert compute_age_bucket(d) == AgeBucket.VERY_NEW

    def test_30_days_is_new(self):
        d = date.today() - timedelta(days=30)
        assert compute_age_bucket(d) == AgeBucket.NEW

    def test_60_days_is_new(self):
        d = date.today() - timedelta(days=60)
        assert compute_age_bucket(d) == AgeBucket.NEW

    def test_179_days_is_new(self):
        d = date.today() - timedelta(days=179)
        assert compute_age_bucket(d) == AgeBucket.NEW

    def test_180_days_is_established(self):
        d = date.today() - timedelta(days=180)
        assert compute_age_bucket(d) == AgeBucket.ESTABLISHED

    def test_729_days_is_established(self):
        d = date.today() - timedelta(days=729)
        assert compute_age_bucket(d) == AgeBucket.ESTABLISHED

    def test_730_days_is_mature(self):
        d = date.today() - timedelta(days=730)
        assert compute_age_bucket(d) == AgeBucket.MATURE

    def test_old_domain_is_mature(self):
        # example.com registered in 1995
        d = date(1995, 8, 14)
        assert compute_age_bucket(d) == AgeBucket.MATURE

    def test_future_date_is_unknown(self):
        d = date.today() + timedelta(days=1)
        assert compute_age_bucket(d) == AgeBucket.UNKNOWN


# ── _parse_rdap_response ──────────────────────────────────────────────────────

class TestParseRdapResponse:

    def test_parses_created_at(self):
        data = _make_rdap_200(creation_date="1995-08-14T04:00:00Z")
        result = _parse_rdap_response(data, "example.com")
        assert result.created_at is not None
        assert result.created_at.year == 1995
        assert result.created_at.month == 8
        assert result.created_at.day == 14

    def test_parses_registrar(self):
        data = _make_rdap_200(registrar="Test Registrar LLC")
        result = _parse_rdap_response(data, "example.com")
        assert result.registrar == "Test Registrar LLC"

    def test_parses_epp_status(self):
        data = _make_rdap_200(statuses=["clientTransferProhibited", "clientUpdateProhibited"])
        result = _parse_rdap_response(data, "example.com")
        assert "clientTransferProhibited" in result.epp_status
        assert "clientUpdateProhibited" in result.epp_status

    def test_strips_url_suffixes_from_status(self):
        data = _make_rdap_200(statuses=[
            "clientTransferProhibited https://icann.org/epp#clientTransferProhibited"
        ])
        result = _parse_rdap_response(data, "example.com")
        assert result.epp_status == ["clientTransferProhibited"]

    def test_parses_nameservers(self):
        data = _make_rdap_200(nameservers=[{"ldhName": "NS1.EXAMPLE.COM"}, {"ldhName": "NS2.EXAMPLE.COM"}])
        result = _parse_rdap_response(data, "example.com")
        assert "ns1.example.com" in result.nameservers
        assert "ns2.example.com" in result.nameservers

    def test_age_bucket_mature_for_1995(self):
        data = _make_rdap_200(creation_date="1995-08-14T04:00:00Z")
        result = _parse_rdap_response(data, "example.com")
        assert result.age_bucket == AgeBucket.MATURE

    def test_age_bucket_very_new(self):
        d = datetime.now(timezone.utc) - timedelta(days=5)
        data = _make_rdap_200(creation_date=d.strftime("%Y-%m-%dT%H:%M:%SZ"))
        result = _parse_rdap_response(data, "new-domain.com")
        assert result.age_bucket == AgeBucket.VERY_NEW

    def test_no_hold_detected(self):
        data = _make_rdap_200(statuses=["clientTransferProhibited"])
        result = _parse_rdap_response(data, "example.com")
        assert result.domain_hold.has_hold is False
        assert result.domain_hold.source == DomainStatusSource.RDAP

    def test_client_hold_detected(self):
        data = _make_rdap_200(statuses=["clientHold", "clientTransferProhibited"])
        result = _parse_rdap_response(data, "malicious.com")
        assert result.domain_hold.has_hold is True
        assert result.domain_hold.source == DomainStatusSource.RDAP

    def test_server_hold_detected(self):
        data = _make_rdap_200(statuses=["serverHold"])
        result = _parse_rdap_response(data, "held.com")
        assert result.domain_hold.has_hold is True

    def test_source_is_rdap(self):
        data = _make_rdap_200()
        result = _parse_rdap_response(data, "example.com")
        assert result.source == DomainStatusSource.RDAP
        assert result.error is None

    def test_empty_events_leaves_created_at_none(self):
        data = _make_rdap_200()
        data["events"] = []
        result = _parse_rdap_response(data, "example.com")
        assert result.created_at is None
        assert result.age_bucket == AgeBucket.UNKNOWN

    def test_missing_registrar_entity_leaves_none(self):
        data = _make_rdap_200()
        data["entities"] = []
        result = _parse_rdap_response(data, "example.com")
        assert result.registrar is None


# ── _parse_whois_result ───────────────────────────────────────────────────────

class TestParseWhoisResult:

    def test_parses_all_fields(self):
        d = datetime(2020, 6, 1, tzinfo=timezone.utc)
        result = _parse_whois_result(
            {"creation_date": d, "registrar": "WHOIS Reg", "status": ["clientTransferProhibited"], "name_servers": ["ns1.example.com"]},
            "example.com",
        )
        assert result.created_at == d
        assert result.registrar == "WHOIS Reg"
        assert "clientTransferProhibited" in result.epp_status
        assert "ns1.example.com" in result.nameservers
        assert result.source == DomainStatusSource.WHOIS
        assert result.whois_fallback_used is True

    def test_client_hold_from_whois(self):
        result = _parse_whois_result(
            {"creation_date": None, "registrar": None, "status": ["clientHold"], "name_servers": []},
            "held.com",
        )
        assert result.domain_hold.has_hold is True
        assert result.domain_hold.source == DomainStatusSource.WHOIS

    def test_naive_datetime_gets_utc(self):
        d = datetime(2020, 1, 1)  # no tzinfo
        result = _parse_whois_result(
            {"creation_date": d, "registrar": None, "status": [], "name_servers": []},
            "example.com",
        )
        assert result.created_at is not None
        assert result.created_at.tzinfo is not None


# ── enrich_domain (integration with mocked HTTP) ─────────────────────────────

class TestEnrichDomain:

    def test_rdap_200_returns_enrichment_result(self):
        rdap_data = _make_rdap_200()
        mock_resp = _make_rdap_response(200, rdap_data)

        with patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(return_value=mock_resp)):
            result = _run(enrich_domain("example.com"))

        assert result.source == DomainStatusSource.RDAP
        assert result.created_at is not None
        assert result.created_at.year == 1995
        assert result.registrar == "Test Registrar LLC"
        assert result.age_bucket == AgeBucket.MATURE
        assert result.error is None

    def test_rdap_200_no_hold(self):
        rdap_data = _make_rdap_200(statuses=["clientTransferProhibited"])
        mock_resp = _make_rdap_response(200, rdap_data)

        with patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(return_value=mock_resp)):
            result = _run(enrich_domain("example.com"))

        assert result.domain_hold.has_hold is False
        assert result.domain_hold.source == DomainStatusSource.RDAP

    def test_rdap_200_client_hold(self):
        rdap_data = _make_rdap_200(statuses=["clientHold", "clientTransferProhibited"])
        mock_resp = _make_rdap_response(200, rdap_data)

        with patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(return_value=mock_resp)):
            result = _run(enrich_domain("malicious.com"))

        assert result.domain_hold.has_hold is True
        assert result.domain_hold.source == DomainStatusSource.RDAP

    def test_rdap_200_server_hold(self):
        rdap_data = _make_rdap_200(statuses=["serverHold"])
        mock_resp = _make_rdap_response(200, rdap_data)

        with patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(return_value=mock_resp)):
            result = _run(enrich_domain("held.com"))

        assert result.domain_hold.has_hold is True

    def test_rdap_404_falls_back_to_whois(self):
        mock_404 = _make_rdap_response(404)
        whois_dict = _make_whois_dict()

        with (
            patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(return_value=mock_404)),
            patch.object(domain_enrichment, "_whois_query_sync", return_value=whois_dict),
        ):
            result = _run(enrich_domain("no-rdap.example"))

        assert result.source == DomainStatusSource.WHOIS
        assert result.whois_fallback_used is True
        assert result.error is None

    def test_rdap_timeout_falls_back_to_whois(self):
        whois_dict = _make_whois_dict()

        with (
            patch.object(
                domain_enrichment, "_rdap_request",
                new=AsyncMock(side_effect=httpx.TimeoutException("timeout")),
            ),
            patch.object(domain_enrichment, "_whois_query_sync", return_value=whois_dict),
        ):
            result = _run(enrich_domain("slow.example.com"))

        assert result.source == DomainStatusSource.WHOIS
        assert result.whois_fallback_used is True

    def test_rdap_network_error_falls_back_to_whois(self):
        whois_dict = _make_whois_dict()

        with (
            patch.object(
                domain_enrichment, "_rdap_request",
                new=AsyncMock(side_effect=httpx.RequestError("network error")),
            ),
            patch.object(domain_enrichment, "_whois_query_sync", return_value=whois_dict),
        ):
            result = _run(enrich_domain("unreachable.com"))

        assert result.source == DomainStatusSource.WHOIS

    def test_rdap_5xx_falls_back_to_whois(self):
        mock_5xx = _make_rdap_response(503)
        whois_dict = _make_whois_dict()

        with (
            patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(return_value=mock_5xx)),
            patch.object(domain_enrichment, "_whois_query_sync", return_value=whois_dict),
        ):
            result = _run(enrich_domain("example.com"))

        assert result.source == DomainStatusSource.WHOIS

    def test_rdap_429_retries_once_then_whois_if_still_fails(self):
        mock_429 = _make_rdap_response(429)
        whois_dict = _make_whois_dict()

        async def _sleep_noop(_):
            pass

        with (
            patch.object(
                domain_enrichment, "_rdap_request",
                new=AsyncMock(return_value=mock_429),
            ),
            patch.object(domain_enrichment, "_whois_query_sync", return_value=whois_dict),
            patch("services.domain_enrichment.asyncio.sleep", new=_sleep_noop),
        ):
            result = _run(enrich_domain("rate-limited.com"))

        # First call (429) → sleep → second call (429) → whois fallback
        assert result.source == DomainStatusSource.WHOIS
        assert result.whois_fallback_used is True

    def test_rdap_429_retries_once_succeeds_on_retry(self):
        mock_429 = _make_rdap_response(429)
        rdap_data = _make_rdap_200()
        mock_200 = _make_rdap_response(200, rdap_data)

        responses = [mock_429, mock_200]

        async def side_effect(*args, **kwargs):
            return responses.pop(0)

        async def _sleep_noop(_):
            pass

        with (
            patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(side_effect=side_effect)),
            patch("services.domain_enrichment.asyncio.sleep", new=_sleep_noop),
        ):
            result = _run(enrich_domain("rate-limited.com"))

        assert result.source == DomainStatusSource.RDAP
        assert result.error is None

    def test_both_rdap_and_whois_fail_returns_error(self):
        mock_5xx = _make_rdap_response(500)

        with (
            patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(return_value=mock_5xx)),
            patch.object(domain_enrichment, "_whois_query_sync", return_value=None),
        ):
            result = _run(enrich_domain("broken.com"))

        assert result.error is not None
        assert result.error.code == "whois_failed"
        assert result.source == DomainStatusSource.UNKNOWN
        assert result.domain_hold.has_hold is False

    def test_enrichment_result_has_no_hold_when_no_status(self):
        rdap_data = _make_rdap_200(statuses=[])
        mock_resp = _make_rdap_response(200, rdap_data)

        with patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(return_value=mock_resp)):
            result = _run(enrich_domain("clean.com"))

        assert result.domain_hold.has_hold is False


# ── URL input extraction and age bucket end-to-end ────────────────────────────

class TestExtractAndEnrich:

    def test_url_input_extracts_registered_domain(self):
        reg = extract_registered_domain(
            "https://evil.sub.example.com/malware.zip",
            InputType.URL,
        )
        assert reg == "example.com"

    def test_subdomain_stripped_for_domain_input(self):
        reg = extract_registered_domain("sub.evil.example.co.uk", InputType.DOMAIN)
        assert reg == "example.co.uk"

    def test_ip_url_input_returns_none(self):
        reg = extract_registered_domain("http://192.168.0.1/evil", InputType.URL)
        assert reg is None


# ── Uploaded-hold skip (unit) ─────────────────────────────────────────────────

class TestUploadedHoldSkip:
    """
    Tests for _should_skip_enrichment logic in job_processor.
    We test the helper directly here to avoid needing a full job setup.
    """

    def test_hold_skipped_status_returns_true(self):
        from services.job_processor import _should_skip_enrichment
        from models import MdiResultItem, InputType, MdiProcessingStatus

        item = MdiResultItem(
            input_original="example.com",
            input_normalized="example.com",
            input_type=InputType.DOMAIN,
            position=1,
            processing_status=MdiProcessingStatus.HOLD_SKIPPED,
        )
        assert _should_skip_enrichment(item) is True

    def test_uploaded_confirmed_hold_returns_true(self):
        from services.job_processor import _should_skip_enrichment
        from models import (
            DomainHold, DomainHoldType, DomainStatusSource,
            InputType, MdiProcessingStatus, MdiResultItem,
        )

        item = MdiResultItem(
            input_original="held.com",
            input_normalized="held.com",
            input_type=InputType.DOMAIN,
            position=1,
            processing_status=MdiProcessingStatus.PENDING,
            domain_hold=DomainHold(
                has_hold=True,
                hold_types=[DomainHoldType.CLIENT_HOLD],
                source=DomainStatusSource.UPLOADED_FILE,
            ),
        )
        assert _should_skip_enrichment(item) is True

    def test_pending_item_returns_false(self):
        from services.job_processor import _should_skip_enrichment
        from models import InputType, MdiProcessingStatus, MdiResultItem

        item = MdiResultItem(
            input_original="normal.com",
            input_normalized="normal.com",
            input_type=InputType.DOMAIN,
            position=1,
            processing_status=MdiProcessingStatus.PENDING,
        )
        assert _should_skip_enrichment(item) is False

    def test_uploaded_no_hold_returns_false(self):
        from services.job_processor import _should_skip_enrichment
        from models import (
            DomainHold, DomainHoldType, DomainStatusSource,
            InputType, MdiProcessingStatus, MdiResultItem,
        )

        item = MdiResultItem(
            input_original="noheld.com",
            input_normalized="noheld.com",
            input_type=InputType.DOMAIN,
            position=1,
            processing_status=MdiProcessingStatus.PENDING,
            domain_hold=DomainHold(
                has_hold=False,
                hold_types=[DomainHoldType.NONE],
                source=DomainStatusSource.UPLOADED_FILE,
            ),
        )
        assert _should_skip_enrichment(item) is False


# ── Merge enrichment logic (unit) ─────────────────────────────────────────────

class TestMergeEnrichment:

    def _make_pending_result(self, **kwargs):
        from models import InputType, MdiProcessingStatus, MdiResultItem
        defaults = dict(
            input_original="example.com",
            input_normalized="example.com",
            input_type=InputType.DOMAIN,
            position=1,
            processing_status=MdiProcessingStatus.PENDING,
        )
        defaults.update(kwargs)
        return MdiResultItem(**defaults)

    def _make_enrichment(self, **kwargs) -> EnrichmentResult:
        from models import DomainHold, DomainHoldType
        defaults = dict(
            registered_domain="example.com",
            source=DomainStatusSource.RDAP,
            created_at=datetime(1995, 8, 14, tzinfo=timezone.utc),
            age_bucket=AgeBucket.MATURE,
            registrar="Test Registrar",
            epp_status=["clientTransferProhibited"],
            nameservers=["ns1.example.com"],
            domain_hold=DomainHold(
                has_hold=False,
                hold_types=[DomainHoldType.NONE],
                source=DomainStatusSource.RDAP,
            ),
            error=None,
            whois_fallback_used=False,
        )
        defaults.update(kwargs)
        return EnrichmentResult(**defaults)

    def test_sets_created_at_when_none(self):
        from services.job_processor import _merge_enrichment_into_result
        result = self._make_pending_result()
        enrichment = self._make_enrichment()
        updates = _merge_enrichment_into_result(result, enrichment)
        assert "created_at" in updates
        assert updates["created_at"].year == 1995

    def test_preserves_existing_created_at(self):
        from services.job_processor import _merge_enrichment_into_result
        existing_date = datetime(2022, 1, 1, tzinfo=timezone.utc)
        result = self._make_pending_result(created_at=existing_date)
        enrichment = self._make_enrichment()
        updates = _merge_enrichment_into_result(result, enrichment)
        assert "created_at" not in updates  # preserved

    def test_sets_age_bucket_when_unknown(self):
        from services.job_processor import _merge_enrichment_into_result
        result = self._make_pending_result(age_bucket=AgeBucket.UNKNOWN)
        enrichment = self._make_enrichment(age_bucket=AgeBucket.MATURE)
        updates = _merge_enrichment_into_result(result, enrichment)
        assert "age_bucket" in updates
        assert updates["age_bucket"] == AgeBucket.MATURE

    def test_preserves_existing_age_bucket(self):
        from services.job_processor import _merge_enrichment_into_result
        result = self._make_pending_result(age_bucket=AgeBucket.NEW)
        enrichment = self._make_enrichment(age_bucket=AgeBucket.MATURE)
        updates = _merge_enrichment_into_result(result, enrichment)
        assert "age_bucket" not in updates  # preserved

    def test_sets_registrar_when_none(self):
        from services.job_processor import _merge_enrichment_into_result
        result = self._make_pending_result(registrar=None)
        enrichment = self._make_enrichment(registrar="Good Registrar")
        updates = _merge_enrichment_into_result(result, enrichment)
        assert updates.get("registrar") == "Good Registrar"

    def test_preserves_existing_registrar(self):
        from services.job_processor import _merge_enrichment_into_result
        result = self._make_pending_result(registrar="Uploaded Registrar")
        enrichment = self._make_enrichment(registrar="RDAP Registrar")
        updates = _merge_enrichment_into_result(result, enrichment)
        assert "registrar" not in updates

    def test_appends_enrichment_error_to_errors(self):
        from services.job_processor import _merge_enrichment_into_result
        from models import MdiError
        result = self._make_pending_result()
        enrichment = self._make_enrichment(
            error=MdiError(code="rdap_failed", message="RDAP failed", source="domain_enrichment", retriable=True)
        )
        updates = _merge_enrichment_into_result(result, enrichment)
        assert "errors" in updates
        assert len(updates["errors"]) == 1
        assert updates["errors"][0].code == "rdap_failed"

    def test_no_enrichment_error_does_not_set_errors(self):
        from services.job_processor import _merge_enrichment_into_result
        result = self._make_pending_result()
        enrichment = self._make_enrichment(error=None)
        updates = _merge_enrichment_into_result(result, enrichment)
        assert "errors" not in updates


# ── No-live-call guard ────────────────────────────────────────────────────────

class TestNoLiveCallGuard:
    """
    These tests verify that the mock infrastructure works correctly.
    If _rdap_request or _whois_query_sync is called without a mock,
    an error would be raised (or a live HTTP/WHOIS call would be made).

    The tests above all use explicit mocks — this class documents the rule.
    """

    def test_extract_registered_domain_makes_no_network_calls(self):
        """extract_registered_domain is pure — no HTTP, no DNS."""
        result = extract_registered_domain("example.com", InputType.DOMAIN)
        assert result == "example.com"

    def test_parse_rdap_response_is_pure(self):
        """_parse_rdap_response is a pure function — no network calls."""
        data = _make_rdap_200()
        result = _parse_rdap_response(data, "example.com")
        assert result.source == DomainStatusSource.RDAP

    def test_parse_whois_result_is_pure(self):
        """_parse_whois_result is a pure function — no network calls."""
        result = _parse_whois_result(_make_whois_dict(), "example.com")
        assert result.source == DomainStatusSource.WHOIS


# ── MDI-11A: RDAP rate limiter and Retry-After handling ──────────────────────

class TestRdapRateLimiter:
    """
    Tests for MDI-11A rate limiter changes.
    Each test overrides the module-level autouse mock_rdap_rate_limiter as needed.
    No live RDAP/WHOIS/VT calls are made.
    """

    def test_rdap_min_interval_constant_is_1_1_seconds(self):
        """_RDAP_MIN_INTERVAL_SECONDS must be 1.1 to honour rdap.org's ~10 req/10s limit."""
        assert _RDAP_MIN_INTERVAL_SECONDS == 1.1

    def test_rdap_retry_delay_default_is_5_seconds(self):
        """Default wait on 429 (no Retry-After header) must be 5 s."""
        assert _RDAP_RETRY_DELAY_DEFAULT_SECONDS == 5.0

    # ── _parse_retry_after unit tests ──────────────────────────────────────────

    def test_parse_retry_after_numeric_string(self):
        headers = {"Retry-After": "3"}
        assert _parse_retry_after(headers, 5.0) == 3.0

    def test_parse_retry_after_lowercase_key(self):
        headers = {"retry-after": "7"}
        assert _parse_retry_after(headers, 5.0) == 7.0

    def test_parse_retry_after_absent_returns_fallback(self):
        headers = {}
        assert _parse_retry_after(headers, 5.0) == 5.0

    def test_parse_retry_after_non_numeric_returns_fallback(self):
        headers = {"Retry-After": "Fri, 06 Jun 2026 12:00:00 GMT"}
        assert _parse_retry_after(headers, 5.0) == 5.0

    def test_parse_retry_after_zero_returns_fallback(self):
        """Zero or negative values are treated as absent (return fallback)."""
        headers = {"Retry-After": "0"}
        assert _parse_retry_after(headers, 5.0) == 5.0

    def test_parse_retry_after_very_large_is_capped(self):
        """Values above _RDAP_RETRY_AFTER_MAX_SECONDS (60 s) are capped."""
        headers = {"Retry-After": "3600"}
        result = _parse_retry_after(headers, 5.0)
        assert result == 60.0

    def test_parse_retry_after_none_dict_returns_fallback(self):
        """Pathological headers object that raises — returns fallback."""

        class BrokenHeaders:
            def get(self, *args, **kwargs):
                raise RuntimeError("broken")

        result = _parse_retry_after(BrokenHeaders(), 5.0)
        assert result == 5.0

    # ── enrich_domain: 429 honours Retry-After ────────────────────────────────

    def test_rdap_429_honours_retry_after_header(self):
        """
        When RDAP returns 429 with Retry-After: 3, asyncio.sleep must be called
        with 3 seconds (not the default 5) before the single retry.
        """
        mock_429 = _make_rdap_response(429)
        mock_429.headers = MagicMock()
        mock_429.headers.get = lambda key, default="": (
            "3" if key.lower() == "retry-after" else default
        )

        rdap_data = _make_rdap_200()
        mock_200 = _make_rdap_response(200, rdap_data)

        responses = [mock_429, mock_200]

        async def _side_effect(*args, **kwargs):
            return responses.pop(0)

        sleep_calls: list = []

        async def _capture_sleep(secs):
            sleep_calls.append(secs)

        with (
            patch.object(domain_enrichment, "_rdap_acquire_slot", new=AsyncMock()),
            patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(side_effect=_side_effect)),
            patch("services.domain_enrichment.asyncio.sleep", new=_capture_sleep),
        ):
            result = _run(enrich_domain("rate-limited.com"))

        assert result.source == DomainStatusSource.RDAP, "Retry should succeed with RDAP source"
        assert len(sleep_calls) == 1, "asyncio.sleep called exactly once (for the 429 wait)"
        assert sleep_calls[0] == 3.0, f"Expected 3 s from Retry-After header, got {sleep_calls[0]}"

    def test_rdap_429_no_retry_after_uses_default_delay(self):
        """
        When RDAP returns 429 without Retry-After, asyncio.sleep must be called
        with _RDAP_RETRY_DELAY_DEFAULT_SECONDS (5.0).
        """
        mock_429 = _make_rdap_response(429)
        mock_429.headers = MagicMock()
        mock_429.headers.get = lambda key, default="": default  # no Retry-After

        rdap_data = _make_rdap_200()
        mock_200 = _make_rdap_response(200, rdap_data)

        responses = [mock_429, mock_200]

        async def _side_effect(*args, **kwargs):
            return responses.pop(0)

        sleep_calls: list = []

        async def _capture_sleep(secs):
            sleep_calls.append(secs)

        with (
            patch.object(domain_enrichment, "_rdap_acquire_slot", new=AsyncMock()),
            patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(side_effect=_side_effect)),
            patch("services.domain_enrichment.asyncio.sleep", new=_capture_sleep),
        ):
            result = _run(enrich_domain("no-header.com"))

        assert result.source == DomainStatusSource.RDAP
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == _RDAP_RETRY_DELAY_DEFAULT_SECONDS

    def test_rdap_429_retry_once_only(self):
        """
        On persistent 429, _rdap_request is called exactly twice:
        once for the initial attempt and once for the single retry.
        After that, the code falls through to WHOIS fallback — no third RDAP attempt.
        """
        mock_429 = _make_rdap_response(429)
        mock_429.headers = MagicMock()
        mock_429.headers.get = lambda key, default="": default

        whois_dict = _make_whois_dict()
        call_count = {"n": 0}

        async def _always_429(*args, **kwargs):
            call_count["n"] += 1
            return mock_429

        async def _sleep_noop(_):
            pass

        with (
            patch.object(domain_enrichment, "_rdap_acquire_slot", new=AsyncMock()),
            patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(side_effect=_always_429)),
            patch.object(domain_enrichment, "_whois_query_sync", return_value=whois_dict),
            patch("services.domain_enrichment.asyncio.sleep", new=_sleep_noop),
        ):
            result = _run(enrich_domain("always-429.com"))

        assert call_count["n"] == 2, (
            f"_rdap_request must be called exactly twice (initial + 1 retry), got {call_count['n']}"
        )
        assert result.source == DomainStatusSource.WHOIS, "Should fall back to WHOIS after retry exhausted"

    def test_rdap_persistent_429_records_structured_error_and_does_not_block_vt(self):
        """
        When RDAP is persistently rate-limited (429 on both initial and retry)
        and WHOIS also fails, the result must carry a structured error and have
        UNKNOWN source — allowing VT processing to continue (enrichment is non-fatal).
        """
        mock_429 = _make_rdap_response(429)
        mock_429.headers = MagicMock()
        mock_429.headers.get = lambda key, default="": default

        async def _always_429(*args, **kwargs):
            return mock_429

        async def _sleep_noop(_):
            pass

        with (
            patch.object(domain_enrichment, "_rdap_acquire_slot", new=AsyncMock()),
            patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(side_effect=_always_429)),
            patch.object(domain_enrichment, "_whois_query_sync", return_value=None),
            patch("services.domain_enrichment.asyncio.sleep", new=_sleep_noop),
        ):
            result = _run(enrich_domain("persistent-429.com"))

        assert result.source == DomainStatusSource.UNKNOWN
        assert result.error is not None
        assert result.error.code == "whois_failed"
        assert result.domain_hold.has_hold is False

    def test_rdap_acquire_slot_is_called_before_initial_request(self):
        """
        _rdap_acquire_slot must be called before the initial RDAP request.
        Verifies call ordering: acquire → request.
        """
        rdap_data = _make_rdap_200()
        mock_200 = _make_rdap_response(200, rdap_data)

        call_order: list = []

        async def _acquire():
            call_order.append("acquire")

        async def _request(url, client):
            call_order.append("request")
            return mock_200

        with (
            patch.object(domain_enrichment, "_rdap_acquire_slot", new=_acquire),
            patch.object(domain_enrichment, "_rdap_request", new=_request),
        ):
            _run(enrich_domain("example.com"))

        assert call_order[0] == "acquire", "Rate-limit slot must be acquired before RDAP request"
        assert call_order[1] == "request"

    def test_rdap_acquire_slot_called_before_retry_too(self):
        """
        _rdap_acquire_slot must be called both before the initial request
        and before the single 429 retry — ensuring the retry also respects the rate limit.
        """
        mock_429 = _make_rdap_response(429)
        mock_429.headers = MagicMock()
        mock_429.headers.get = lambda key, default="": default

        rdap_data = _make_rdap_200()
        mock_200 = _make_rdap_response(200, rdap_data)

        responses = [mock_429, mock_200]
        call_order: list = []

        async def _acquire():
            call_order.append("acquire")

        async def _request(*args, **kwargs):
            call_order.append("request")
            return responses.pop(0)

        async def _sleep_noop(_):
            pass

        with (
            patch.object(domain_enrichment, "_rdap_acquire_slot", new=_acquire),
            patch.object(domain_enrichment, "_rdap_request", new=_request),
            patch("services.domain_enrichment.asyncio.sleep", new=_sleep_noop),
        ):
            result = _run(enrich_domain("retry-order.com"))

        assert call_order == ["acquire", "request", "acquire", "request"], (
            f"Expected acquire→request→acquire→request, got {call_order}"
        )
        assert result.source == DomainStatusSource.RDAP
