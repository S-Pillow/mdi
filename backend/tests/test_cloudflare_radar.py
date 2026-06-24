"""Tests for Cloudflare Radar rank lookup (MDI-50B)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from models import InputType, MdiProcessingStatus, MdiResultItem
from services import cloudflare_radar, job_processor, job_store
from services.cloudflare_radar import (
    CloudflareRankBucket,
    CloudflareJobState,
    clear_cache,
    lookup_domain_rank,
    normalize_bucket,
    parse_api_response,
)


# ── Fixtures from live validation (sanitized) ─────────────────────────────────


def _body_google():
    return {
        "success": True,
        "errors": [],
        "result": {
            "details_0": {"rank": 1, "bucket": "200"},
            "meta": {"dateRange": [{"startTime": "t0", "endTime": "t1"}]},
        },
    }


def _body_example():
    return {
        "success": True,
        "errors": [],
        "result": {
            "details_0": {"bucket": "200"},
            "meta": {"dateRange": [{"startTime": "t0", "endTime": "t1"}]},
        },
    }


def _body_unranked():
    return {
        "success": True,
        "errors": [],
        "result": {
            "details_0": {"bucket": ">200000"},
            "meta": {"dateRange": [{"startTime": "t0", "endTime": "t1"}]},
        },
    }


@pytest.fixture(autouse=True)
def _clear_cf_cache():
    clear_cache()
    yield
    clear_cache()


# ── Normalization unit tests ──────────────────────────────────────────────────


class TestNormalizeBucket:
    def test_google_style_rank_and_bucket(self):
        bucket, rank = normalize_bucket(1, "200")
        assert bucket == CloudflareRankBucket.TOP_100
        assert rank == 1

    def test_example_style_bucket_only(self):
        bucket, rank = normalize_bucket(None, "200")
        assert bucket == CloudflareRankBucket.TOP_1K
        assert rank is None

    def test_numeric_buckets(self):
        assert normalize_bucket(None, "1000")[0] == CloudflareRankBucket.TOP_1K
        assert normalize_bucket(None, "5000")[0] == CloudflareRankBucket.TOP_5K
        assert normalize_bucket(None, "10000")[0] == CloudflareRankBucket.TOP_10K
        assert normalize_bucket(None, "100000")[0] == CloudflareRankBucket.TOP_100K
        assert normalize_bucket(None, "1000000")[0] == CloudflareRankBucket.TOP_1M

    def test_inequality_bucket_unranked(self):
        bucket, rank = normalize_bucket(None, ">200000")
        assert bucket == CloudflareRankBucket.UNRANKED
        assert rank is None


class TestParseApiResponse:
    def test_google_live_shape(self):
        r = parse_api_response(200, _body_google())
        assert r.available is True
        assert r.rank == 1
        assert r.bucket == CloudflareRankBucket.TOP_100
        assert r.raw_bucket == "200"
        assert r.error is None

    def test_example_live_shape(self):
        r = parse_api_response(200, _body_example())
        assert r.available is True
        assert r.bucket == CloudflareRankBucket.TOP_1K
        assert r.error is None

    def test_synthetic_unranked_live_shape(self):
        r = parse_api_response(200, _body_unranked())
        assert r.available is False
        assert r.bucket == CloudflareRankBucket.UNRANKED
        assert r.raw_bucket == ">200000"
        assert r.error is None

    def test_404_unranked(self):
        r = parse_api_response(404, {"success": False, "errors": [{"code": 7003}]})
        assert r.bucket == CloudflareRankBucket.UNRANKED
        assert r.error is None

    def test_401_auth_failed(self):
        r = parse_api_response(401, {"success": False, "errors": []})
        assert r.bucket == CloudflareRankBucket.UNKNOWN
        assert r.error == "auth_failed"

    def test_403_auth_failed(self):
        r = parse_api_response(403, {"success": False, "errors": []})
        assert r.error == "auth_failed"

    def test_429_rate_limited(self):
        r = parse_api_response(429, {"success": False, "errors": [{"code": 1015}]})
        assert r.bucket == CloudflareRankBucket.UNKNOWN
        assert r.error == "rate_limited"

    def test_5xx_api_unavailable(self):
        r = parse_api_response(502, {"success": False, "errors": []})
        assert r.error == "api_unavailable"

    def test_malformed_response(self):
        r = parse_api_response(200, {"success": True, "result": "bad"})
        assert r.bucket == CloudflareRankBucket.UNKNOWN
        assert r.error == "invalid_response"


# ── Async lookup behavior ───────────────────────────────────────────────────────


def test_disabled_no_http_call():
    called = False

    async def _req(domain, token):
        nonlocal called
        called = True
        return 200, _body_google()

    r = asyncio.run(lookup_domain_rank("google.com", enabled=False, request_func=_req))
    assert called is False
    assert r.available is False
    assert r.bucket is None


def test_missing_token_no_http_call():
    called = False

    async def _req(domain, token):
        nonlocal called
        called = True
        return 200, _body_google()

    with patch.dict("os.environ", {}, clear=True):
        r = asyncio.run(lookup_domain_rank(
            "google.com",
            enabled=True,
            token=None,
            request_func=_req,
        ))
    assert called is False
    assert r.error == "not_configured"


def test_lookup_google_mocked():
    async def _req(domain, token):
        assert token == "test-token"
        assert domain == "google.com"
        return 200, _body_google()

    r = asyncio.run(lookup_domain_rank(
        "google.com",
        enabled=True,
        token="test-token",
        request_func=_req,
    ))
    assert r.bucket == CloudflareRankBucket.TOP_100


def test_5xx_retries_once_then_unknown():
    calls = 0

    async def _req(domain, token):
        nonlocal calls
        calls += 1
        return 503, {"success": False, "errors": []}

    r = asyncio.run(lookup_domain_rank(
        "google.com",
        enabled=True,
        token="t",
        request_func=_req,
    ))
    assert calls == 2
    assert r.error == "api_unavailable"


def test_timeout_retries_once():
    calls = 0

    async def _req(domain, token):
        nonlocal calls
        calls += 1
        raise httpx.TimeoutException("timeout")

    r = asyncio.run(lookup_domain_rank(
        "google.com",
        enabled=True,
        token="t",
        request_func=_req,
    ))
    assert calls == 2
    assert r.error == "timeout"


def test_429_stops_job_state():
    state = CloudflareJobState()

    async def _req(domain, token):
        return 429, {"success": False, "errors": [{"code": 1015}]}

    r1 = asyncio.run(lookup_domain_rank(
        "a.com", enabled=True, token="t", job_state=state, request_func=_req,
    ))
    assert r1.error == "rate_limited"
    assert state.stop is True

    r2 = asyncio.run(lookup_domain_rank(
        "b.com", enabled=True, token="t", job_state=state, request_func=_req,
    ))
    assert r2.error == "rate_limited"
    assert state.lookups_done == 1


def test_cache_prevents_second_call():
    calls = 0

    async def _req(domain, token):
        nonlocal calls
        calls += 1
        return 200, _body_google()

    asyncio.run(lookup_domain_rank("google.com", enabled=True, token="t", request_func=_req))
    asyncio.run(lookup_domain_rank("google.com", enabled=True, token="t", request_func=_req))
    assert calls == 1


def test_cap_exceeded_without_http():
    state = CloudflareJobState()
    state.lookups_done = cloudflare_radar.MAX_LOOKUPS_PER_JOB

    async def _req(domain, token):
        raise AssertionError("should not call")

    r = asyncio.run(lookup_domain_rank(
        "google.com",
        enabled=True,
        token="t",
        job_state=state,
        request_func=_req,
    ))
    assert r.error == "lookup_cap_exceeded"


# ── Job processor integration ─────────────────────────────────────────────────


def _done_item(domain: str) -> MdiResultItem:
    return MdiResultItem(
        input_original=domain,
        input_normalized=domain,
        input_type=InputType.DOMAIN,
        position=1,
        processing_status=MdiProcessingStatus.DONE,
        vt_total_engines=70,
    )


def _held_item(domain: str) -> MdiResultItem:
    return MdiResultItem(
        input_original=domain,
        input_normalized=domain,
        input_type=InputType.DOMAIN,
        position=2,
        processing_status=MdiProcessingStatus.HOLD_SKIPPED,
    )


def test_job_processor_cloudflare_enrichment_mocked():
    job = job_store.InMemoryJob(
        job_id="j-cf",
        status="running",
        submitted_at=0.0,
        cloudflare_rank_lookup_enabled=True,
        item_order=["example.com", "blocked.org"],
        results={
            "example.com": _done_item("example.com"),
            "blocked.org": _held_item("blocked.org"),
        },
    )

    before_triage = job.results["example.com"].triage_bucket

    async def _req(domain, token):
        return 200, _body_example()

    with patch.dict("os.environ", {"CLOUDFLARE_RADAR_API_TOKEN": "tok"}):
        with patch.object(cloudflare_radar, "_default_request", _req):
            asyncio.run(job_processor._cloudflare_rank_items(job))

    updated = job.results["example.com"]
    assert updated.cloudflare_rank_bucket == CloudflareRankBucket.TOP_1K
    assert updated.triage_bucket == before_triage
    held = job.results["blocked.org"]
    assert held.cloudflare_rank_bucket is None


def test_job_processor_disabled_skips():
    job = job_store.InMemoryJob(
        job_id="j-off",
        status="running",
        submitted_at=0.0,
        cloudflare_rank_lookup_enabled=False,
        item_order=["example.com"],
        results={"example.com": _done_item("example.com")},
    )

    async def _req(domain, token):
        raise AssertionError("no call")

    with patch.object(cloudflare_radar, "_default_request", _req):
        asyncio.run(job_processor._cloudflare_rank_items(job))

    assert job.results["example.com"].cloudflare_rank_bucket is None


class TestSerializationNoTokenLeak:
    def test_model_dump_excludes_token(self):
        item = _done_item("example.com")
        item = item.model_copy(update={
            "cloudflare_rank_bucket": CloudflareRankBucket.TOP_1K,
            "cloudflare_rank_source": cloudflare_radar.SOURCE_POPULAR,
        })
        dumped = json.dumps(item.model_dump(mode="json"))
        assert "Bearer" not in dumped
        assert "test-token" not in dumped
        assert "CLOUDFLARE_RADAR_API_TOKEN" not in dumped
