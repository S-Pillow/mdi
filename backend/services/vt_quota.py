"""
MDI shared VT quota read layer.

Reads the same runtime files used by the VirusTotal Bulk Check tool so that
both tools see the same daily usage counter.  This module is READ-ONLY in
MDI-03; increment/write logic will be added in a later ticket once VT calls
are implemented, and only via explicit temp-file paths in tests.

File paths are resolved from environment variables so that tests can inject
temp paths without touching production runtime files.

  VT_USAGE_FILE         — daily counter JSON  (default: /var/lib/dns-tool/vt_usage.json)
  VT_USAGE_HISTORY_FILE — per-job JSONL       (default: /var/lib/dns-tool/vt_usage_history.jsonl)
  VT_DAILY_HISTORY_FILE — 90-day history JSON (default: /var/lib/dns-tool/vt_daily_history.json)

Safety contract:
  - Missing file  → return safe defaults, do not raise, do not create the file.
  - Malformed JSON → return error field, do not mutate or delete the file.
  - Never read VT_API_KEY.  Never log file contents.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("mdi.vt_quota")

# ── Constants shared with vt-bulk-check (must not diverge) ────────────────────

DAILY_LOOKUPS_LIMIT: int = 500
RATE_LIMIT_PER_MIN: int = 4


# ── Path resolution ────────────────────────────────────────────────────────────

def _usage_file_path() -> Path:
    return Path(os.environ.get("VT_USAGE_FILE", "/var/lib/dns-tool/vt_usage.json"))


def _usage_history_file_path() -> Path:
    return Path(os.environ.get("VT_USAGE_HISTORY_FILE", "/var/lib/dns-tool/vt_usage_history.jsonl"))


def _daily_history_file_path() -> Path:
    return Path(os.environ.get("VT_DAILY_HISTORY_FILE", "/var/lib/dns-tool/vt_daily_history.json"))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _utc_date_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _read_json_file(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Safely read and parse a JSON file.

    Returns (data_dict, None) on success.
    Returns (None, error_message) on missing file, empty file, or JSON decode error.
    Never raises.  Never mutates the file.
    """
    if not path.exists():
        return None, f"file_not_found:{path}"
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None, f"file_empty:{path}"
        data = json.loads(text)
        if not isinstance(data, dict):
            return None, f"unexpected_type:{type(data).__name__}:{path}"
        return data, None
    except json.JSONDecodeError as exc:
        return None, f"json_decode_error:{exc.msg}:{path}"
    except OSError as exc:
        return None, f"os_error:{exc.strerror}:{path}"


# ── Public read API ────────────────────────────────────────────────────────────

def read_usage_state(usage_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    Read the current daily VT usage counter.

    Returns a dict with keys:
      date_utc           — date string from the file, or today's date on missing/stale
      daily_lookups_used — integer counter (0 on missing/error)
      _source            — resolved file path (string)
      _error             — error message if file was missing or malformed, else None

    Handles stale-date reset: if the file's date_utc differs from today, returns
    daily_lookups_used=0 with today's date (matching vt-bulk-check behavior).
    Does NOT write a reset to disk.
    """
    path = usage_file or _usage_file_path()
    today = _utc_date_str()
    data, err = _read_json_file(path)

    if err or data is None:
        logger.debug("vt_quota.read_usage_state: %s", err)
        return {
            "date_utc": today,
            "daily_lookups_used": 0,
            "_source": str(path),
            "_error": err,
        }

    stored_date = data.get("date_utc", "")
    if stored_date != today:
        # Date rolled over — new day counter starts at 0 (read-only view)
        return {
            "date_utc": today,
            "daily_lookups_used": 0,
            "_source": str(path),
            "_error": None,
        }

    return {
        "date_utc": stored_date,
        "daily_lookups_used": int(data.get("daily_lookups_used", 0)),
        "_source": str(path),
        "_error": None,
    }


def get_usage_summary(usage_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    Return the full usage summary dict suitable for the /api/mdi/usage response.

    All fields are safe to return in an API response.
    The '_source' and '_error' internal keys are renamed to 'source' and 'error'.
    """
    state = read_usage_state(usage_file)
    used = state["daily_lookups_used"]
    remaining = max(0, DAILY_LOOKUPS_LIMIT - used)
    return {
        "date_utc": state["date_utc"],
        "daily_lookups_used": used,
        "daily_limit": DAILY_LOOKUPS_LIMIT,
        "remaining": remaining,
        "rate_limit_per_min": RATE_LIMIT_PER_MIN,
        "source": state["_source"],
        "shared_with": ["vt-bulk-check", "mdi"],
        "mutated": False,
        "error": state["_error"],
    }


# ── Test-only write helper ─────────────────────────────────────────────────────

def _increment_usage_for_file(path: Path, amount: int = 1) -> Dict[str, Any]:
    """
    Increment the usage counter in the given file by `amount`.

    IMPORTANT: This function accepts an EXPLICIT file path and is intended
    ONLY for tests using tempfile paths.  It must never be called with a
    production runtime path.  The caller is responsible for ensuring the path
    is a safe temp location.

    Returns the new state dict.  Raises on OS errors (intentional — tests
    should not silently swallow write failures).
    """
    today = _utc_date_str()
    data, _ = _read_json_file(path)

    if data is None or data.get("date_utc") != today:
        data = {"date_utc": today, "daily_lookups_used": 0}

    new_count = int(data.get("daily_lookups_used", 0)) + amount
    new_data = {"date_utc": today, "daily_lookups_used": new_count}

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_data), encoding="utf-8")
    os.replace(tmp, path)

    return {"date_utc": today, "daily_lookups_used": new_count, "_source": str(path), "_error": None}
