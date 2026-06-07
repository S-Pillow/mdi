"""
MDI live_check service — SSRF-safe live HTTP check for flagged domains.

Port of the URL Activity Scanner SSRF safety chain to Python.
Implements the four-gate pipeline:

  1. URL validation (scheme, hostname blocklist, IP-literal CIDR check)
  2. DNS resolution with SSRF re-check of all resolved IPs
  3. HTTP HEAD request with manual redirect chain (max 3 hops)
  4. HTTP GET fallback (only on 405/501)
  5. Result mapping to LiveStatus enum

Safety guarantees:
  - Only http:// and https:// schemes are allowed.
  - Private/loopback/reserved/cloud-metadata IP ranges are blocked.
  - Blocked hostname suffixes (.local, .internal, .localhost, .localdomain) rejected.
  - All DNS-resolved IPs are validated against the SSRF blocklist.
  - Every redirect Location header is re-validated before following.
  - Maximum 3 redirects; beyond that => UNKNOWN.
  - HEAD only; GET fallback only on 405/501; body immediately closed.
  - TLS certificate verification always enabled.

Data privacy guarantees:
  - No submitted URL, hostname, resolved IP, redirect chain, or per-item status
    is written to usage-history JSONL or any runtime file.
  - Only aggregate counts (live_check_count, live_check_skipped_count,
    live_check_error_count) are stored — no raw request/response data.

Eligibility (enforced by job_processor, not here):
  - Only items with vt_hits > 0 or vt_suspicious > 0 receive live checks.
  - Held domains (HOLD_SKIPPED) are always excluded.
  - Clean items (zero VT hits and zero suspicious) are skipped by default.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from models import InputType, LiveStatus, MdiError
from services.error_taxonomy import make_mdi_error

# ── Constants ──────────────────────────────────────────────────────────────────


def _live_error(code: str, message: str, *, retriable: bool = True) -> MdiError:
    return make_mdi_error(
        code=code,
        message=message,
        source="live_check",
        retriable=retriable,
    )

MAX_REDIRECTS: int = 3
TIMEOUT_S: float = 10.0
USER_AGENT: str = "MDI-LiveCheck/1.0"

# ── SSRF blocked IPv4 networks ─────────────────────────────────────────────────
# Ported from URL Activity Scanner ipSafety.ts (AIPF-002/003)

_BLOCKED_IPV4_NETWORKS = [
    ipaddress.ip_network(cidr, strict=False)
    for cidr in [
        "0.0.0.0/8",          # This network (RFC 1122)
        "10.0.0.0/8",         # Private Class A (RFC 1918)
        "100.64.0.0/10",      # Carrier-grade NAT (RFC 6598)
        "127.0.0.0/8",        # Loopback
        "169.254.0.0/16",     # Link-local / cloud metadata (RFC 3927 + AWS/GCP)
        "172.16.0.0/12",      # Private Class B (RFC 1918)
        "192.0.0.0/24",       # IETF Protocol Assignments (RFC 6890)
        "192.0.2.0/24",       # TEST-NET-1 (RFC 5737)
        "192.168.0.0/16",     # Private Class C (RFC 1918)
        "198.18.0.0/15",      # Benchmarking (RFC 2544)
        "198.51.100.0/24",    # TEST-NET-2 (RFC 5737)
        "203.0.113.0/24",     # TEST-NET-3 (RFC 5737)
        "224.0.0.0/4",        # Multicast (RFC 3171)
        "240.0.0.0/4",        # Reserved (RFC 1112)
        "255.255.255.255/32", # Broadcast
    ]
]

# ── SSRF blocked IPv6 networks ─────────────────────────────────────────────────

_BLOCKED_IPV6_NETWORKS = [
    ipaddress.ip_network(cidr, strict=False)
    for cidr in [
        "::/128",                   # Unspecified address
        "::1/128",                  # Loopback
        "::ffff:0:0/96",            # IPv4-mapped (covers all ::ffff:x.x.x.x)
        "64:ff9b::/96",             # IPv4-IPv6 translation (RFC 6052)
        "100::/64",                 # Discard prefix (RFC 6666)
        "2001::/23",                # IETF protocol (RFC 2928)
        "2001:db8::/32",            # Documentation (RFC 3849)
        "2002::/16",                # 6to4 (RFC 3056)
        "fc00::/7",                 # Unique local (fc00:: and fd00::) (RFC 4193)
        "fe80::/10",                # Link-local unicast (RFC 4291)
        "ff00::/8",                 # Multicast (RFC 4291)
    ]
]

# ── Blocked hostname exact matches ─────────────────────────────────────────────

_BLOCKED_HOSTNAMES_EXACT: frozenset = frozenset([
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
])

# ── Blocked hostname suffixes ──────────────────────────────────────────────────

_BLOCKED_HOSTNAME_SUFFIXES: tuple = (
    ".localhost",
    ".localdomain",
    ".local",
    ".internal",
)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class LiveCheckResult:
    """Result of a live HTTP check for one item."""
    live_status: LiveStatus
    http_status_code: Optional[int] = None
    redirect_count: int = 0
    error: Optional[MdiError] = None


@dataclass
class _UrlValidation:
    """Internal result of URL safety validation. Not part of the public API."""
    allowed: bool
    hostname: Optional[str] = None
    normalized_url: Optional[str] = None
    reason: str = ""


# ── Pure safety functions ──────────────────────────────────────────────────────


def _check_ip_safety(ip: str) -> Optional[str]:
    """
    Check if an IP address string falls in a blocked range.

    Returns a human-readable block reason, or None if the IP is safe.
    Pure function — no network calls.
    """
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return f"Invalid IP address: {ip!r}"

    if isinstance(ip_obj, ipaddress.IPv4Address):
        for network in _BLOCKED_IPV4_NETWORKS:
            if ip_obj in network:
                return f"Blocked IPv4 range: {network}"
        return None

    # IPv6
    for network in _BLOCKED_IPV6_NETWORKS:
        if ip_obj in network:
            return f"Blocked IPv6 range: {network}"
    return None


def _validate_url(url: str) -> _UrlValidation:
    """
    Validate a URL for SSRF safety before any network call.

    Checks (in order):
      1. Non-empty and parseable.
      2. Scheme restricted to http / https.
      3. Hostname present.
      4. Hostname blocklist (exact + suffixes).
      5. IP-literal: if hostname is an IP, it must not be in a blocked range.

    Returns _UrlValidation(allowed=False) for any blocked or invalid input.
    Pure function — no network calls.
    """
    if not url or not url.strip():
        return _UrlValidation(allowed=False, reason="Empty URL")

    try:
        parsed = urlparse(url)
    except Exception as exc:  # noqa: BLE001
        return _UrlValidation(allowed=False, reason=f"Unparseable URL: {exc}")

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return _UrlValidation(
            allowed=False,
            reason=f"Unsupported scheme: {scheme!r} (only http/https allowed)",
        )

    hostname = parsed.hostname
    if not hostname:
        return _UrlValidation(allowed=False, reason="Missing or empty hostname")
    hostname = hostname.lower().rstrip(".")

    # IP literal — check directly, skip hostname blocklist
    try:
        ip_obj = ipaddress.ip_address(hostname)
        block_reason = _check_ip_safety(str(ip_obj))
        if block_reason:
            return _UrlValidation(
                allowed=False, hostname=hostname, normalized_url=url,
                reason=f"IP literal in blocked range: {block_reason}",
            )
        return _UrlValidation(
            allowed=True, hostname=hostname, normalized_url=url,
            reason="Valid IP literal",
        )
    except ValueError:
        pass  # Not an IP literal — continue to hostname checks

    # Hostname exact blocklist
    if hostname in _BLOCKED_HOSTNAMES_EXACT:
        return _UrlValidation(
            allowed=False, hostname=hostname, normalized_url=url,
            reason=f"Blocked hostname: {hostname!r}",
        )

    # Hostname suffix blocklist
    for suffix in _BLOCKED_HOSTNAME_SUFFIXES:
        if hostname.endswith(suffix):
            return _UrlValidation(
                allowed=False, hostname=hostname, normalized_url=url,
                reason=f"Blocked hostname suffix: {suffix!r} in {hostname!r}",
            )

    return _UrlValidation(
        allowed=True, hostname=hostname, normalized_url=url,
        reason="Valid",
    )


# ── Mockable network entry points ──────────────────────────────────────────────


async def _resolve_dns(hostname: str) -> List[str]:
    """
    Resolve a hostname to a list of IP address strings (IPv4 + IPv6).

    Uses socket.getaddrinfo via a thread-pool executor to avoid blocking the
    event loop.  Returns an empty list on DNS failure (NXDOMAIN, SERVFAIL, etc.).

    Mockable entry point — all tests patch this function to avoid live DNS.
    """
    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(
            None,
            lambda: socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM),
        )
        ips: List[str] = []
        for r in results:
            addr = r[4][0]
            if addr not in ips:
                ips.append(addr)
        return ips
    except (socket.gaierror, OSError):
        return []


async def _head_request(url: str, client: httpx.AsyncClient) -> httpx.Response:
    """
    Issue a single HTTP HEAD request. Never follows redirects. Body is not read.

    Mockable entry point — all tests patch this function to avoid live HTTP.
    """
    resp = await client.head(url, follow_redirects=False)
    await resp.aclose()
    return resp


async def _get_fallback_request(url: str, client: httpx.AsyncClient) -> httpx.Response:
    """
    Issue a single HTTP GET request as a fallback for 405/501 HEAD responses.
    Never follows redirects. Body is immediately closed without reading.

    Mockable entry point — all tests patch this function to avoid live HTTP.
    """
    resp = await client.get(url, follow_redirects=False)
    await resp.aclose()
    return resp


# ── Internal helpers ───────────────────────────────────────────────────────────


def _is_tls_error(exc: Exception) -> bool:
    """Return True if the exception represents a TLS/SSL failure."""
    cause = exc.__context__
    if isinstance(cause, ssl.SSLError):
        return True
    msg = str(exc).lower()
    return "ssl" in msg or "tls" in msg or "certificate" in msg


def _map_status_to_result(status_code: int, redirect_count: int) -> LiveCheckResult:
    """
    Map a final HTTP status code + redirect context to a LiveCheckResult.

    If any redirect was followed (redirect_count > 0), the result is always
    REDIRECT, regardless of the final status code.  This matches the URL
    Activity Scanner behaviour: a redirected URL is "live" from MDI's perspective.
    """
    if redirect_count > 0:
        return LiveCheckResult(
            live_status=LiveStatus.REDIRECT,
            http_status_code=status_code,
            redirect_count=redirect_count,
        )

    if 200 <= status_code < 300:
        live_status = LiveStatus.ACTIVE
    elif status_code == 403:
        live_status = LiveStatus.FORBIDDEN
    elif status_code == 404:
        live_status = LiveStatus.NOT_FOUND
    elif status_code == 410:
        live_status = LiveStatus.GONE
    elif 500 <= status_code < 600:
        live_status = LiveStatus.SERVER_ERROR
    else:
        live_status = LiveStatus.UNKNOWN

    return LiveCheckResult(
        live_status=live_status,
        http_status_code=status_code,
        redirect_count=redirect_count,
    )


async def _run_head_chain(
    start_url: str,
    client: httpx.AsyncClient,
) -> LiveCheckResult:
    """
    Execute the HEAD request chain with SSRF re-validation on every redirect hop.

    On each 3xx response:
      - Resolve the Location header to an absolute URL.
      - Re-run _validate_url on the redirect destination.
      - Re-run _resolve_dns + _check_ip_safety on the redirect hostname.
      - Abort with BLOCKED if any check fails.

    Stops after MAX_REDIRECTS hops (returns UNKNOWN) or a non-3xx response.
    On 405/501, falls back to GET with body immediately discarded.
    """
    current_url = start_url
    redirect_count = 0

    while True:
        # HEAD request
        try:
            resp = await _head_request(current_url, client)
        except httpx.TimeoutException:
            return LiveCheckResult(
                live_status=LiveStatus.TIMEOUT,
                redirect_count=redirect_count,
            )
        except httpx.ConnectError as exc:
            if _is_tls_error(exc):
                return LiveCheckResult(
                    live_status=LiveStatus.UNKNOWN,
                    redirect_count=redirect_count,
                    error=_live_error(
                        "live_check_tls_error",
                        "TLS/SSL verification failed",
                        retriable=False,
                    ),
                )
            return LiveCheckResult(
                live_status=LiveStatus.CONNECTION_REFUSED,
                redirect_count=redirect_count,
            )
        except httpx.RequestError:
            return LiveCheckResult(
                live_status=LiveStatus.UNKNOWN,
                redirect_count=redirect_count,
            )

        status = resp.status_code

        # Handle redirect
        if status in (301, 302, 303, 307, 308):
            if redirect_count >= MAX_REDIRECTS:
                return LiveCheckResult(
                    live_status=LiveStatus.UNKNOWN,
                    http_status_code=status,
                    redirect_count=redirect_count,
                )

            location = resp.headers.get("location")
            if not location:
                return LiveCheckResult(
                    live_status=LiveStatus.UNKNOWN,
                    http_status_code=status,
                    redirect_count=redirect_count,
                )

            # Resolve relative redirect target
            try:
                next_url = urljoin(current_url, location)
            except Exception:  # noqa: BLE001
                return LiveCheckResult(
                    live_status=LiveStatus.UNKNOWN,
                    http_status_code=status,
                    redirect_count=redirect_count,
                )

            # SSRF re-validation: scheme + hostname blocklist + IP literal check
            next_validation = _validate_url(next_url)
            if not next_validation.allowed:
                return LiveCheckResult(
                    live_status=LiveStatus.BLOCKED,
                    http_status_code=status,
                    redirect_count=redirect_count,
                    error=_live_error(
                        "live_check_redirect_blocked",
                        f"Redirect target blocked: {next_validation.reason}",
                        retriable=False,
                    ),
                )

            # DNS re-check on redirect destination (DNS rebinding mitigation)
            next_hostname = next_validation.hostname
            if next_hostname:
                next_ips = await _resolve_dns(next_hostname)
                if not next_ips:
                    return LiveCheckResult(
                        live_status=LiveStatus.DNS_FAILURE,
                        http_status_code=status,
                        redirect_count=redirect_count,
                    )
                for ip in next_ips:
                    block_reason = _check_ip_safety(ip)
                    if block_reason:
                        return LiveCheckResult(
                            live_status=LiveStatus.BLOCKED,
                            http_status_code=status,
                            redirect_count=redirect_count,
                            error=_live_error(
                                "live_check_redirect_blocked",
                                f"Redirect DNS resolved to blocked IP: {block_reason}",
                                retriable=False,
                            ),
                        )

            redirect_count += 1
            current_url = next_url
            continue

        # 405/501 — HEAD not allowed; try GET fallback (body immediately discarded)
        if status in (405, 501):
            try:
                fallback = await _get_fallback_request(current_url, client)
            except httpx.TimeoutException:
                return LiveCheckResult(
                    live_status=LiveStatus.TIMEOUT,
                    redirect_count=redirect_count,
                )
            except httpx.ConnectError:
                return LiveCheckResult(
                    live_status=LiveStatus.CONNECTION_REFUSED,
                    redirect_count=redirect_count,
                )
            except httpx.RequestError:
                return LiveCheckResult(
                    live_status=LiveStatus.UNKNOWN,
                    redirect_count=redirect_count,
                )
            return _map_status_to_result(fallback.status_code, redirect_count)

        # Non-redirect, non-fallback status — map directly
        return _map_status_to_result(status, redirect_count)


# ── Public entry point ─────────────────────────────────────────────────────────


async def live_check_item(
    input_normalized: str,
    input_type: InputType,
) -> LiveCheckResult:
    """
    Perform an SSRF-safe live HTTP check for one MDI result item.

    For DOMAIN inputs, prepends https:// to build the check URL.
    For URL inputs, uses input_normalized as-is (already has a scheme).

    Gates (in order):
      1. URL validation (scheme, hostname, IP literal)  — pure, no network
      2. DNS resolution + SSRF IP check                — uses _resolve_dns()
      3. HEAD chain with redirect revalidation          — uses _head_request()
      4. GET fallback on 405/501                        — uses _get_fallback_request()

    Never raises — all failure paths return a structured LiveCheckResult.
    Never reads or stores response bodies.
    """
    # Build the URL to probe
    if input_type == InputType.DOMAIN:
        check_url = f"https://{input_normalized}"
    else:
        check_url = input_normalized

    # Gate 1: URL validation (pure)
    validation = _validate_url(check_url)
    if not validation.allowed:
        return LiveCheckResult(
            live_status=LiveStatus.BLOCKED,
            error=_live_error(
                "live_check_blocked",
                f"URL blocked by SSRF safety check: {validation.reason}",
                retriable=False,
            ),
        )

    hostname = validation.hostname
    if not hostname:
        return LiveCheckResult(live_status=LiveStatus.UNKNOWN)

    # Gate 2: DNS resolution + IP safety
    resolved_ips = await _resolve_dns(hostname)
    if not resolved_ips:
        return LiveCheckResult(
            live_status=LiveStatus.DNS_FAILURE,
            error=_live_error(
                "live_check_dns_failure",
                f"DNS resolution returned no results for {hostname!r}",
            ),
        )

    for ip in resolved_ips:
        block_reason = _check_ip_safety(ip)
        if block_reason:
            return LiveCheckResult(
                live_status=LiveStatus.BLOCKED,
                error=_live_error(
                    "live_check_blocked",
                    f"DNS resolved to blocked IP — {block_reason}",
                    retriable=False,
                ),
            )

    # Gates 3 + 4: HEAD chain (and optional GET fallback)
    try:
        async with httpx.AsyncClient(
            verify=True,
            follow_redirects=False,
            timeout=TIMEOUT_S,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            return await _run_head_chain(check_url, client)
    except Exception as exc:  # noqa: BLE001
        return LiveCheckResult(
            live_status=LiveStatus.UNKNOWN,
            error=_live_error(
                "live_check_error",
                f"Unexpected error during live check: {exc}",
            ),
        )
