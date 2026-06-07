"""
MDI input parser.

Converts raw pasted text into validated, normalized MdiInputItem objects.
Ported and extended from VirusTotal Bulk Check _normalize_item() logic.

Key MDI differences from vt-bulk-check:
  - Bare domains keep InputType.DOMAIN (not wrapped in http:// for the API key)
  - Scheme + hostname are lowercased; path/query/fragment are preserved as-is
  - Deduplication is enforced here, not at job-run time
  - Quote and bracket stripping is applied before normalization
  - Unsupported schemes (file://, ftp://, etc.) are rejected with a structured error

No network calls are made by this module.
No DNS resolution is performed.
No external APIs are contacted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from models import InputType, MdiError, MdiInputItem


# ── Constants ──────────────────────────────────────────────────────────────────

SUPPORTED_SCHEMES: frozenset = frozenset({"http", "https"})

DEFAULT_MAX_ITEMS: int = 500
DEFAULT_MAX_RAW_CHARS: int = 100_000
MAX_TOKEN_LENGTH: int = 2_048

# Matches valid domain labels: letters, digits, hyphens (not at start/end).
# Also accepts bare IPv4 addresses and single-label hostnames (e.g. localhost).
_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?$"
)
_IPV4_RE = re.compile(
    r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$"
)


# ── Output structures ──────────────────────────────────────────────────────────

@dataclass
class RejectedItem:
    """An input token that could not be normalized."""
    input_original: str
    position: int
    error: MdiError


@dataclass
class DuplicateItem:
    """An input token whose normalized value was already accepted."""
    input_original: str
    position: int
    duplicate_of: str    # the normalized value it duplicates


@dataclass
class ParseResult:
    """Full output of parse_raw_input()."""
    accepted: List[MdiInputItem] = field(default_factory=list)
    rejected: List[RejectedItem] = field(default_factory=list)
    duplicates: List[DuplicateItem] = field(default_factory=list)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _split_tokens(raw: str) -> List[str]:
    """
    Split raw input by any combination of newlines, commas, and whitespace.
    Returns non-empty tokens only.
    """
    return [t for t in re.split(r"[\n\r\t,\s]+", raw) if t]


def _strip_surrounding(s: str) -> str:
    """
    Strip matching surrounding quote or bracket pairs, then whitespace.
    Only one layer is stripped per call.
    """
    s = s.strip()
    for open_ch, close_ch in [
        ('"', '"'), ("'", "'"), ("`", "`"),
        ("<", ">"), ("[", "]"), ("(", ")"),
    ]:
        if len(s) >= 2 and s[0] == open_ch and s[-1] == close_ch:
            s = s[1:-1].strip()
            break
    return s


def _lowercase_url(parsed) -> str:
    """Lowercase scheme and hostname; preserve path/query/fragment exactly."""
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))


def _is_valid_domain(s: str) -> bool:
    """
    Return True if s looks like a valid domain, single-label host, or IPv4.
    Does not perform DNS resolution or network calls.
    """
    if not s or " " in s or len(s) > 253:
        return False
    if _IPV4_RE.match(s):
        parts = [int(p) for p in s.split(".")]
        return all(0 <= p <= 255 for p in parts)
    return bool(_DOMAIN_RE.match(s))


def _make_error(code: str, message: str, source: str = "input_parser") -> MdiError:
    from services.error_taxonomy import make_mdi_error

    return make_mdi_error(code=code, message=message, source=source, retriable=False)


# ── Core normalization ─────────────────────────────────────────────────────────

def normalize_token(
    raw: str,
    default_scheme: str = "http",
) -> Tuple[str, InputType]:
    """
    Normalize a single input token into (normalized_string, InputType).

    Raises ValueError with a short description on invalid input.
    Never makes network calls.

    Rules (in order):
      1. Strip surrounding whitespace, quotes, and bracket pairs.
      2. Remove a single trailing FQDN dot from the domain/host part.
      3. If token contains '://' → full URL; validate and normalize scheme+host.
      4. If token contains '/' but no '://' → domain/path; prefix with default_scheme.
      5. Otherwise → bare domain; lowercase and validate.
    """
    s = _strip_surrounding(raw)

    if not s:
        raise ValueError("empty_token")

    if len(s) > MAX_TOKEN_LENGTH:
        raise ValueError("token_too_long")

    if " " in s:
        raise ValueError("token_contains_space")

    # ── Full URL with scheme ──────────────────────────────────────────────────
    if "://" in s:
        parsed = urlparse(s)
        scheme = parsed.scheme.lower()

        if not scheme:
            raise ValueError("missing_scheme")
        if scheme not in SUPPORTED_SCHEMES:
            raise ValueError(f"unsupported_scheme:{scheme}")

        host = parsed.hostname or ""
        # Remove trailing FQDN dot from host
        if host.endswith("."):
            host = host.rstrip(".")
            # Rebuild netloc preserving port if present
            port_part = f":{parsed.port}" if parsed.port else ""
            userinfo = f"{parsed.username}@" if parsed.username else ""
            netloc = f"{userinfo}{host}{port_part}"
            parsed = parsed._replace(netloc=netloc)

        if not host:
            raise ValueError("missing_host")

        normalized = _lowercase_url(parsed)
        return normalized, InputType.URL

    # ── Domain/path without scheme ────────────────────────────────────────────
    if "/" in s:
        # Prefix with default scheme, then re-parse to lowercase host
        prefixed = f"{default_scheme}://{s}"
        parsed = urlparse(prefixed)
        host = parsed.hostname or ""
        if host.endswith("."):
            host = host.rstrip(".")
        if not host:
            raise ValueError("missing_host")
        normalized = _lowercase_url(parsed)
        return normalized, InputType.URL

    # ── Bare domain ───────────────────────────────────────────────────────────
    domain = s.rstrip(".")   # strip trailing FQDN dot
    domain = domain.lower()

    if not _is_valid_domain(domain):
        raise ValueError(f"invalid_domain:{domain}")

    return domain, InputType.DOMAIN


# ── Public parse API ───────────────────────────────────────────────────────────

def parse_raw_input(
    raw: str,
    *,
    default_scheme: str = "http",
    max_items: int = DEFAULT_MAX_ITEMS,
    max_raw_chars: int = DEFAULT_MAX_RAW_CHARS,
) -> ParseResult:
    """
    Parse raw pasted input into accepted, rejected, and duplicate items.

    No network calls.  No DNS resolution.  No external API access.

    Args:
        raw:            Raw multi-line/comma-separated input string.
        default_scheme: Scheme to prepend to domain/path tokens (default: 'http').
        max_items:      Maximum accepted items; excess tokens become rejected.
        max_raw_chars:  Maximum raw input length; returns a single rejection if exceeded.

    Returns:
        ParseResult with accepted, rejected, and duplicates lists.
        accepted items are ordered by first-seen position.
        Duplicate items preserve the original string and position of the repeat.
    """
    result = ParseResult()

    if not raw or not raw.strip():
        return result

    if len(raw) > max_raw_chars:
        result.rejected.append(RejectedItem(
            input_original=raw[:120] + "…",
            position=1,
            error=_make_error(
                "input_too_large",
                f"Raw input exceeds {max_raw_chars:,} character limit.",
            ),
        ))
        return result

    tokens = _split_tokens(raw)
    seen_normalized: dict[str, int] = {}   # normalized → accepted position (1-based)
    position = 0   # raw token counter

    for raw_token in tokens:
        position += 1

        # Enforce max_items on accepted list
        if len(result.accepted) >= max_items:
            result.rejected.append(RejectedItem(
                input_original=raw_token,
                position=position,
                error=_make_error(
                    "max_items_exceeded",
                    f"Batch limit of {max_items} items reached. "
                    "This item was not accepted.",
                ),
            ))
            continue

        try:
            normalized, input_type = normalize_token(raw_token, default_scheme)
        except ValueError as exc:
            code_str = str(exc)
            # Map internal codes to user-facing messages
            if code_str == "empty_token":
                continue   # silently skip pure whitespace/empty tokens
            elif code_str == "token_too_long":
                msg = f"Token exceeds {MAX_TOKEN_LENGTH} character limit."
                code = "token_too_long"
            elif code_str == "token_contains_space":
                msg = "Token contains a space character and cannot be parsed as a domain or URL."
                code = "invalid_input"
            elif code_str.startswith("unsupported_scheme:"):
                scheme = code_str.split(":", 1)[1]
                msg = (
                    f"Unsupported scheme '{scheme}'. "
                    "Only http:// and https:// are accepted."
                )
                code = "unsupported_scheme"
            elif code_str.startswith("invalid_domain:"):
                msg = f"'{raw_token}' does not appear to be a valid domain or URL."
                code = "invalid_input"
            elif code_str == "missing_host":
                msg = f"Could not extract a hostname from '{raw_token}'."
                code = "invalid_input"
            else:
                msg = f"Could not parse '{raw_token}': {code_str}."
                code = "invalid_input"

            result.rejected.append(RejectedItem(
                input_original=raw_token,
                position=position,
                error=_make_error(code, msg),
            ))
            continue

        # Deduplication check
        if normalized in seen_normalized:
            result.duplicates.append(DuplicateItem(
                input_original=raw_token,
                position=position,
                duplicate_of=normalized,
            ))
            continue

        # Accept
        seen_normalized[normalized] = len(result.accepted) + 1
        result.accepted.append(MdiInputItem(
            input_original=raw_token,
            input_normalized=normalized,
            input_type=input_type,
            position=seen_normalized[normalized],
        ))

    return result
