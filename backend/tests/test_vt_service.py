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
    """MDI-10: shim delegates to triage_rules. FRESH + NOT_CHECKED live + UNKNOWN age → VERIFY_INVESTIGATE (catch-all)."""
    r = VtLookupResult(vt_malicious=3, vt_suspicious=0, vt_total_engines=70,
                       freshness=Freshness.FRESH, error=None)
    bucket, conf, action, evidence = classify_triage(r)
    assert bucket == TriageBucket.MALICIOUS
    assert action == RecommendedAction.VERIFY_INVESTIGATE
    assert evidence == EvidenceStatus.COMPLETE


def test_classify_triage_suspicious():
    """MDI-10: suspicious + FRESH + NOT_CHECKED + UNKNOWN age → VERIFY_INVESTIGATE (catch-all)."""
    r = VtLookupResult(vt_malicious=0, vt_suspicious=2, vt_total_engines=70,
                       freshness=Freshness.FRESH, error=None)
    bucket, conf, action, evidence = classify_triage(r)
    assert bucket == TriageBucket.SUSPICIOUS
    assert action == RecommendedAction.VERIFY_INVESTIGATE
    assert evidence == EvidenceStatus.COMPLETE


def test_classify_triage_clean():
    """MDI-10: clean + FRESH → NO_ACTION_BASED_ON_VT (replaced CLEAR)."""
    r = VtLookupResult(vt_malicious=0, vt_suspicious=0, vt_total_engines=70,
                       freshness=Freshness.FRESH, error=None)
    bucket, conf, action, evidence = classify_triage(r)
    assert bucket == TriageBucket.CLEAN
    assert action == RecommendedAction.NO_ACTION_BASED_ON_VT


def test_classify_triage_error():
    """MDI-10: error → RETRY_LOOKUP (replaced MANUAL_REVIEW)."""
    err = MdiError(code="vt_429", message="Rate limited", source="vt_service", retriable=True)
    r = VtLookupResult(error=err)
    bucket, conf, action, evidence = classify_triage(r)
    assert bucket == TriageBucket.ERROR
    assert action == RecommendedAction.RETRY_LOOKUP
    assert evidence == EvidenceStatus.PARTIAL


def test_classify_triage_stale_degrades_confidence():
    """MDI-10: STALE malicious → MEDIUM confidence, REFRESH_REPORT."""
    r = VtLookupResult(vt_malicious=1, vt_total_engines=70, freshness=Freshness.STALE, error=None)
    _, conf, action, _ = classify_triage(r)
    assert conf == TriageConfidence.MEDIUM
    assert action == RecommendedAction.REFRESH_REPORT


def test_classify_triage_very_stale_degrades_confidence():
    """MDI-10: VERY_STALE malicious → LOW confidence (was MEDIUM), REQUEST_NEW_SCAN."""
    r = VtLookupResult(vt_malicious=1, vt_total_engines=70, freshness=Freshness.VERY_STALE, error=None)
    _, conf, action, _ = classify_triage(r)
    assert conf == TriageConfidence.LOW
    assert action == RecommendedAction.REQUEST_NEW_SCAN


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


# ── MDI-14: engine_detections in parse_vt_response ────────────────────────────

def _vt_url_report_with_engines(
    malicious: int = 0,
    suspicious: int = 0,
    harmless: int = 70,
    last_analysis_date: int = None,
    last_analysis_results: dict = None,
) -> dict:
    """Build a mock VT URL report that includes last_analysis_results."""
    report = _vt_url_report(malicious=malicious, suspicious=suspicious,
                            harmless=harmless, last_analysis_date=last_analysis_date)
    if last_analysis_results is not None:
        report["data"]["attributes"]["last_analysis_results"] = last_analysis_results
    return report


def test_parse_vt_response_malicious_engines_extracted():
    """Malicious and suspicious engine entries are extracted; harmless are excluded."""
    engines = {
        "Kaspersky":    {"category": "malicious",  "result": "Trojan.GenAI",  "method": "blacklist", "engine_update": "20240101"},
        "ESET-NOD32":   {"category": "suspicious", "result": "Suspicious",    "method": "heuristic", "engine_update": "20240102"},
        "Google":       {"category": "harmless",   "result": "clean",         "method": "blacklist", "engine_update": "20240101"},
        "Comodo":       {"category": "malicious",  "result": "Malware.Gen",   "method": "blacklist", "engine_update": "20240101"},
    }
    report = _vt_url_report_with_engines(malicious=2, suspicious=1, last_analysis_results=engines)
    result = parse_vt_response(report, VtModeUsed.URL_REPORT)

    assert len(result.engine_detections) == 3
    names = {d["engine_name"] for d in result.engine_detections}
    assert "Kaspersky" in names
    assert "ESET-NOD32" in names
    assert "Comodo" in names
    assert "Google" not in names

    # Check field shape on one detection
    kas = next(d for d in result.engine_detections if d["engine_name"] == "Kaspersky")
    assert kas["category"] == "malicious"
    assert kas["result"] == "Trojan.GenAI"
    assert kas["method"] == "blacklist"
    assert kas["engine_update"] == "20240101"


def test_parse_vt_response_clean_produces_empty_engine_list():
    """A fully clean VT response produces engine_detections == []."""
    engines = {
        "Google":    {"category": "harmless",   "result": "clean", "method": "blacklist"},
        "Microsoft": {"category": "undetected", "result": None,    "method": "blacklist"},
    }
    report = _vt_url_report_with_engines(malicious=0, suspicious=0, last_analysis_results=engines)
    result = parse_vt_response(report, VtModeUsed.URL_REPORT)

    assert result.engine_detections == []


def test_parse_vt_response_missing_last_analysis_results():
    """Missing last_analysis_results key produces engine_detections == []."""
    report = _vt_url_report(malicious=1)
    # Deliberately omit last_analysis_results
    result = parse_vt_response(report, VtModeUsed.URL_REPORT)

    assert result.engine_detections == []


def test_parse_vt_response_none_last_analysis_results():
    """Explicit null last_analysis_results produces engine_detections == []."""
    report = _vt_url_report(malicious=1)
    report["data"]["attributes"]["last_analysis_results"] = None
    result = parse_vt_response(report, VtModeUsed.URL_REPORT)

    assert result.engine_detections == []


def test_parse_vt_response_engine_missing_fields():
    """Engine entries missing result/method/engine_update fields are handled gracefully."""
    engines = {
        "MinimalEngine": {"category": "malicious"},  # only category, no other fields
    }
    report = _vt_url_report_with_engines(malicious=1, last_analysis_results=engines)
    result = parse_vt_response(report, VtModeUsed.URL_REPORT)

    assert len(result.engine_detections) == 1
    det = result.engine_detections[0]
    assert det["engine_name"] == "MinimalEngine"
    assert det["category"] == "malicious"
    assert det["result"] is None
    assert det["method"] is None
    assert det["engine_update"] is None


def test_parse_vt_response_non_dict_engine_value_skipped():
    """Non-dict engine values (malformed response) are skipped without error."""
    engines = {
        "BadEngine": "this-is-not-a-dict",
        "GoodEngine": {"category": "malicious", "result": "Malware"},
    }
    report = _vt_url_report_with_engines(malicious=1, last_analysis_results=engines)
    result = parse_vt_response(report, VtModeUsed.URL_REPORT)

    assert len(result.engine_detections) == 1
    assert result.engine_detections[0]["engine_name"] == "GoodEngine"


def test_parse_vt_response_engine_detections_default_empty():
    """VtLookupResult.engine_detections defaults to [] when not supplied."""
    vr = VtLookupResult()
    assert vr.engine_detections == []
    assert isinstance(vr.engine_detections, list)
