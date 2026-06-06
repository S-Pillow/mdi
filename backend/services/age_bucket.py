"""
MDI shared age-bucket utility.

Converts a domain registration date into an AgeBucket enum value.
Used by both upload_parser (offline, from CSV/XLSX create-date columns) and
domain_enrichment (live, from RDAP/WHOIS created_at).

Single source of truth — both code paths produce the same bucket for the same date.

No network calls. No external APIs. No disk I/O.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from models import AgeBucket

# ── Date format list (shared for parsing string dates) ────────────────────────

DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
    "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
    "%Y.%m.%d",
]


def parse_date_string(s: str) -> Optional[date]:
    """
    Parse a date string in one of the known formats; return None if none match.

    Attempts each format in DATE_FORMATS; then tries the first 10 chars as YYYY-MM-DD.
    """
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    if len(s) >= 10:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def compute_age_bucket(d: date) -> AgeBucket:
    """
    Map a registration date to an AgeBucket.

    Mapping:
      future date (delta < 0) → UNKNOWN  (data error)
      0–29 days               → VERY_NEW
      30–179 days             → NEW
      180–729 days            → ESTABLISHED
      ≥ 730 days              → MATURE

    Args:
        d: The domain registration date (date only, not datetime).

    Returns:
        AgeBucket enum value. Never raises.
    """
    today = date.today()
    delta = (today - d).days
    if delta < 0:
        return AgeBucket.UNKNOWN
    if delta < 30:
        return AgeBucket.VERY_NEW
    if delta < 180:
        return AgeBucket.NEW
    if delta < 730:
        return AgeBucket.ESTABLISHED
    return AgeBucket.MATURE
