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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from services.quota_lock import QuotaLockTimeout, quota_lock

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

def _read_usage_state_unlocked(path: Path) -> Dict[str, Any]:
    """Read usage state from disk without acquiring flock (internal)."""
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


def read_usage_state(usage_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    Read the current daily VT usage counter under a shared flock.

    Raises QuotaLockTimeout if the lock cannot be acquired.
    Does NOT write a reset to disk on stale date.
    """
    path = usage_file or _usage_file_path()
    with quota_lock("shared"):
        return _read_usage_state_unlocked(path)


def get_usage_summary(usage_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    Return the full usage summary dict suitable for the /api/mdi/usage response.

    Retries briefly on QuotaLockTimeout before returning error in response.
    """
    path = usage_file or _usage_file_path()
    state = None
    lock_error: Optional[str] = None
    for attempt in range(3):
        try:
            state = read_usage_state(usage_file)
            break
        except QuotaLockTimeout:
            if attempt < 2:
                time.sleep(0.1)
            else:
                lock_error = QuotaLockTimeout.code
    if state is None:
        today = _utc_date_str()
        return {
            "date_utc": today,
            "daily_lookups_used": 0,
            "daily_limit": DAILY_LOOKUPS_LIMIT,
            "remaining": 0,
            "rate_limit_per_min": RATE_LIMIT_PER_MIN,
            "source": str(path),
            "shared_with": ["vt-bulk-check", "mdi"],
            "mutated": False,
            "error": lock_error,
        }
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
        "error": state["_error"] or lock_error,
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

    with quota_lock("exclusive"):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(new_data), encoding="utf-8")
        os.replace(tmp, path)

    return {"date_utc": today, "daily_lookups_used": new_count, "_source": str(path), "_error": None}
