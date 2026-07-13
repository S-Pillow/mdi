"""
MDI offline hold detection.

Parses EPP/domain status strings for clientHold and serverHold without any
external lookup. Works entirely from operator-supplied file data.

No network calls. No DNS resolution. No external APIs.

Supported status formats:
  - Single string:                 "clientHold"
  - Spaced registry variants:      "client hold", "server hold"
  - Comma-separated:               "clientHold, serverHold"
  - Semicolon-separated:           "clientHold; serverHold"
  - Pipe-separated (EPP exports):  "clientTransferProhibited|clientHold|inactive"
  - Whitespace/newline-separated:  "clientHold\\nserverHold"
  - Mixed delimiters
  - Status with URL suffixes:      "clientHold https://icann.org/epp#clientHold"
  - Upper/lower/mixed case

Negative (not holds):
  - clientTransferProhibited, serverTransferProhibited, inactive, pending transfer
  - standalone "hold"
"""

from __future__ import annotations

import re
from typing import List, Optional

from models import DomainHold, DomainHoldType, DomainStatusSource


# Tokens to discard when extracting individual status labels (audit/raw_statuses)
_TOKEN_SPLIT_RE = re.compile(r'[,;|\s\n\r\t]+')

# Strip trailing ICANN URL suffixes from individual tokens (common in RDAP/WHOIS exports)
_ICANN_URL_RE = re.compile(r'https?://\S*', re.IGNORECASE)

_HOLD_CLIENT_CAMEL_RE = re.compile(r'\bclienthold\b', re.IGNORECASE)
_HOLD_SERVER_CAMEL_RE = re.compile(r'\bserverhold\b', re.IGNORECASE)
_HOLD_CLIENT_SPACED_RE = re.compile(r'\bclient\s+hold\b', re.IGNORECASE)
_HOLD_SERVER_SPACED_RE = re.compile(r'\bserver\s+hold\b', re.IGNORECASE)


def _clean_status_text(raw: str) -> str:
    """Remove ICANN URL suffixes and normalize whitespace for hold matching."""
    return _ICANN_URL_RE.sub(' ', raw).strip()


def _hold_flags_from_cleaned(cleaned: str) -> tuple[bool, bool]:
    """
    Return (client_hold, server_hold) flags from a cleaned status string.

    Uses camelCase token matching and spaced phrase matching. Does not treat
    transfer-prohibited or inactive statuses as holds.
    """
    if not cleaned:
        return False, False
    found_client = (
        _HOLD_CLIENT_CAMEL_RE.search(cleaned) is not None
        or _HOLD_CLIENT_SPACED_RE.search(cleaned) is not None
    )
    found_server = (
        _HOLD_SERVER_CAMEL_RE.search(cleaned) is not None
        or _HOLD_SERVER_SPACED_RE.search(cleaned) is not None
    )
    return found_client, found_server


def _split_status_tokens(raw: str) -> List[str]:
    """
    Split a raw EPP status cell into individual token strings.
    Drops empty tokens and strips ICANN URL suffixes.
    """
    cleaned = _clean_status_text(raw)
    return [t.strip() for t in _TOKEN_SPLIT_RE.split(cleaned) if t.strip()]


def _build_domain_hold(
    *,
    found_client: bool,
    found_server: bool,
    source: DomainStatusSource,
    raw_statuses: List[str],
) -> DomainHold:
    hold_types: List[DomainHoldType] = []
    if found_client:
        hold_types.append(DomainHoldType.CLIENT_HOLD)
    if found_server:
        hold_types.append(DomainHoldType.SERVER_HOLD)
    if not hold_types:
        hold_types = [DomainHoldType.NONE]
    return DomainHold(
        has_hold=found_client or found_server,
        hold_types=hold_types,
        source=source,
        raw_statuses=raw_statuses,
    )


def detect_hold_from_epp_statuses(
    statuses: List[str],
    source: DomainStatusSource = DomainStatusSource.RDAP,
) -> DomainHold:
    """
    Inspect a list of EPP status strings (e.g. from RDAP/WHOIS) and return DomainHold.

    Each list element is evaluated independently so spaced variants like
    ``client hold`` are not broken by whitespace tokenization.
    """
    if not statuses:
        return DomainHold(
            has_hold=False,
            hold_types=[DomainHoldType.NONE],
            source=DomainStatusSource.NOT_CHECKED,
            raw_statuses=[],
        )

    found_client = False
    found_server = False
    raw_statuses: List[str] = []
    for item in statuses:
        if item is None or not str(item).strip():
            continue
        clean_item = _clean_status_text(str(item))
        raw_statuses.append(clean_item)
        fc, fs = _hold_flags_from_cleaned(clean_item)
        found_client = found_client or fc
        found_server = found_server or fs

    if not raw_statuses:
        return DomainHold(
            has_hold=False,
            hold_types=[DomainHoldType.NONE],
            source=DomainStatusSource.NOT_CHECKED,
            raw_statuses=[],
        )

    return _build_domain_hold(
        found_client=found_client,
        found_server=found_server,
        source=source,
        raw_statuses=raw_statuses,
    )


def detect_hold(
    raw_status: Optional[str],
    source: DomainStatusSource = DomainStatusSource.UPLOADED_FILE,
) -> DomainHold:
    """
    Inspect a raw EPP/domain status value and return a populated DomainHold.

    Args:
        raw_status: The raw status string from the uploaded file.
                    May be None/empty if the column was absent or blank.
        source:     Which data source this status came from.

    Returns:
        DomainHold where:
          - has_hold = True  → at least one of clientHold / serverHold is present
          - has_hold = False → status present but neither hold type found
          - has_hold = False + source = NOT_CHECKED → status was absent

    Raises: nothing — all error paths return a safe default.
    """
    if not raw_status or not raw_status.strip():
        return DomainHold(
            has_hold=False,
            hold_types=[DomainHoldType.NONE],
            source=DomainStatusSource.NOT_CHECKED,
            raw_statuses=[],
        )

    cleaned = _clean_status_text(raw_status)
    found_client, found_server = _hold_flags_from_cleaned(cleaned)
    tokens = _split_status_tokens(raw_status)

    return _build_domain_hold(
        found_client=found_client,
        found_server=found_server,
        source=source,
        raw_statuses=tokens,
    )


def hold_type_display(hold: DomainHold) -> str:
    """
    Return a short human-readable hold-type string for display.

    Examples:
      has_hold=False, source=NOT_CHECKED → "unknown"
      has_hold=False                     → "none"
      clientHold only                    → "clientHold"
      serverHold only                    → "serverHold"
      both                               → "clientHold + serverHold"
    """
    if hold.source == DomainStatusSource.NOT_CHECKED:
        return "unknown"
    if not hold.has_hold:
        return "none"
    labels = []
    if DomainHoldType.CLIENT_HOLD in hold.hold_types:
        labels.append("clientHold")
    if DomainHoldType.SERVER_HOLD in hold.hold_types:
        labels.append("serverHold")
    return " + ".join(labels)
