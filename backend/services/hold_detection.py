"""
MDI offline hold detection.

Parses EPP/domain status strings for clientHold and serverHold without any
external lookup. Works entirely from operator-supplied file data.

No network calls. No DNS resolution. No external APIs.

Supported status formats:
  - Single string:                 "clientHold"
  - Comma-separated:               "clientHold, serverHold"
  - Semicolon-separated:           "clientHold; serverHold"
  - Pipe-separated (EPP exports):  "clientTransferProhibited|clientHold|inactive"
  - Whitespace/newline-separated:  "clientHold\\nserverHold"
  - Mixed delimiters
  - Status with URL suffixes:      "clientHold https://icann.org/epp#clientHold"
  - Upper/lower/mixed case
"""

from __future__ import annotations

import re
from typing import List, Optional

from models import DomainHold, DomainHoldType, DomainStatusSource


# Tokens to discard when extracting individual status labels
_TOKEN_SPLIT_RE = re.compile(r'[,;|\s\n\r\t]+')

# Strip trailing ICANN URL suffixes from individual tokens (common in RDAP/WHOIS exports)
_ICANN_URL_RE = re.compile(r'https?://\S*', re.IGNORECASE)


def _split_status_tokens(raw: str) -> List[str]:
    """
    Split a raw EPP status cell into individual token strings.
    Drops empty tokens and strips ICANN URL suffixes.
    """
    # Remove inline URLs first
    cleaned = _ICANN_URL_RE.sub(' ', raw)
    return [t.strip() for t in _TOKEN_SPLIT_RE.split(cleaned) if t.strip()]


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

    tokens = _split_status_tokens(raw_status)
    raw_statuses = tokens[:]

    found_client = any(t.lower() == "clienthold" for t in tokens)
    found_server = any(t.lower() == "serverhold" for t in tokens)

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
