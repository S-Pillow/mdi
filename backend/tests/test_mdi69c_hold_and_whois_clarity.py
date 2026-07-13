"""
MDI-69C — spaced hold detection + WHOIS/RDAP failure clarity regression tests.

All RDAP/WHOIS/VT HTTP is mocked. No live external calls. No runtime files.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import (
    DomainHoldType,
    DomainStatusSource,
    EvidenceStatus,
    InputType,
    LiveStatus,
    MdiProcessingStatus,
    RecommendedAction,
    TriageBucket,
    VtModeUsed,
)
from services import domain_enrichment, job_processor, job_store, live_check
from services.domain_enrichment import extract_registered_domain, enrich_domain
from services.job_store import InMemoryJob
from services.live_check import LiveCheckResult


def _run(coro):
    return asyncio.run(coro)


def _mock_resp(status_code: int, body: dict | None = None) -> MagicMock:
    m = MagicMock(spec=httpx.Response)
    m.status_code = status_code
    m.json.return_value = body or {}
    m.headers = MagicMock()
    m.headers.get = lambda key, default="": default
    return m


def _make_rdap_200(
    *,
    creation_date: str = "2026-06-19T05:40:17Z",
    registrar: str = "Dynadot Inc",
    statuses: list[str] | None = None,
) -> dict:
    if statuses is None:
        statuses = ["client transfer prohibited", "client hold", "server transfer prohibited", "inactive"]
    return {
        "events": [{"eventAction": "registration", "eventDate": creation_date}],
        "entities": [{
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["fn", {}, "text", registrar]]],
        }],
        "status": statuses,
        "nameservers": [{"ldhName": "ns1.example.com"}],
    }


def _make_job(job_id: str, items: list[tuple[str, str, InputType]]) -> InMemoryJob:
    job = InMemoryJob(
        job_id=job_id,
        status="queued",
        submitted_at=time.time(),
        total=len(items),
    )
    from models import MdiResultItem

    for pos, (orig, norm, itype) in enumerate(items, start=1):
        job.results[norm] = MdiResultItem(
            input_original=orig,
            input_normalized=norm,
            input_type=itype,
            position=pos,
            processing_status=MdiProcessingStatus.PENDING,
        )
        job.item_order.append(norm)
    _run(job_store.create_job(job))
    return job


@pytest.fixture(autouse=True)
def _clear_jobs():
    job_store.clear_all_jobs()
    yield
    job_store.clear_all_jobs()


class TestUrlNormalizationGuardrails:
    @pytest.mark.parametrize("url,expected", [
        ("https://orlvexa.vu/myparty", "orlvexa.vu"),
        ("https://hk.kavlix.vu/path/file.html", "kavlix.vu"),
        ("https://test.example.com/testtesttest123", "example.com"),
        ("https://sub.test.example.co.uk/path", "example.co.uk"),
    ])
    def test_extract_registered_domain(self, url, expected):
        assert extract_registered_domain(url, InputType.URL) == expected


class TestSpacedClientHoldRdapEnrichment:
    def test_rdap_spaced_client_hold_detected(self):
        data = _make_rdap_200()
        from services.domain_enrichment import _parse_rdap_response

        result = _parse_rdap_response(data, "ap-exdex.vip")
        assert result.domain_hold.has_hold is True
        assert DomainHoldType.CLIENT_HOLD in result.domain_hold.hold_types
        assert result.domain_hold.source == DomainStatusSource.RDAP
        assert "client hold" in result.epp_status
        assert result.registrar == "Dynadot Inc"
        assert result.created_at is not None

    def test_job_spaced_client_hold_skips_vt_and_live(self, tmp_path):
        job_id = f"mdi69c-hold-{time.time_ns()}"
        url = "https://ap-exdex.vip"
        _make_job(job_id, [(url, url, InputType.URL)])

        rdap_data = _make_rdap_200()
        mock_rdap = AsyncMock(return_value=_mock_resp(200, rdap_data))
        mock_vt = AsyncMock()
        mock_live = AsyncMock(side_effect=AssertionError("live_check should not run for held row"))

        usage_file = tmp_path / "vt_usage.json"
        usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

        with patch("services.vt_service._VT_LIMITER.acquire", new=AsyncMock()), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch.object(domain_enrichment, "_rdap_acquire_slot", new=AsyncMock()), \
             patch.object(domain_enrichment, "_rdap_request", new=mock_rdap), \
             patch("services.vt_service._vt_request", new=mock_vt), \
             patch.object(live_check, "live_check_item", new=mock_live):
            _run(job_processor.process_job(
                job_id,
                usage_file=usage_file,
                job_file=tmp_path / "mdi_latest_job.json",
            ))

        mock_vt.assert_not_called()
        mock_live.assert_not_called()
        job = job_store.get_job_sync(job_id)
        result = job.results[url]
        assert result.input_original == url
        assert result.input_normalized == url
        assert result.processing_status == MdiProcessingStatus.HOLD_SKIPPED
        assert result.triage_bucket == TriageBucket.HELD
        assert result.recommended_action == RecommendedAction.ACTION_ALREADY_TAKEN
        assert result.evidence_status == EvidenceStatus.SKIPPED_HOLD
        assert result.vt_mode_used == VtModeUsed.SKIPPED_HOLD
        assert result.domain_hold.has_hold is True
        assert job.hold_detected_by_enrichment_count >= 1


class TestWhoisFailureClarity:
    def test_enrich_domain_whois_failed_message_names_registrable_domain(self):
        mock_404 = _mock_resp(404)
        with patch.object(domain_enrichment, "_rdap_acquire_slot", new=AsyncMock()), \
             patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(return_value=mock_404)), \
             patch.object(domain_enrichment, "_whois_query_sync", return_value=None):
            result = _run(enrich_domain("orlvexa.vu"))

        assert result.error is not None
        assert result.error.code == "whois_failed"
        assert "orlvexa.vu" in result.error.message
        assert "normalization succeeded" in result.error.message
        assert "parse" not in result.error.message.lower() or "normalization succeeded" in result.error.message
        assert result.registrar is None
        assert result.created_at is None

    def test_job_vu_url_enrichment_failure_message(self, tmp_path):
        job_id = f"mdi69c-vu-fail-{time.time_ns()}"
        url = "https://orlvexa.vu/myparty"
        _make_job(job_id, [(url, url, InputType.URL)])

        body = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {"malicious": 1, "suspicious": 0, "harmless": 70, "undetected": 5, "timeout": 0},
                    "last_analysis_date": int(time.time()) - 86400,
                }
            }
        }
        mock_vt = AsyncMock(return_value=_mock_resp(200, body))
        mock_404 = _mock_resp(404)

        usage_file = tmp_path / "vt_usage.json"
        usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

        with patch("services.vt_service._VT_LIMITER.acquire", new=AsyncMock()), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch.object(domain_enrichment, "_rdap_acquire_slot", new=AsyncMock()), \
             patch.object(domain_enrichment, "_rdap_request", new=AsyncMock(return_value=mock_404)), \
             patch.object(domain_enrichment, "_whois_query_sync", return_value=None), \
             patch("services.vt_service._vt_request", new=mock_vt), \
             patch.object(live_check, "live_check_item", new=AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.NOT_CHECKED))):
            _run(job_processor.process_job(
                job_id,
                usage_file=usage_file,
                job_file=tmp_path / "mdi_latest_job.json",
            ))

        job = job_store.get_job_sync(job_id)
        result = job.results[url]
        assert extract_registered_domain(url, InputType.URL) == "orlvexa.vu"
        assert result.registrar is None
        assert result.created_at is None
        whois_err = next(e for e in (result.errors or []) if e.code == "whois_failed")
        assert "orlvexa.vu" in whois_err.message
        assert "normalization succeeded" in whois_err.message
        assert "failed to parse" not in whois_err.message.lower()
        mock_vt.assert_called()

    def test_successful_url_enrichment_no_failure_warning(self, tmp_path):
        job_id = f"mdi69c-ok-{time.time_ns()}"
        url = "https://valorex.club/"
        _make_job(job_id, [(url, url, InputType.URL)])

        rdap_data = _make_rdap_200(
            registrar="Global Domain Group LLC",
            statuses=["client transfer prohibited", "server transfer prohibited"],
        )
        mock_rdap = AsyncMock(return_value=_mock_resp(200, rdap_data))
        body = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {"malicious": 0, "suspicious": 0, "harmless": 70, "undetected": 5, "timeout": 0},
                    "last_analysis_date": int(time.time()) - 86400,
                }
            }
        }
        mock_vt = AsyncMock(return_value=_mock_resp(200, body))

        usage_file = tmp_path / "vt_usage.json"
        usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')

        with patch("services.vt_service._VT_LIMITER.acquire", new=AsyncMock()), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch.object(domain_enrichment, "_rdap_acquire_slot", new=AsyncMock()), \
             patch.object(domain_enrichment, "_rdap_request", new=mock_rdap), \
             patch("services.vt_service._vt_request", new=mock_vt), \
             patch.object(live_check, "live_check_item", new=AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.NOT_CHECKED))):
            _run(job_processor.process_job(
                job_id,
                usage_file=usage_file,
                job_file=tmp_path / "mdi_latest_job.json",
            ))

        result = job_store.get_job_sync(job_id).results[url]
        assert result.registrar == "Global Domain Group LLC"
        assert result.created_at is not None
        assert not any(e.code == "whois_failed" for e in (result.errors or []))
