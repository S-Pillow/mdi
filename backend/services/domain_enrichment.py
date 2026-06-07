"""
MDI domain enrichment service — RDAP/WHOIS lookup before VT processing.

Populates enrichment fields for a registered domain:
  created_at, age_bucket, registrar, epp_status, nameservers, domain_hold.

Lookup strategy:
  1. RDAP primary  — GET https://rdap.org/domain/{registered_domain}
     - Rate-limited: minimum 1.1 s between requests (_rdap_acquire_slot).
     - 200: parse and return.
     - 404: domain not found in RDAP registry → try WHOIS fallback.
     - 429: read Retry-After header (or default 5 s), wait, retry once only.
       If retry also 429/error → WHOIS fallback.
     - 5xx / network / timeout: try WHOIS fallback.
  2. WHOIS fallback — blocking call in thread executor.
     - Failure: return partial EnrichmentResult with error; item continues to VT.

Rate-limit design (rdap.org):
  - rdap.org allows ~10 requests per 10 seconds (≈ 1 req/s).
  - MDI enforces a 1.1 s minimum gap between RDAP requests via _rdap_acquire_slot().
  - _rdap_acquire_slot() is a single mockable entry point for tests.
  - The per-job domain cache (_enrich_items in job_processor) avoids repeat lookups.

Hold detection:
  epp_status strings from RDAP/WHOIS are fed through the existing
  hold_detection.detect_hold() function, which parses clientHold/serverHold.

Registered domain extraction:
  - DOMAIN inputs: hostname is already the registered domain.
  - URL inputs: tldextract extracts registered domain from the full URL.
  - IP addresses: skip enrichment, return NOT_CHECKED result.
  - IDN/unicode: each label is encoded to punycode before RDAP query.

Hard guarantees:
  - No VT calls.
  - No DNS resolution beyond what httpx does internally.
  - Enrichment failures are non-fatal: EnrichmentResult.error is set,
    the item proceeds to VT with UNKNOWN enrichment fields.
  - Raw domain names / registrar names / nameservers are NEVER written to
    usage-history JSONL or any runtime file. Only aggregate counts are logged.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
import tldextract

from models import (
    AgeBucket,
    DomainHold,
    DomainHoldType,
    DomainStatusSource,
    InputType,
    MdiError,
)
from services.age_bucket import compute_age_bucket
from services.error_taxonomy import make_mdi_error
from services.hold_detection import detect_hold

logger = logging.getLogger("mdi.domain_enrichment")


def _enrichment_error(code: str, message: str) -> MdiError:
    return make_mdi_error(
        code=code,
        message=message,
        source="domain_enrichment",
        retriable=True,
    )

# Timeout for individual RDAP requests (seconds)
_RDAP_TIMEOUT_SECONDS: float = 10.0

# Minimum interval between RDAP requests (rdap.org allows ~10 req/10s; 1.1 s gives headroom)
_RDAP_MIN_INTERVAL_SECONDS: float = 1.1

# Default wait on 429 when Retry-After header is absent or unparseable
_RDAP_RETRY_DELAY_DEFAULT_SECONDS: float = 5.0

# Maximum Retry-After to honour (cap to prevent indefinite blocking)
_RDAP_RETRY_AFTER_MAX_SECONDS: float = 60.0

# Module-level timestamp of last RDAP call (seconds, monotonic)
_rdap_last_call_ts: float = 0.0


# ── Rate limiter ──────────────────────────────────────────────────────────────

async def _rdap_acquire_slot() -> None:
    """
    Single mockable rate-limiter entry point.

    Enforces _RDAP_MIN_INTERVAL_SECONDS (1.1 s) minimum gap between RDAP
    requests to stay within rdap.org's ~10 req/10 s limit with headroom.

    Monotonic time avoids event-loop-boundary issues across asyncio.run() calls.
    Not concurrency-safe for simultaneous coroutines, but MDI enriches items
    sequentially per job — accepted MVP risk.
    """
    global _rdap_last_call_ts
    import time as _time
    now = _time.monotonic()
    gap = _RDAP_MIN_INTERVAL_SECONDS - (now - _rdap_last_call_ts)
    if gap > 0:
        await asyncio.sleep(gap)
    _rdap_last_call_ts = _time.monotonic()


def _parse_retry_after(headers: Any, fallback: float) -> float:
    """
    Parse the Retry-After response header into a safe wait duration.

    Accepts a numeric seconds value only (HTTP-date format is not supported).
    Returns fallback if the header is absent, non-numeric, or out of range.
    Caps the returned value at _RDAP_RETRY_AFTER_MAX_SECONDS for safety.
    """
    raw = ""
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After") or ""
    except Exception:
        return fallback
    if not raw:
        return fallback
    try:
        val = float(raw)
        if val <= 0:
            return fallback
        return min(val, _RDAP_RETRY_AFTER_MAX_SECONDS)
    except (ValueError, TypeError):
        return fallback


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class EnrichmentResult:
    """
    Enrichment data for a single registered domain.

    All fields are optional — partial results are normal when RDAP/WHOIS
    returns incomplete data or when a lookup fails.
    """
    registered_domain: str
    source: DomainStatusSource = DomainStatusSource.NOT_CHECKED
    created_at: Optional[datetime] = None
    age_bucket: AgeBucket = AgeBucket.UNKNOWN
    registrar: Optional[str] = None
    epp_status: List[str] = field(default_factory=list)
    nameservers: List[str] = field(default_factory=list)
    domain_hold: DomainHold = field(
        default_factory=lambda: DomainHold(
            has_hold=False,
            hold_types=[DomainHoldType.NONE],
            source=DomainStatusSource.NOT_CHECKED,
        )
    )
    error: Optional[MdiError] = None
    whois_fallback_used: bool = False


# ── Mockable entry points ─────────────────────────────────────────────────────

async def _rdap_request(url: str, client: httpx.AsyncClient) -> httpx.Response:
    """
    Single mockable RDAP HTTP entry point.

    All RDAP HTTP traffic flows through here so tests can patch this function
    without touching httpx globally.
    """
    return await client.get(url, timeout=_RDAP_TIMEOUT_SECONDS, follow_redirects=True)


def _whois_query_sync(domain: str) -> Optional[Dict[str, Any]]:
    """
    Single mockable, blocking WHOIS entry point.

    Returns a normalized dict with keys:
      creation_date: datetime or None
      registrar: str or None
      status: List[str]
      name_servers: List[str]

    Returns None if the lookup fails or the domain is not found.
    Intended to be called via asyncio.run_in_executor (blocking I/O).
    """
    try:
        import whois as whois_lib  # noqa: PLC0415

        w = whois_lib.query(domain)
        if w is None:
            return None

        # Normalize creation_date (may be datetime, list, or None)
        cd = getattr(w, "creation_date", None)
        if isinstance(cd, list):
            cd = cd[0] if cd else None

        # Normalize status (list, string, or None)
        raw_status = getattr(w, "status", None) or []
        if isinstance(raw_status, str):
            raw_status = [s.strip() for s in raw_status.replace(",", " ").split() if s.strip()]
        elif not isinstance(raw_status, list):
            raw_status = []

        # Normalize name_servers (set, list, or None)
        ns = getattr(w, "name_servers", None) or []
        if isinstance(ns, (set, frozenset)):
            ns = list(ns)
        ns = [n.lower().rstrip(".") for n in ns if n]

        return {
            "creation_date": cd,
            "registrar": getattr(w, "registrar", None),
            "status": raw_status,
            "name_servers": ns,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("WHOIS query failed for %s: %s", domain, exc)
        return None


# ── Domain extraction ─────────────────────────────────────────────────────────

def extract_registered_domain(normalized: str, input_type: InputType) -> Optional[str]:
    """
    Extract the registered domain (eTLD+1) from a normalized input.

    Returns None for IP addresses or inputs where a registered domain
    cannot be determined — callers should skip enrichment in that case.

    - DOMAIN: normalize as-is (may already contain a subdomain; tldextract
      returns the eTLD+1 portion).
    - URL: extract hostname from URL, then apply tldextract.
    - IDN (unicode domain labels): each label is encoded to punycode (A-label)
      before the RDAP query.
    """
    if input_type == InputType.URL:
        parsed = urlparse(normalized)
        hostname = (parsed.hostname or "").lower()
    else:
        hostname = normalized.lower()

    if not hostname:
        return None

    # Reject IP addresses — no RDAP for IPs
    try:
        ipaddress.ip_address(hostname)
        return None
    except ValueError:
        pass

    extracted = tldextract.extract(hostname)
    if not extracted.domain or not extracted.suffix:
        return None

    registered = f"{extracted.domain}.{extracted.suffix}"

    # Encode IDN labels to punycode (A-label form) for RDAP compatibility
    try:
        registered = ".".join(
            label.encode("idna").decode("ascii")
            for label in registered.split(".")
        )
    except (UnicodeError, UnicodeDecodeError):
        pass  # Already ASCII or encoding not possible; use as-is

    return registered


# ── RDAP response parser ──────────────────────────────────────────────────────

def _parse_rdap_response(data: Dict[str, Any], registered_domain: str) -> EnrichmentResult:
    """
    Parse a successful RDAP JSON response into an EnrichmentResult.

    Handles multiple RDAP status field formats (list of strings, status objects).
    """
    created_at: Optional[datetime] = None
    registrar: Optional[str] = None
    epp_status: List[str] = []
    nameservers: List[str] = []

    # ── created_at from events ────────────────────────────────────────────────
    for event in data.get("events", []):
        if event.get("eventAction") == "registration":
            date_str = event.get("eventDate", "")
            if date_str:
                try:
                    # Handle both "Z" suffix and "+00:00"
                    created_at = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    logger.debug("Could not parse RDAP eventDate: %s", date_str)
            break

    # ── registrar from entities ───────────────────────────────────────────────
    for entity in data.get("entities", []):
        if "registrar" in entity.get("roles", []):
            vcard = entity.get("vcardArray", [None, []])
            if len(vcard) > 1 and isinstance(vcard[1], list):
                for entry in vcard[1]:
                    if (isinstance(entry, (list, tuple)) and
                            len(entry) > 3 and entry[0] == "fn"):
                        registrar = str(entry[3]) if entry[3] else None
                        break
            break

    # ── epp_status from status field ──────────────────────────────────────────
    raw_statuses = data.get("status", [])
    if isinstance(raw_statuses, list):
        for s in raw_statuses:
            if not isinstance(s, str):
                s = str(s)
            # Strip trailing ICANN URL suffixes (e.g. "clientHold https://icann.org/...")
            clean = s.split(" https://")[0].split(" http://")[0].strip()
            if clean:
                epp_status.append(clean)

    # ── nameservers ───────────────────────────────────────────────────────────
    for ns_obj in data.get("nameservers", []):
        ldh = ns_obj.get("ldhName", "")
        if ldh:
            nameservers.append(ldh.lower().rstrip("."))

    # ── age_bucket from created_at ────────────────────────────────────────────
    age_bkt = AgeBucket.UNKNOWN
    if created_at is not None:
        age_bkt = compute_age_bucket(created_at.date())

    # ── hold detection ────────────────────────────────────────────────────────
    domain_hold = detect_hold(
        " ".join(epp_status) if epp_status else None,
        source=DomainStatusSource.RDAP,
    )

    return EnrichmentResult(
        registered_domain=registered_domain,
        source=DomainStatusSource.RDAP,
        created_at=created_at,
        age_bucket=age_bkt,
        registrar=registrar,
        epp_status=epp_status,
        nameservers=nameservers,
        domain_hold=domain_hold,
        error=None,
        whois_fallback_used=False,
    )


# ── WHOIS result parser ───────────────────────────────────────────────────────

def _parse_whois_result(
    result_dict: Dict[str, Any],
    registered_domain: str,
) -> EnrichmentResult:
    """
    Build an EnrichmentResult from a normalized WHOIS result dict.

    result_dict keys: creation_date, registrar, status (List[str]), name_servers (List[str]).
    """
    created_at: Optional[datetime] = result_dict.get("creation_date")

    # Ensure created_at is timezone-aware
    if isinstance(created_at, datetime) and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    registrar: Optional[str] = result_dict.get("registrar")
    epp_status: List[str] = result_dict.get("status") or []
    nameservers: List[str] = result_dict.get("name_servers") or []

    age_bkt = AgeBucket.UNKNOWN
    if isinstance(created_at, datetime):
        age_bkt = compute_age_bucket(created_at.date())

    domain_hold = detect_hold(
        " ".join(epp_status) if epp_status else None,
        source=DomainStatusSource.WHOIS,
    )

    return EnrichmentResult(
        registered_domain=registered_domain,
        source=DomainStatusSource.WHOIS,
        created_at=created_at,
        age_bucket=age_bkt,
        registrar=registrar,
        epp_status=epp_status,
        nameservers=nameservers,
        domain_hold=domain_hold,
        error=None,
        whois_fallback_used=True,
    )


# ── WHOIS fallback ────────────────────────────────────────────────────────────

async def _whois_fallback(registered_domain: str) -> EnrichmentResult:
    """
    Run WHOIS lookup in a thread executor; parse result.
    Returns an error-bearing EnrichmentResult on failure.
    """
    try:
        loop = asyncio.get_running_loop()
        result_dict = await loop.run_in_executor(None, _whois_query_sync, registered_domain)
    except Exception as exc:  # noqa: BLE001
        logger.debug("WHOIS executor error for %s: %s", registered_domain, exc)
        result_dict = None

    if result_dict is None:
        return EnrichmentResult(
            registered_domain=registered_domain,
            source=DomainStatusSource.UNKNOWN,
            domain_hold=DomainHold(
                has_hold=False,
                hold_types=[DomainHoldType.NONE],
                source=DomainStatusSource.NOT_CHECKED,
            ),
            error=_enrichment_error(
                "whois_failed",
                f"RDAP and WHOIS both failed for {registered_domain}.",
            ),
            whois_fallback_used=True,
        )

    return _parse_whois_result(result_dict, registered_domain)


# ── Public API ────────────────────────────────────────────────────────────────

async def enrich_domain(registered_domain: str) -> EnrichmentResult:
    """
    Look up enrichment data for a registered domain.

    Strategy:
      1. Acquire RDAP rate-limit slot (1.1 s minimum gap via _rdap_acquire_slot).
      2. RDAP via rdap.org (primary).
         - 200: parse and return.
         - 404: domain not in RDAP → WHOIS fallback.
         - 429: read Retry-After header (or default 5 s), wait, retry once.
           If retry still 429 or error → WHOIS fallback.
         - 5xx / timeout / network error: WHOIS fallback.
      3. WHOIS (fallback).
         - Failure: return EnrichmentResult with error set.

    Returns:
        EnrichmentResult with all available fields populated.
        Never raises — all error paths return a result with error set.
    """
    rdap_url = f"https://rdap.org/domain/{registered_domain}"

    try:
        async with httpx.AsyncClient() as client:
            # Enforce rate limit before initial request
            await _rdap_acquire_slot()

            try:
                resp = await _rdap_request(rdap_url, client)
            except httpx.TimeoutException:
                logger.debug("RDAP timeout for %s — trying WHOIS", registered_domain)
                return await _whois_fallback(registered_domain)
            except httpx.RequestError as exc:
                logger.debug("RDAP network error for %s: %s — trying WHOIS", registered_domain, exc)
                return await _whois_fallback(registered_domain)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    return _parse_rdap_response(data, registered_domain)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("RDAP parse error for %s: %s — trying WHOIS", registered_domain, exc)
                    return await _whois_fallback(registered_domain)

            elif resp.status_code == 404:
                logger.debug("RDAP 404 for %s — trying WHOIS", registered_domain)
                return await _whois_fallback(registered_domain)

            elif resp.status_code == 429:
                # Honour Retry-After when present; otherwise use default wait
                wait = _parse_retry_after(resp.headers, _RDAP_RETRY_DELAY_DEFAULT_SECONDS)
                logger.debug(
                    "RDAP 429 for %s — waiting %.1fs then retrying once",
                    registered_domain, wait,
                )
                await asyncio.sleep(wait)
                # Acquire rate-limit slot before the single retry
                await _rdap_acquire_slot()
                try:
                    resp2 = await _rdap_request(rdap_url, client)
                    if resp2.status_code == 200:
                        data = resp2.json()
                        return _parse_rdap_response(data, registered_domain)
                    logger.debug(
                        "RDAP retry returned %s for %s — trying WHOIS",
                        resp2.status_code, registered_domain,
                    )
                except Exception as exc2:  # noqa: BLE001
                    logger.debug("RDAP retry error for %s: %s — trying WHOIS", registered_domain, exc2)
                # Single retry exhausted → WHOIS fallback
                return await _whois_fallback(registered_domain)

            else:
                logger.debug(
                    "RDAP unexpected status %s for %s — trying WHOIS",
                    resp.status_code, registered_domain,
                )
                return await _whois_fallback(registered_domain)

    except Exception as exc:  # noqa: BLE001
        logger.warning("enrich_domain unexpected error for %s: %s", registered_domain, exc)
        return EnrichmentResult(
            registered_domain=registered_domain,
            source=DomainStatusSource.UNKNOWN,
            domain_hold=DomainHold(
                has_hold=False,
                hold_types=[DomainHoldType.NONE],
                source=DomainStatusSource.NOT_CHECKED,
            ),
            error=_enrichment_error(
                "enrichment_error",
                f"Unexpected enrichment error for {registered_domain}: {exc}",
            ),
        )
