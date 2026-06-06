"""
MDI VirusTotal service layer.

Provides:
  - AsyncMinIntervalLimiter  — 15s rate limit (4 req/min, VT free tier)
  - _vt_request()            — single mockable HTTP entry point for all VT calls
  - _build_vt_target()       — translate MDI normalized form → VT lookup target
  - fetch_report()           — fetch URL or domain report; handle 404→submit→refetch
  - parse_vt_response()      — report JSON → VtLookupResult
  - classify_freshness()     — last_analysis_date timestamp → Freshness enum
  - classify_triage()        — vt_hits/suspicious → TriageBucket + triage fields

No external calls are made in this module except through _vt_request().
Patch _vt_request in tests to inject mock responses without any network access.

Normalization contract (from MDI-04 input_parser):
  InputType.DOMAIN, normalized = "example.com"
    → URL report mode:    VT target = "http://example.com/"  (vt_mode_used = url_report)
    → domain report mode: VT target = "example.com"          (vt_mode_used = domain_report)
  InputType.URL, normalized = "https://example.net/path"
    → VT target = "https://example.net/path"                 (vt_mode_used = url_report)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from models import (
    AgeBucket,
    EvidenceStatus,
    Freshness,
    InputType,
    LiveStatus,
    MdiError,
    MdiProcessingStatus,
    RecommendedAction,
    TriageBucket,
    TriageConfidence,
    VtModeUsed,
)
from services import triage_rules

logger = logging.getLogger("mdi.vt_service")

VT_BASE_URL = "https://www.virustotal.com/api/v3"

# Stale threshold in days — report older than this is STALE.
# Default is 7 days (corrected MDI-09 / MDI-09A); aligns with Pydantic model defaults.
DEFAULT_STALE_THRESHOLD_DAYS: int = 7
VERY_STALE_THRESHOLD_DAYS: int = 30


# ── Rate limiter ───────────────────────────────────────────────────────────────

class AsyncMinIntervalLimiter:
    """
    Enforces a minimum time gap between acquired slots.
    15 seconds = 4 requests per minute (VT free-tier rate limit).
    Set min_interval_seconds=0.0 in tests.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._next_allowed: float = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_allowed = time.monotonic() + self._min_interval


# Module-level limiter — replace in tests with AsyncMinIntervalLimiter(0.0)
_VT_LIMITER = AsyncMinIntervalLimiter(min_interval_seconds=15.0)


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class VtLookupResult:
    """Parsed result from a single VT report fetch."""
    vt_malicious: int = 0
    vt_suspicious: int = 0
    vt_harmless: int = 0
    vt_total_engines: int = 0
    vt_hits: int = 0        # malicious count (for PRD FLAGGED rule)
    vt_ratio: str = "0/0"
    vt_scan_date: Optional[datetime] = None
    freshness: Freshness = Freshness.UNKNOWN
    vt_mode_used: VtModeUsed = VtModeUsed.NOT_CHECKED
    error: Optional[MdiError] = None
    calls_made: int = 0     # how many VT API calls were consumed (for quota accounting)
    # MDI-14: malicious/suspicious engine detections only; [] for clean results
    engine_detections: "List[Dict[str, Any]]" = field(default_factory=list)


# ── Internal HTTP call ─────────────────────────────────────────────────────────

async def _vt_request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    data: Optional[Dict[str, str]] = None,
) -> httpx.Response:
    """
    Single entry point for all VT HTTP calls.

    PATCH THIS IN TESTS — every VT integration test must mock this function.
    No direct httpx calls anywhere else in this module.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.request(method, url, headers=headers, data=data)


def _vt_headers(api_key: str) -> Dict[str, str]:
    return {"x-apikey": api_key, "accept": "application/json"}


def _vt_url_id(url: str) -> str:
    """Base64url-encode a URL (without padding) — standard VT URL ID."""
    return base64.urlsafe_b64encode(url.encode()).decode().strip("=")


def _vt_error(code: str, message: str, retriable: bool = False) -> MdiError:
    return MdiError(code=code, message=message, source="vt_service", retriable=retriable)


# ── Normalization translation ──────────────────────────────────────────────────

def _build_vt_target(
    input_normalized: str,
    input_type: InputType,
    use_domain_reports: bool,
) -> Tuple[str, VtModeUsed]:
    """
    Translate MDI's stored normalized form into the VT API lookup target.

    MDI stores bare domains as "example.com" (InputType.DOMAIN).
    VT URL-report mode needs "http://example.com/" as the lookup target.
    This translation happens here, not in the parser.

    Returns: (vt_target, vt_mode_used)
    """
    if input_type == InputType.URL:
        return input_normalized, VtModeUsed.URL_REPORT

    # Bare domain
    if use_domain_reports:
        return input_normalized, VtModeUsed.DOMAIN_REPORT
    # URL-report mode for bare domain: wrap with http://
    return f"http://{input_normalized}/", VtModeUsed.URL_REPORT


# ── Response parsing ───────────────────────────────────────────────────────────

def parse_vt_response(
    report: Dict[str, Any],
    vt_mode_used: VtModeUsed,
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
) -> VtLookupResult:
    """
    Parse a VT report JSON body into a VtLookupResult.
    Handles missing/malformed fields gracefully.
    """
    attrs: Dict[str, Any] = (
        (report.get("data") or {})
        .get("attributes") or {}
    )
    stats: Dict[str, Any] = attrs.get("last_analysis_stats") or {}

    malicious   = int(stats.get("malicious")   or 0)
    suspicious  = int(stats.get("suspicious")  or 0)
    harmless    = int(stats.get("harmless")    or 0)
    undetected  = int(stats.get("undetected")  or 0)
    timeout_cnt = int(stats.get("timeout")     or 0)
    total       = malicious + suspicious + harmless + undetected + timeout_cnt
    flagging    = malicious + suspicious

    raw_date = attrs.get("last_analysis_date")
    scan_ts: Optional[int] = None
    if raw_date is not None:
        try:
            scan_ts = int(raw_date)
        except (ValueError, TypeError):
            scan_ts = None

    scan_dt: Optional[datetime] = None
    if scan_ts:
        scan_dt = datetime.fromtimestamp(scan_ts, tz=timezone.utc)

    freshness = classify_freshness(scan_ts, stale_threshold_days=stale_threshold_days)

    # MDI-14: extract malicious/suspicious engine detections only (never harmless rows)
    engine_detections: List[Dict[str, Any]] = []
    raw_engines: Dict[str, Any] = attrs.get("last_analysis_results") or {}
    if isinstance(raw_engines, dict):
        for engine_name, details in raw_engines.items():
            if not isinstance(details, dict):
                continue
            category = details.get("category") or ""
            if category not in ("malicious", "suspicious"):
                continue
            engine_detections.append({
                "engine_name": str(engine_name),
                "category": category,
                "result": details.get("result") or None,
                "method": details.get("method") or None,
                "engine_update": details.get("engine_update") or None,
            })

    return VtLookupResult(
        vt_malicious=malicious,
        vt_suspicious=suspicious,
        vt_harmless=harmless,
        vt_total_engines=total,
        vt_hits=malicious,              # PRD: FLAGGED = vt_hits (malicious) >= 1
        vt_ratio=f"{flagging}/{total}" if total else f"{flagging}/0",
        vt_scan_date=scan_dt,
        freshness=freshness,
        vt_mode_used=vt_mode_used,
        error=None,
        calls_made=0,                   # filled in by fetch_report
        engine_detections=engine_detections,
    )


# ── Freshness classification ───────────────────────────────────────────────────

def classify_freshness(
    last_analysis_ts: Optional[int],
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
) -> Freshness:
    """
    Map VT last_analysis_date → Freshness enum.

    Bands (matching MdiResultItem Freshness doc):
      FRESH      — < stale_threshold_days (default 5)
      STALE      — 5–30 days
      VERY_STALE — > 30 days
      NEVER_SCANNED — None / null
    """
    if not last_analysis_ts:
        return Freshness.NEVER_SCANNED
    age_days = (time.time() - last_analysis_ts) / 86400
    if age_days < stale_threshold_days:
        return Freshness.FRESH
    if age_days <= VERY_STALE_THRESHOLD_DAYS:
        return Freshness.STALE
    return Freshness.VERY_STALE


# ── Triage classification ──────────────────────────────────────────────────────

def classify_triage(result: VtLookupResult) -> Tuple[
    TriageBucket, TriageConfidence, RecommendedAction, EvidenceStatus
]:
    """
    Compatibility shim — delegates to triage_rules.decide().

    Callers should prefer using triage_rules.decide() directly with a full
    TriageInput, which supports age_bucket, live_status, and triage_reason.
    This shim is kept for any legacy call sites; job_processor uses decide() directly.
    """
    errors = [result.error] if result.error else []
    processing_status = (
        MdiProcessingStatus.ERROR if result.error else MdiProcessingStatus.DONE
    )
    inp = triage_rules.TriageInput(
        domain_hold_has_hold=False,
        processing_status=processing_status,
        vt_hits=result.vt_malicious,
        vt_suspicious=result.vt_suspicious,
        vt_total_engines=result.vt_total_engines,
        freshness=result.freshness,
        live_status=LiveStatus.NOT_CHECKED,
        age_bucket=AgeBucket.UNKNOWN,
        errors=errors,
    )
    dec = triage_rules.decide(inp)
    return (dec.triage_bucket, dec.triage_confidence, dec.recommended_action, dec.evidence_status)


# ── Core fetch functions ───────────────────────────────────────────────────────

async def _fetch_url_report(
    url_target: str,
    headers: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], Optional[MdiError], int]:
    """
    Fetch a VT URL analysis report.
    Handles 404 → submit → re-fetch flow (up to 3 API calls).

    Returns: (report_dict, error, calls_made)
    error is None on success.
    """
    url_id = _vt_url_id(url_target)
    calls = 0

    # First fetch
    await _VT_LIMITER.acquire()
    try:
        resp = await _vt_request("GET", f"{VT_BASE_URL}/urls/{url_id}", headers=headers)
        calls += 1
    except httpx.TimeoutException:
        return None, _vt_error("vt_timeout", "VT request timed out.", retriable=True), calls
    except Exception as exc:
        return None, _vt_error("vt_connection", f"Connection error: {exc}", retriable=True), calls

    if resp.status_code == 200:
        return resp.json(), None, calls

    if resp.status_code == 404:
        # Submit URL for analysis
        await _VT_LIMITER.acquire()
        try:
            submit = await _vt_request("POST", f"{VT_BASE_URL}/urls", headers=headers, data={"url": url_target})
            calls += 1
        except httpx.TimeoutException:
            return None, _vt_error("vt_timeout", "VT submit timed out.", retriable=True), calls
        except Exception as exc:
            return None, _vt_error("vt_connection", f"Submit connection error: {exc}", retriable=True), calls

        if submit.status_code == 429:
            return None, _vt_error("vt_429", "VT rate limit hit during URL submit.", retriable=True), calls
        if submit.status_code >= 400:
            return None, _vt_error(
                "vt_submit_error",
                f"VT URL submit returned HTTP {submit.status_code}.",
            ), calls

        # Re-fetch after submit
        await _VT_LIMITER.acquire()
        try:
            resp2 = await _vt_request("GET", f"{VT_BASE_URL}/urls/{url_id}", headers=headers)
            calls += 1
        except httpx.TimeoutException:
            return None, _vt_error("vt_timeout", "VT re-fetch timed out.", retriable=True), calls
        except Exception as exc:
            return None, _vt_error("vt_connection", f"Re-fetch connection error: {exc}", retriable=True), calls

        if resp2.status_code == 200:
            return resp2.json(), None, calls
        return None, _vt_error(
            "vt_server_error",
            f"VT re-fetch returned HTTP {resp2.status_code}.",
        ), calls

    if resp.status_code == 401:
        return None, _vt_error("vt_auth", "VT API key is invalid or missing.", retriable=False), calls
    if resp.status_code == 429:
        return None, _vt_error("vt_429", "VT rate limit reached.", retriable=True), calls
    return None, _vt_error(
        "vt_server_error",
        f"VT returned HTTP {resp.status_code}.",
    ), calls


async def _fetch_domain_report(
    domain: str,
    headers: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], Optional[MdiError], int]:
    """
    Fetch a VT domain analysis report (domain-report mode).
    Domains are always indexed; no 404→submit flow.

    Returns: (report_dict, error, calls_made)
    """
    calls = 0
    await _VT_LIMITER.acquire()
    try:
        resp = await _vt_request("GET", f"{VT_BASE_URL}/domains/{domain}", headers=headers)
        calls += 1
    except httpx.TimeoutException:
        return None, _vt_error("vt_timeout", "VT domain request timed out.", retriable=True), calls
    except Exception as exc:
        return None, _vt_error("vt_connection", f"Connection error: {exc}", retriable=True), calls

    if resp.status_code == 200:
        return resp.json(), None, calls
    if resp.status_code == 404:
        return None, _vt_error("vt_not_found", f"Domain '{domain}' not found in VT.", retriable=False), calls
    if resp.status_code == 401:
        return None, _vt_error("vt_auth", "VT API key is invalid or missing.", retriable=False), calls
    if resp.status_code == 429:
        return None, _vt_error("vt_429", "VT rate limit reached.", retriable=True), calls
    return None, _vt_error(
        "vt_server_error",
        f"VT returned HTTP {resp.status_code}.",
    ), calls


# ── Public API ─────────────────────────────────────────────────────────────────

async def fetch_report(
    input_normalized: str,
    input_type: InputType,
    *,
    use_domain_reports: bool = False,
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
) -> VtLookupResult:
    """
    Fetch and parse a VT report for a single MDI input item.

    Reads VT_API_KEY from environment. Never logs the key.
    Translates MDI's stored normalized form to the VT lookup target.

    Returns a VtLookupResult. On error, result.error is set and
    result.calls_made reflects actual calls made (for quota accounting).
    """
    api_key = os.environ.get("VT_API_KEY", "")
    if not api_key:
        return VtLookupResult(
            error=_vt_error("no_api_key", "VT_API_KEY is not configured.", retriable=False),
            calls_made=0,
        )

    headers = _vt_headers(api_key)
    vt_target, vt_mode = _build_vt_target(input_normalized, input_type, use_domain_reports)

    if vt_mode == VtModeUsed.DOMAIN_REPORT:
        report, error, calls = await _fetch_domain_report(vt_target, headers)
    else:
        report, error, calls = await _fetch_url_report(vt_target, headers)

    if error:
        err_result = VtLookupResult(
            vt_mode_used=vt_mode,
            error=error,
            calls_made=calls,
        )
        return err_result

    result = parse_vt_response(report, vt_mode, stale_threshold_days)
    result.calls_made = calls
    return result
