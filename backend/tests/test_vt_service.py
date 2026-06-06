"""
Tests for services/vt_service.py.

All VT HTTP calls are mocked by patching services.vt_service._vt_request.
No network connections are made.  No VT quota is consumed.
The module-level rate limiter is set to zero interval for all tests.
"""

from __future__ import annotations

import asyncio
import socket
import time
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.vt_service as vt_svc
from services.vt_service import (
    AsyncMinIntervalLimiter,
    VtLookupResult,
    _build_vt_target,
    _vt_url_id,
    classify_freshness,
    classify_triage,
    parse_vt_response,
)
from models import (
    EvidenceStatus,
    Freshness,
    InputType,
    MdiError,
    RecommendedAction,
    TriageBucket,
    TriageConfidence,
    VtModeUsed,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _patch_limiter():
    """Set the module limiter to zero interval — returns a context manager."""
    return patch.object(vt_svc._VT_LIMITER, "acquire", new=AsyncMock())


def _mock_resp(status_code: int, body: dict = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    return m


def _vt_url_report(malicious: int = 0, suspicious: int = 0, harmless: int = 70,
                   last_analysis_date: int = None) -> dict:
    return {
        "data": {
            "attributes": {
                "last_analysis_stats": {
                    "malicious": malicious,
                    "suspicious": suspicious,
                    "harmless": harmless,
                    "undetected": 5,
                    "timeout": 0,
                },
                "last_analysis_date": last_analysis_date,
            }
        }
    }


def _run(coro):
    return asyncio.run(coro)


# ── Rate limiter unit test ─────────────────────────────────────────────────────

def test_async_min_interval_limiter_zero():
    """Zero-interval limiter should not sleep."""
    limiter = AsyncMinIntervalLimiter(0.0)
    start = time.monotonic()
    _run(limiter.acquire())
    _run(limiter.acquire())
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, "Zero-interval limiter should complete near-instantly"


# ── _build_vt_target ──────────────────────────────────────────────────────────

def test_build_vt_target_domain_url_mode():
    """Bare domain in URL-report mode → http://{domain}/"""
    target, mode = _build_vt_target("example.com", InputType.DOMAIN, use_domain_reports=False)
    assert target == "http://example.com/"
    assert mode == VtModeUsed.URL_REPORT


def test_build_vt_target_domain_domain_mode():
    """Bare domain in domain-report mode → domain string unchanged."""
    target, mode = _build_vt_target("example.com", InputType.DOMAIN, use_domain_reports=True)
    assert target == "example.com"
    assert mode == VtModeUsed.DOMAIN_REPORT


def test_build_vt_target_url_item():
    """URL item always uses URL-report mode regardless of use_domain_reports."""
    url = "https://example.net/path?q=1"
    target, mode = _build_vt_target(url, InputType.URL, use_domain_reports=False)
    assert target == url
    assert mode == VtModeUsed.URL_REPORT

    target2, mode2 = _build_vt_target(url, InputType.URL, use_domain_reports=True)
    assert target2 == url
    assert mode2 == VtModeUsed.URL_REPORT


def test_vt_url_id_is_base64url():
    """_vt_url_id must produce a base64url-encoded string without padding."""
    url = "http://example.com/"
    uid = _vt_url_id(url)
    assert "=" not in uid
    assert "/" not in uid.replace("/", "")   # standard / → _ in urlsafe
    # Round-trip check via stdlib
    import base64
    decoded = base64.urlsafe_b64decode(uid + "==").decode()
    assert decoded == url


# ── classify_freshness ────────────────────────────────────────────────────────

def test_freshness_fresh():
    ts = int(time.time()) - (1 * 86400)   # 1 day ago
    assert classify_freshness(ts, stale_threshold_days=5) == Freshness.FRESH


def test_freshness_stale():
    ts = int(time.time()) - (10 * 86400)  # 10 days ago
    assert classify_freshness(ts, stale_threshold_days=5) == Freshness.STALE


def test_freshness_very_stale():
    ts = int(time.time()) - (45 * 86400)  # 45 days ago
    assert classify_freshness(ts, stale_threshold_days=5) == Freshness.VERY_STALE


def test_freshness_never_scanned():
    assert classify_freshness(None) == Freshness.NEVER_SCANNED
    assert classify_freshness(0) == Freshness.NEVER_SCANNED


# ── parse_vt_response ─────────────────────────────────────────────────────────

def test_parse_vt_response_clean():
    body = _vt_url_report(malicious=0, suspicious=0, harmless=72,
                          last_analysis_date=int(time.time()) - 86400)
    result = parse_vt_response(body, VtModeUsed.URL_REPORT, stale_threshold_days=5)
    assert result.vt_malicious == 0
    assert result.vt_suspicious == 0
    assert result.vt_harmless == 72
    assert result.vt_hits == 0
    assert result.vt_total_engines == 72 + 5  # harmless + undetected
    assert result.freshness == Freshness.FRESH
    assert result.error is None


def test_parse_vt_response_malicious():
    body = _vt_url_report(malicious=5, suspicious=1, harmless=66,
                          last_analysis_date=int(time.time()) - 86400)
    result = parse_vt_response(body, VtModeUsed.URL_REPORT)
    assert result.vt_malicious == 5
    assert result.vt_suspicious == 1
    assert result.vt_hits == 5               # PRD: vt_hits = malicious count
    assert result.vt_ratio == "6/77"         # (malicious+suspicious)/(total)


def test_parse_vt_response_missing_date():
    body = _vt_url_report(malicious=0, last_analysis_date=None)
    result = parse_vt_response(body, VtModeUsed.URL_REPORT)
    assert result.freshness == Freshness.NEVER_SCANNED
    assert result.vt_scan_date is None


# ── classify_triage ───────────────────────────────────────────────────────────

def test_classify_triage_malicious():
    r = VtLookupResult(vt_malicious=3, vt_suspicious=0, vt_total_engines=70,
                       freshness=Freshness.FRESH, error=None)
    bucket, conf, action, evidence = classify_triage(r)
    assert bucket == TriageBucket.MALICIOUS
    assert action == RecommendedAction.INVESTIGATE
    assert evidence == EvidenceStatus.COMPLETE


def test_classify_triage_suspicious():
    r = VtLookupResult(vt_malicious=0, vt_suspicious=2, vt_total_engines=70,
                       freshness=Freshness.FRESH, error=None)
    bucket, conf, action, evidence = classify_triage(r)
    assert bucket == TriageBucket.SUSPICIOUS
    assert action == RecommendedAction.MANUAL_REVIEW
    assert evidence == EvidenceStatus.COMPLETE


def test_classify_triage_clean():
    r = VtLookupResult(vt_malicious=0, vt_suspicious=0, vt_total_engines=70,
                       freshness=Freshness.FRESH, error=None)
    bucket, conf, action, evidence = classify_triage(r)
    assert bucket == TriageBucket.CLEAN
    assert action == RecommendedAction.CLEAR


def test_classify_triage_error():
    err = MdiError(code="vt_429", message="Rate limited", source="vt_service", retriable=True)
    r = VtLookupResult(error=err)
    bucket, conf, action, evidence = classify_triage(r)
    assert bucket == TriageBucket.ERROR
    assert action == RecommendedAction.MANUAL_REVIEW
    assert evidence == EvidenceStatus.PARTIAL


def test_classify_triage_stale_degrades_confidence():
    r = VtLookupResult(vt_malicious=1, vt_total_engines=70, freshness=Freshness.STALE, error=None)
    _, conf, _, _ = classify_triage(r)
    assert conf == TriageConfidence.MEDIUM


def test_classify_triage_very_stale_degrades_confidence():
    r = VtLookupResult(vt_malicious=1, vt_total_engines=70, freshness=Freshness.VERY_STALE, error=None)
    _, conf, _, _ = classify_triage(r)
    assert conf == TriageConfidence.MEDIUM


# ── fetch_report: success paths ────────────────────────────────────────────────

def test_fetch_report_url_200_clean():
    """URL report 200 with 0 hits → clean result."""
    scan_ts = int(time.time()) - 86400
    body = _vt_url_report(malicious=0, last_analysis_date=scan_ts)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        result = _run(vt_svc.fetch_report("http://example.com/", InputType.URL))

    assert result.error is None
    assert result.vt_malicious == 0
    assert result.vt_mode_used == VtModeUsed.URL_REPORT
    assert result.calls_made == 1
    mock_req.assert_called_once()


def test_fetch_report_url_200_malicious():
    """URL report with malicious hits → hits counted correctly."""
    scan_ts = int(time.time()) - 86400
    body = _vt_url_report(malicious=3, suspicious=1, last_analysis_date=scan_ts)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        result = _run(vt_svc.fetch_report("http://evil.com/", InputType.URL))

    assert result.vt_malicious == 3
    assert result.vt_suspicious == 1
    assert result.vt_hits == 3
    assert result.error is None


def test_fetch_report_domain_report_mode():
    """Domain report mode uses /domains/{domain} endpoint."""
    scan_ts = int(time.time()) - 86400
    body = _vt_url_report(malicious=0, last_analysis_date=scan_ts)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        result = _run(vt_svc.fetch_report(
            "example.com", InputType.DOMAIN, use_domain_reports=True
        ))

    assert result.error is None
    assert result.vt_mode_used == VtModeUsed.DOMAIN_REPORT
    call_url = mock_req.call_args[0][1]
    assert "/domains/example.com" in call_url


def test_fetch_report_bare_domain_url_mode_target():
    """Bare domain in URL-mode → VT lookup target is http://example.com/, not example.com"""
    body = _vt_url_report(malicious=0, last_analysis_date=int(time.time()) - 3600)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        _run(vt_svc.fetch_report("example.com", InputType.DOMAIN, use_domain_reports=False))

    call_url = mock_req.call_args[0][1]
    # Should use URL endpoint, not domain endpoint
    assert "/urls/" in call_url
    assert "/domains/" not in call_url


# ── fetch_report: 404 → submit → refetch ──────────────────────────────────────

def test_fetch_report_url_404_submit_refetch():
    """URL 404 → submit → re-fetch → success consumes 3 calls."""
    scan_ts = int(time.time()) - 86400
    success_body = _vt_url_report(malicious=0, last_analysis_date=scan_ts)

    call_responses = [
        _mock_resp(404, {}),                             # 1st GET → not found
        _mock_resp(200, {"data": {"id": "url-abc"}}),   # POST submit → accepted
        _mock_resp(200, success_body),                   # 2nd GET → result
    ]
    call_idx = 0

    async def multi_response(method, url, *, headers, data=None):
        nonlocal call_idx
        resp = call_responses[call_idx]
        call_idx += 1
        return resp

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=multi_response), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        result = _run(vt_svc.fetch_report("http://unknown.com/", InputType.URL))

    assert result.error is None
    assert result.calls_made == 3
    assert result.vt_malicious == 0


def test_fetch_report_url_404_submit_quota_count():
    """URL 404 → submit → re-fetch: quota increment should account for 3 calls."""
    scan_ts = int(time.time()) - 3600
    success_body = _vt_url_report(malicious=1, last_analysis_date=scan_ts)

    responses = [
        _mock_resp(404, {}),
        _mock_resp(200, {"data": {"id": "x"}}),
        _mock_resp(200, success_body),
    ]
    idx = 0

    async def multi(method, url, *, headers, data=None):
        nonlocal idx
        r = responses[idx]; idx += 1
        return r

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=multi), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        result = _run(vt_svc.fetch_report("http://another.com/", InputType.URL))

    assert result.calls_made == 3
    assert result.vt_malicious == 1


# ── fetch_report: error paths ──────────────────────────────────────────────────

def test_fetch_report_vt_429():
    """VT 429 → structured MdiError with code 'vt_429'."""
    mock_req = AsyncMock(return_value=_mock_resp(429, {}))

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        result = _run(vt_svc.fetch_report("http://site.com/", InputType.URL))

    assert result.error is not None
    assert result.error.code == "vt_429"
    assert result.error.retriable is True


def test_fetch_report_vt_500():
    """VT 5xx → structured server error."""
    mock_req = AsyncMock(return_value=_mock_resp(503, {}))

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        result = _run(vt_svc.fetch_report("http://site.com/", InputType.URL))

    assert result.error is not None
    assert result.error.code == "vt_server_error"


def test_fetch_report_timeout():
    """Timeout exception → structured timeout error."""
    import httpx

    async def raise_timeout(method, url, *, headers, data=None):
        raise httpx.TimeoutException("timed out")

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=raise_timeout), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
        result = _run(vt_svc.fetch_report("http://slow.com/", InputType.URL))

    assert result.error is not None
    assert result.error.code == "vt_timeout"
    assert result.error.retriable is True


def test_fetch_report_no_api_key():
    """Missing VT_API_KEY → structured no_api_key error without any HTTP call."""
    mock_req = AsyncMock()

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {}, clear=True):
        # Remove VT_API_KEY if present
        env = {k: v for k, v in os.environ.items() if k != "VT_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            result = _run(vt_svc.fetch_report("http://x.com/", InputType.URL))

    assert result.error is not None
    assert result.error.code == "no_api_key"
    mock_req.assert_not_called()


# ── No socket / DNS calls ──────────────────────────────────────────────────────

def test_no_dns_calls_in_vt_service():
    """Confirm that vt_service tests never resolve DNS via socket.getaddrinfo."""
    original_getaddrinfo = socket.getaddrinfo
    dns_calls = []

    def spy_getaddrinfo(*args, **kwargs):
        dns_calls.append(args)
        return original_getaddrinfo(*args, **kwargs)

    body = _vt_url_report(malicious=0, last_analysis_date=int(time.time()) - 3600)
    mock_req = AsyncMock(return_value=_mock_resp(200, body))

    with _patch_limiter(), \
         patch("services.vt_service._vt_request", new=mock_req), \
         patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
         patch("socket.getaddrinfo", side_effect=spy_getaddrinfo):
        _run(vt_svc.fetch_report("http://example.com/", InputType.URL))

    # socket.getaddrinfo should NOT be called (all HTTP is mocked)
    assert dns_calls == [], f"Unexpected DNS resolution: {dns_calls}"
