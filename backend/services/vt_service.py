"""
MDI VirusTotal service layer.

Provides:
  - AsyncMinIntervalLimiter  — 15s rate limit (4 req/min, VT free tier)
  - _vt_request()            — single mockable HTTP entry point for all VT calls
  - _build_vt_target()       — translate MDI normalized form → VT lookup target
  - fetch_report()           — fetch URL or domain report; URL 404→submit-only (MDI-57A)
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
# Default is 30 days (MDI-57A); aligns with Pydantic model defaults.
DEFAULT_STALE_THRESHOLD_DAYS: int = 30

# Very-stale boundary scales with the operator threshold (MDI-57A):
#   very_stale_after_days = max(2 * stale_threshold_days, VERY_STALE_MIN_DAYS)
# With threshold 30 → boundary 60; threshold 7 → boundary 30; threshold 45 → 90.
VERY_STALE_MIN_DAYS: int = 30


def very_stale_after_days(stale_threshold_days: int) -> int:
    """Return the age in days beyond which a report is VERY_STALE."""
    return max(2 * stale_threshold_days, VERY_STALE_MIN_DAYS)


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
    # MDI-49: limited URL evidence from VT URL report attributes (URL mode only)
    vt_targeted_brand: Optional[str] = None
    vt_targeted_brand_sources: List[str] = field(default_factory=list)
    vt_redirection_chain: List[str] = field(default_factory=list)
    vt_last_final_url: Optional[str] = None


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
    from services.error_taxonomy import ErrorSeverity, make_mdi_error

    severity = None
    if code == "scan_not_supported":
        severity = ErrorSeverity.SKIP.value
    elif code == "vt_scan_pending":
        severity = ErrorSeverity.WARNING.value
    return make_mdi_error(
        code=code,
        message=message,
        source="vt_service",
        retriable=retriable,
        severity=severity,
    )


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

def extract_vt_url_evidence(
    attrs: Dict[str, Any],
    vt_mode_used: VtModeUsed,
) -> Tuple[Optional[str], List[str], List[str], Optional[str]]:
    """
    Extract limited VT URL evidence fields from report attributes.

    Populated only for URL reports (not domain reports). Does not affect triage.
    """
    if vt_mode_used != VtModeUsed.URL_REPORT:
        return None, [], [], None

    brand_sources: List[str] = []
    brand_values: List[str] = []
    raw_brand = attrs.get("targeted_brand")
    if isinstance(raw_brand, dict):
        for engine, brand in raw_brand.items():
            if brand is None:
                continue
            brand_str = str(brand).strip()
            if not brand_str:
                continue
            brand_sources.append(str(engine))
            brand_values.append(brand_str)

    seen: set[str] = set()
    unique_brands: List[str] = []
    for brand in brand_values:
        key = brand.casefold()
        if key not in seen:
            seen.add(key)
            unique_brands.append(brand)

    redirection_chain: List[str] = []
    raw_chain = attrs.get("redirection_chain")
    if isinstance(raw_chain, list):
        redirection_chain = [
            str(url).strip()
            for url in raw_chain
            if url is not None and str(url).strip()
        ]

    last_final_url: Optional[str] = None
    raw_final = attrs.get("last_final_url")
    if raw_final is not None:
        final_str = str(raw_final).strip()
        if final_str:
            last_final_url = final_str

    targeted_brand = "; ".join(unique_brands) if unique_brands else None
    return targeted_brand, sorted(brand_sources), redirection_chain, last_final_url


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

    (
        vt_targeted_brand,
        vt_targeted_brand_sources,
        vt_redirection_chain,
        vt_last_final_url,
    ) = extract_vt_url_evidence(attrs, vt_mode_used)

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
        vt_targeted_brand=vt_targeted_brand,
        vt_targeted_brand_sources=vt_targeted_brand_sources,
        vt_redirection_chain=vt_redirection_chain,
        vt_last_final_url=vt_last_final_url,
    )


# ── Freshness classification ───────────────────────────────────────────────────

def classify_freshness(
    last_analysis_ts: Optional[int],
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
) -> Freshness:
    """
    Map VT last_analysis_date → Freshness enum.

    Bands (MDI-57A):
      FRESH      — age < stale_threshold_days
      STALE      — stale_threshold_days ≤ age ≤ very_stale_after_days(threshold)
      VERY_STALE — age > very_stale_after_days(threshold)
      NEVER_SCANNED — None / null

    very_stale_after_days = max(2 × stale_threshold_days, 30).
    Default threshold 30 → fresh < 30 d, stale 30–60 d, very stale > 60 d.
    """
    if not last_analysis_ts:
        return Freshness.NEVER_SCANNED
    age_days = (time.time() - last_analysis_ts) / 86400
    if age_days < stale_threshold_days:
        return Freshness.FRESH
    if age_days <= very_stale_after_days(stale_threshold_days):
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

def report_is_completed(result: "VtLookupResult") -> bool:
    """
    True only when the parsed VT report is a provably completed analysis:
    a last_analysis_date is present AND at least one engine reported.

    A 200 URL report with empty/zero engine stats and no scan date is a
    URL object whose analysis has not completed — it is NOT clean evidence.
    """
    return result.vt_scan_date is not None and result.vt_total_engines > 0


def _pending_error(message: str) -> MdiError:
    """Build the vt_scan_pending WARNING attached to pending-analysis rows."""
    return _vt_error("vt_scan_pending", message, retriable=True)


_PENDING_SUBMITTED_MSG = (
    "URL submitted to VirusTotal for analysis; no URL report is available yet. "
    "This is not a clean result. Use Refresh Report later (1 VT call)."
)
_PENDING_NOT_READY_MSG = (
    "VirusTotal has this URL but analysis is not complete; no usable engine "
    "results yet. This is not a clean result. Use Refresh Report later (1 VT call)."
)


async def _fetch_url_report(
    url_target: str,
    headers: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], Optional[MdiError], int]:
    """
    Fetch a VT URL analysis report (submit-only flow, MDI-57A).

    404 → POST submit → STOP (no immediate re-fetch). A new URL costs
    exactly 2 VT calls (GET + POST) and returns a vt_scan_pending WARNING.

    Returns: (report_dict, error, calls_made)
    error is None on success (report present, completedness checked by caller).
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
        # No URL report exists for this exact URL. Not clean — submit and stop.
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

        # Submit accepted: VT returns an analysis id, not a completed report.
        # MDI-57A: stop here. The operator refreshes later (1 call) when ready.
        return None, _pending_error(_PENDING_SUBMITTED_MSG), calls

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


# ── Refresh (GET-only) helpers ─────────────────────────────────────────────────

async def _get_existing_url_report(
    url_target: str,
    headers: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], Optional[MdiError], int]:
    """GET URL report only — no 404 submit. Used by refresh_report."""
    url_id = _vt_url_id(url_target)
    calls = 0
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
        return None, _vt_error(
            "vt_not_found",
            "No existing VT URL report found to refresh.",
            retriable=False,
        ), calls
    if resp.status_code == 401:
        return None, _vt_error("vt_auth", "VT API key is invalid or missing.", retriable=False), calls
    if resp.status_code == 429:
        return None, _vt_error("vt_429", "VT rate limit reached.", retriable=True), calls
    return None, _vt_error(
        "vt_server_error",
        f"VT returned HTTP {resp.status_code}.",
    ), calls


# ── Scan (POST + bounded poll) helpers ─────────────────────────────────────────

MAX_SCAN_POLL_ATTEMPTS = 3  # GET polls after POST (2–4 URL scan; 2–5 domain rescan)

# Conservative per-item scan quota estimates (manual actions).
URL_SCAN_QUOTA_MIN = 2
URL_SCAN_QUOTA_MAX = 4
DOMAIN_RESCAN_QUOTA_MIN = 2
DOMAIN_RESCAN_QUOTA_MAX = 5  # POST analyse + polls + final domain GET


async def _submit_url_for_scan(
    url_target: str,
    headers: Dict[str, str],
) -> Tuple[Optional[MdiError], int]:
    """POST URL to VT for new analysis. Returns (error, calls_made)."""
    calls = 0
    await _VT_LIMITER.acquire()
    try:
        resp = await _vt_request("POST", f"{VT_BASE_URL}/urls", headers=headers, data={"url": url_target})
        calls += 1
    except httpx.TimeoutException:
        return _vt_error("vt_timeout", "VT submit timed out.", retriable=True), calls
    except Exception as exc:
        return _vt_error("vt_connection", f"Submit connection error: {exc}", retriable=True), calls

    if resp.status_code == 429:
        return _vt_error("vt_429", "VT rate limit hit during URL submit.", retriable=True), calls
    if resp.status_code >= 400:
        return _vt_error(
            "vt_submit_error",
            f"VT URL submit returned HTTP {resp.status_code}.",
        ), calls
    return None, calls


async def _poll_url_report_after_scan(
    url_target: str,
    headers: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], Optional[MdiError], int]:
    """Bounded GET polls after scan submit. Returns (report, error, calls_made)."""
    url_id = _vt_url_id(url_target)
    calls = 0
    last_status = 0
    saw_incomplete_200 = False

    for _ in range(MAX_SCAN_POLL_ATTEMPTS):
        await _VT_LIMITER.acquire()
        try:
            resp = await _vt_request("GET", f"{VT_BASE_URL}/urls/{url_id}", headers=headers)
            calls += 1
            last_status = resp.status_code
        except httpx.TimeoutException:
            return None, _vt_error("vt_timeout", "VT poll timed out.", retriable=True), calls
        except Exception as exc:
            return None, _vt_error("vt_connection", f"Poll connection error: {exc}", retriable=True), calls

        if resp.status_code == 200:
            body = resp.json()
            parsed = parse_vt_response(body, VtModeUsed.URL_REPORT)
            if report_is_completed(parsed):
                return body, None, calls
            saw_incomplete_200 = True
            continue
        if resp.status_code == 401:
            return None, _vt_error("vt_auth", "VT API key is invalid or missing.", retriable=False), calls
        if resp.status_code == 429:
            return None, _vt_error("vt_429", "VT rate limit reached during poll.", retriable=True), calls

    if saw_incomplete_200:
        return None, _pending_error(_PENDING_NOT_READY_MSG), calls

    return None, _vt_error(
        "vt_scan_pending",
        f"VT scan submitted but report not ready after {MAX_SCAN_POLL_ATTEMPTS} polls "
        f"(last HTTP {last_status}). Retry later.",
        retriable=True,
    ), calls


async def _submit_domain_for_rescan(
    domain: str,
    headers: Dict[str, str],
) -> Tuple[Optional[str], Optional[MdiError], int]:
    """POST domain for VT reanalysis. Returns (analysis_id, error, calls_made)."""
    calls = 0
    await _VT_LIMITER.acquire()
    try:
        resp = await _vt_request(
            "POST",
            f"{VT_BASE_URL}/domains/{domain}/analyse",
            headers=headers,
        )
        calls += 1
    except httpx.TimeoutException:
        return None, _vt_error("vt_timeout", "VT domain rescan submit timed out.", retriable=True), calls
    except Exception as exc:
        return None, _vt_error("vt_connection", f"Domain rescan submit error: {exc}", retriable=True), calls

    if resp.status_code == 429:
        return None, _vt_error("vt_429", "VT rate limit hit during domain rescan.", retriable=True), calls
    if resp.status_code == 401:
        return None, _vt_error("vt_auth", "VT API key is invalid or missing.", retriable=False), calls
    if resp.status_code >= 400:
        return None, _vt_error(
            "vt_submit_error",
            f"VT domain rescan returned HTTP {resp.status_code}.",
        ), calls

    body = resp.json() if resp.content else {}
    analysis_id = (body.get("data") or {}).get("id")
    if not analysis_id:
        return None, _vt_error(
            "vt_submit_error",
            "VT domain rescan response missing analysis id.",
        ), calls
    return analysis_id, None, calls


async def _poll_analysis_after_rescan(
    analysis_id: str,
    headers: Dict[str, str],
) -> Tuple[bool, Optional[MdiError], int]:
    """Bounded polls on GET /analyses/{id}. Returns (completed, error, calls_made)."""
    calls = 0
    last_status = ""

    for _ in range(MAX_SCAN_POLL_ATTEMPTS):
        await _VT_LIMITER.acquire()
        try:
            resp = await _vt_request(
                "GET",
                f"{VT_BASE_URL}/analyses/{analysis_id}",
                headers=headers,
            )
            calls += 1
        except httpx.TimeoutException:
            return False, _vt_error("vt_timeout", "VT analysis poll timed out.", retriable=True), calls
        except Exception as exc:
            return False, _vt_error("vt_connection", f"Analysis poll error: {exc}", retriable=True), calls

        if resp.status_code == 401:
            return False, _vt_error("vt_auth", "VT API key is invalid or missing.", retriable=False), calls
        if resp.status_code == 429:
            return False, _vt_error("vt_429", "VT rate limit reached during analysis poll.", retriable=True), calls
        if resp.status_code != 200:
            continue

        attrs = (resp.json().get("data") or {}).get("attributes") or {}
        last_status = str(attrs.get("status") or "")
        if last_status == "completed":
            return True, None, calls

    return False, _vt_error(
        "vt_scan_pending",
        f"VT domain rescan submitted but analysis not complete after {MAX_SCAN_POLL_ATTEMPTS} polls "
        f"(last status: {last_status or 'unknown'}). Retry later.",
        retriable=True,
    ), calls


async def _request_domain_rescan(
    domain: str,
    headers: Dict[str, str],
    *,
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
) -> VtLookupResult:
    """POST domain analyse, poll analysis, then GET updated domain report."""
    calls = 0

    analysis_id, submit_err, submit_calls = await _submit_domain_for_rescan(domain, headers)
    calls += submit_calls
    if submit_err:
        return VtLookupResult(
            vt_mode_used=VtModeUsed.DOMAIN_REPORT,
            error=submit_err,
            calls_made=calls,
        )

    completed, poll_err, poll_calls = await _poll_analysis_after_rescan(analysis_id, headers)
    calls += poll_calls
    if not completed:
        return VtLookupResult(
            vt_mode_used=VtModeUsed.DOMAIN_REPORT,
            error=poll_err,
            calls_made=calls,
        )

    report, fetch_err, fetch_calls = await _fetch_domain_report(domain, headers)
    calls += fetch_calls
    if fetch_err:
        return VtLookupResult(
            vt_mode_used=VtModeUsed.DOMAIN_REPORT,
            error=fetch_err,
            calls_made=calls,
        )

    result = parse_vt_response(report, VtModeUsed.DOMAIN_REPORT, stale_threshold_days)
    result.calls_made = calls
    return result


def _pending_result(
    vt_mode: VtModeUsed,
    pending_error: MdiError,
    calls: int,
) -> VtLookupResult:
    """
    Build the submitted/pending-analysis lookup result (MDI-57A).

    Truthful state: no engine evidence, NEVER_SCANNED freshness, empty ratio
    (never a visible 0/0), vt_scan_pending WARNING attached.
    """
    return VtLookupResult(
        vt_total_engines=0,
        vt_hits=0,
        vt_ratio="",
        vt_scan_date=None,
        freshness=Freshness.NEVER_SCANNED,
        vt_mode_used=vt_mode,
        error=pending_error,
        calls_made=calls,
    )


def scan_quota_estimate_for_mode(vt_mode: VtModeUsed) -> Tuple[int, int]:
    """Return conservative (min, max) VT quota units for a manual scan/rescan."""
    if vt_mode == VtModeUsed.DOMAIN_REPORT:
        return DOMAIN_RESCAN_QUOTA_MIN, DOMAIN_RESCAN_QUOTA_MAX
    return URL_SCAN_QUOTA_MIN, URL_SCAN_QUOTA_MAX


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
        if error.code == "vt_scan_pending":
            return _pending_result(vt_mode, error, calls)
        return VtLookupResult(
            vt_mode_used=vt_mode,
            error=error,
            calls_made=calls,
        )

    result = parse_vt_response(report, vt_mode, stale_threshold_days)
    result.calls_made = calls

    # MDI-57A: a 200 URL report without provable completed analysis
    # (no scan date / no engine results) is pending, never clean.
    if vt_mode == VtModeUsed.URL_REPORT and not report_is_completed(result):
        return _pending_result(vt_mode, _pending_error(_PENDING_NOT_READY_MSG), calls)

    return result


async def refresh_report(
    input_normalized: str,
    input_type: InputType,
    *,
    use_domain_reports: bool = False,
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
) -> VtLookupResult:
    """
    Refresh an existing VT report (GET only — no submit).

    Consumes 1 quota unit on success. Does not escalate to scan on 404.
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
        report, error, calls = await _get_existing_url_report(vt_target, headers)

    if error:
        return VtLookupResult(vt_mode_used=vt_mode, error=error, calls_made=calls)

    result = parse_vt_response(report, vt_mode, stale_threshold_days)
    result.calls_made = calls

    # MDI-57A: refreshing a pending row whose analysis is still not complete
    # must stay pending, not become clean.
    if vt_mode == VtModeUsed.URL_REPORT and not report_is_completed(result):
        return _pending_result(vt_mode, _pending_error(_PENDING_NOT_READY_MSG), calls)

    return result


async def request_new_scan(
    input_normalized: str,
    input_type: InputType,
    *,
    use_domain_reports: bool = False,
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
) -> VtLookupResult:
    """
    Request a new VT analysis for an MDI item.

    Routes by VT mode:
      - domain_report → POST /domains/{domain}/analyse + analysis poll + domain GET
      - url_report    → POST /urls + bounded URL report poll (unchanged)
    """
    api_key = os.environ.get("VT_API_KEY", "")
    if not api_key:
        return VtLookupResult(
            error=_vt_error("no_api_key", "VT_API_KEY is not configured.", retriable=False),
            calls_made=0,
        )

    vt_target, vt_mode = _build_vt_target(input_normalized, input_type, use_domain_reports)
    headers = _vt_headers(api_key)

    if vt_mode == VtModeUsed.DOMAIN_REPORT:
        return await _request_domain_rescan(
            vt_target,
            headers,
            stale_threshold_days=stale_threshold_days,
        )

    calls = 0
    submit_err, submit_calls = await _submit_url_for_scan(vt_target, headers)
    calls += submit_calls
    if submit_err:
        return VtLookupResult(vt_mode_used=vt_mode, error=submit_err, calls_made=calls)

    report, poll_err, poll_calls = await _poll_url_report_after_scan(vt_target, headers)
    calls += poll_calls
    if poll_err:
        if poll_err.code == "vt_scan_pending":
            return _pending_result(vt_mode, poll_err, calls)
        return VtLookupResult(vt_mode_used=vt_mode, error=poll_err, calls_made=calls)

    result = parse_vt_response(report, vt_mode, stale_threshold_days)
    result.calls_made = calls

    # MDI-62: same completedness gate as fetch_report / refresh_report.
    if vt_mode == VtModeUsed.URL_REPORT and not report_is_completed(result):
        return _pending_result(vt_mode, _pending_error(_PENDING_NOT_READY_MSG), calls)

    return result


def scan_supported_for_item(
    input_type: InputType,
    use_domain_reports: bool,
) -> bool:
    """Return True when manual request_new_scan is supported for this item."""
    del use_domain_reports  # domain-report bare domains support domain rescan (MDI-28)
    return input_type in (InputType.URL, InputType.DOMAIN)
