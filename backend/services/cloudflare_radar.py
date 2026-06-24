"""
Cloudflare Radar domain rank lookup (MDI-50B).

Popularity / blast-radius context only — does not affect VT triage or quota.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("mdi.cloudflare_radar")

SOURCE_POPULAR = "cloudflare_radar_popular"
API_URL_TEMPLATE = (
    "https://api.cloudflare.com/client/v4/radar/ranking/domain/{domain}"
    "?rankingType=POPULAR&format=JSON"
)
REQUEST_TIMEOUT_SECONDS = 8.0
CACHE_TTL = timedelta(days=7)
MAX_LOOKUPS_PER_JOB = 100
_INEQUALITY_BUCKET_RE = re.compile(r"^>\s*(\d+)\s*$")


class CloudflareRankBucket:
    TOP_100 = "TOP_100"
    TOP_1K = "TOP_1K"
    TOP_5K = "TOP_5K"
    TOP_10K = "TOP_10K"
    TOP_100K = "TOP_100K"
    TOP_1M = "TOP_1M"
    UNRANKED = "UNRANKED"
    UNKNOWN = "UNKNOWN"


@dataclass
class CloudflareRankResult:
    available: bool = False
    rank: Optional[int] = None
    bucket: Optional[str] = None
    raw_bucket: Optional[str] = None
    source: Optional[str] = None
    checked_at: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class CloudflareJobState:
    lookups_done: int = 0
    stop: bool = False
    stop_reason: Optional[str] = None


@dataclass
class _CacheEntry:
    result: CloudflareRankResult
    expires_at: datetime


_cache: Dict[str, _CacheEntry] = {}


def clear_cache() -> None:
    """Test helper — reset in-memory cache."""
    _cache.clear()


def get_api_token() -> Optional[str]:
    token = os.environ.get("CLOUDFLARE_RADAR_API_TOKEN", "").strip()
    return token or None


def normalize_bucket(
    rank: Optional[int],
    raw_bucket: Optional[str],
) -> Tuple[str, Optional[int]]:
    """
    Return (normalized_bucket, rank_to_store).

    Rank 1–100 → TOP_100. Numeric buckets map to coarse tiers.
    Inequality buckets like >200000 → UNRANKED.
    """
    if rank is not None:
        try:
            r = int(rank)
            if 1 <= r <= 100:
                return CloudflareRankBucket.TOP_100, r
        except (TypeError, ValueError):
            pass

    if raw_bucket is not None:
        raw = str(raw_bucket).strip()
        if _INEQUALITY_BUCKET_RE.match(raw):
            return CloudflareRankBucket.UNRANKED, None
        try:
            n = int(raw)
            if n <= 1000:
                return CloudflareRankBucket.TOP_1K, None
            if n <= 5000:
                return CloudflareRankBucket.TOP_5K, None
            if n <= 10000:
                return CloudflareRankBucket.TOP_10K, None
            if n <= 100000:
                return CloudflareRankBucket.TOP_100K, None
            if n <= 1000000:
                return CloudflareRankBucket.TOP_1M, None
        except ValueError:
            return CloudflareRankBucket.UNKNOWN, None

    if rank is not None:
        return CloudflareRankBucket.UNKNOWN, int(rank) if str(rank).isdigit() else None

    return CloudflareRankBucket.UNRANKED, None


def _error_codes(body: Dict[str, Any]) -> list:
    codes = []
    for err in body.get("errors") or []:
        if isinstance(err, dict) and err.get("code") is not None:
            codes.append(err.get("code"))
    return codes


def parse_api_response(
    http_status: int,
    body: Optional[Dict[str, Any]],
    *,
    checked_at: Optional[datetime] = None,
) -> CloudflareRankResult:
    """Map HTTP + Cloudflare JSON body to CloudflareRankResult."""
    now = checked_at or datetime.now(timezone.utc)
    if body is None:
        body = {}

    if http_status in (401, 403):
        return CloudflareRankResult(
            available=False,
            bucket=CloudflareRankBucket.UNKNOWN,
            source=SOURCE_POPULAR,
            checked_at=now,
            error="auth_failed",
        )

    if http_status == 429:
        return CloudflareRankResult(
            available=False,
            bucket=CloudflareRankBucket.UNKNOWN,
            source=SOURCE_POPULAR,
            checked_at=now,
            error="rate_limited",
        )

    if http_status >= 500:
        return CloudflareRankResult(
            available=False,
            bucket=CloudflareRankBucket.UNKNOWN,
            source=SOURCE_POPULAR,
            checked_at=now,
            error="api_unavailable",
        )

    codes = _error_codes(body)
    if http_status == 404 or 7003 in codes:
        return CloudflareRankResult(
            available=False,
            bucket=CloudflareRankBucket.UNRANKED,
            source=SOURCE_POPULAR,
            checked_at=now,
            error=None,
        )

    if not body.get("success", False):
        if 7003 in codes:
            return CloudflareRankResult(
                available=False,
                bucket=CloudflareRankBucket.UNRANKED,
                source=SOURCE_POPULAR,
                checked_at=now,
                error=None,
            )
        return CloudflareRankResult(
            available=False,
            bucket=CloudflareRankBucket.UNKNOWN,
            source=SOURCE_POPULAR,
            checked_at=now,
            error="api_error",
        )

    result = body.get("result") or {}
    if not isinstance(result, dict):
        return CloudflareRankResult(
            available=False,
            bucket=CloudflareRankBucket.UNKNOWN,
            source=SOURCE_POPULAR,
            checked_at=now,
            error="invalid_response",
        )

    details = result.get("details_0")
    if not isinstance(details, dict):
        return CloudflareRankResult(
            available=False,
            bucket=CloudflareRankBucket.UNRANKED,
            source=SOURCE_POPULAR,
            checked_at=now,
            error=None,
        )

    rank_val = details.get("rank")
    rank_int: Optional[int] = None
    if rank_val is not None:
        try:
            rank_int = int(rank_val)
        except (TypeError, ValueError):
            rank_int = None

    raw_bucket = details.get("bucket")
    raw_str = str(raw_bucket).strip() if raw_bucket is not None else None
    norm_bucket, stored_rank = normalize_bucket(rank_int, raw_str)

    if norm_bucket == CloudflareRankBucket.UNRANKED:
        return CloudflareRankResult(
            available=False,
            rank=stored_rank,
            bucket=norm_bucket,
            raw_bucket=raw_str,
            source=SOURCE_POPULAR,
            checked_at=now,
            error=None,
        )

    if norm_bucket == CloudflareRankBucket.UNKNOWN:
        return CloudflareRankResult(
            available=False,
            rank=stored_rank,
            bucket=norm_bucket,
            raw_bucket=raw_str,
            source=SOURCE_POPULAR,
            checked_at=now,
            error="invalid_response",
        )

    return CloudflareRankResult(
        available=True,
        rank=stored_rank,
        bucket=norm_bucket,
        raw_bucket=raw_str,
        source=SOURCE_POPULAR,
        checked_at=now,
        error=None,
    )


def result_to_item_update(cf: CloudflareRankResult) -> Dict[str, Any]:
    return {
        "cloudflare_rank_available": cf.available,
        "cloudflare_rank": cf.rank,
        "cloudflare_rank_bucket": cf.bucket,
        "cloudflare_rank_raw_bucket": cf.raw_bucket,
        "cloudflare_rank_source": cf.source,
        "cloudflare_rank_checked_at": cf.checked_at,
        "cloudflare_rank_error": cf.error,
    }


def _cache_get(domain: str) -> Optional[CloudflareRankResult]:
    entry = _cache.get(domain)
    if entry is None:
        return None
    if entry.expires_at <= datetime.now(timezone.utc):
        del _cache[domain]
        return None
    return entry.result


def _cache_set(domain: str, result: CloudflareRankResult) -> None:
    _cache[domain] = _CacheEntry(
        result=result,
        expires_at=datetime.now(timezone.utc) + CACHE_TTL,
    )


async def _default_request(domain: str, token: str) -> Tuple[int, Dict[str, Any]]:
    url = API_URL_TEMPLATE.format(domain=domain)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(url, headers=headers)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return response.status_code, body


async def lookup_domain_rank(
    domain: str,
    *,
    enabled: bool = True,
    token: Optional[str] = None,
    job_state: Optional[CloudflareJobState] = None,
    request_func: Optional[Callable[[str, str], Any]] = None,
) -> CloudflareRankResult:
    """
    Lookup Cloudflare Radar rank for a registrable domain.

  Never raises — failures map to UNKNOWN/UNRANKED results.
    """
    if not enabled:
        return CloudflareRankResult()

    effective_token = token if token is not None else get_api_token()
    if not effective_token:
        return CloudflareRankResult(error="not_configured")

    state = job_state or CloudflareJobState()
    if state.stop:
        return CloudflareRankResult(
            bucket=CloudflareRankBucket.UNKNOWN,
            source=SOURCE_POPULAR,
            checked_at=datetime.now(timezone.utc),
            error=state.stop_reason or "skipped",
        )

    if state.lookups_done >= MAX_LOOKUPS_PER_JOB:
        return CloudflareRankResult(
            bucket=CloudflareRankBucket.UNKNOWN,
            source=SOURCE_POPULAR,
            checked_at=datetime.now(timezone.utc),
            error="lookup_cap_exceeded",
        )

    cached = _cache_get(domain)
    if cached is not None:
        return cached

    do_request = request_func or _default_request
    http_status = 0
    body: Dict[str, Any] = {}
    retried = False

    while True:
        try:
            http_status, body = await do_request(domain, effective_token)
        except httpx.TimeoutException:
            if not retried:
                retried = True
                continue
            result = CloudflareRankResult(
                bucket=CloudflareRankBucket.UNKNOWN,
                source=SOURCE_POPULAR,
                checked_at=datetime.now(timezone.utc),
                error="timeout",
            )
            state.lookups_done += 1
            return result
        except Exception as exc:
            logger.warning("Cloudflare Radar lookup failed for domain (redacted): %s", type(exc).__name__)
            result = CloudflareRankResult(
                bucket=CloudflareRankBucket.UNKNOWN,
                source=SOURCE_POPULAR,
                checked_at=datetime.now(timezone.utc),
                error="api_unavailable",
            )
            state.lookups_done += 1
            return result

        if http_status >= 500 and not retried:
            retried = True
            continue
        break

    state.lookups_done += 1
    result = parse_api_response(http_status, body)

    if result.error == "auth_failed" or result.error == "rate_limited":
        state.stop = True
        state.stop_reason = result.error

    if result.error is None and result.bucket != CloudflareRankBucket.UNKNOWN:
        _cache_set(domain, result)

    return result
