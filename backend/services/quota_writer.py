"""
MDI shared VT quota writer.

Manages atomic read-increment-write of the shared VT usage file
(/var/lib/dns-tool/vt_usage.json) and appends metadata-only records
to the usage-history JSONL.

Design:
  - Uses asyncio.Lock for in-process serialization (per-process).
  - Atomic write: write to .tmp, then os.replace() to avoid partial writes.
  - All write methods accept injected path arguments so tests can use
    tmp_path without touching live /var/lib/dns-tool/ files.
  - NEVER writes to vt_latest_job.json.
  - Accepted MVP risk: two processes (MDI + VT Bulk Check) may race on
    the same file. Atomic replace minimises corruption; the race window
    is documented and carried forward.

Usage history records are metadata-only:
  - No raw domains, URLs, or item-level results.
  - Fields: timestamp, tool_name, job_id, operation, items_attempted,
            items_completed, quota_units_consumed, quota_blocked_count,
            errors_count, held_skipped_count, processing_options_summary,
            status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("mdi.quota_writer")

_QUOTA_LOCK = asyncio.Lock()

# ── Path helpers ───────────────────────────────────────────────────────────────

def _default_usage_file() -> Path:
    return Path(os.environ.get("VT_USAGE_FILE", "/var/lib/dns-tool/vt_usage.json"))

def _default_history_file() -> Path:
    return Path(os.environ.get("VT_USAGE_HISTORY_FILE", "/var/lib/dns-tool/vt_usage_history.jsonl"))

def _default_daily_file() -> Path:
    return Path(os.environ.get("VT_DAILY_HISTORY_FILE", "/var/lib/dns-tool/vt_daily_history.json"))


def _utc_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Read JSON file; return None on missing/corrupt."""
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# ── Quota read (remaining) ─────────────────────────────────────────────────────

DAILY_QUOTA = int(os.environ.get("VT_DAILY_QUOTA", "500"))


def read_remaining_quota(usage_file: Optional[Path] = None) -> int:
    """
    Return the estimated remaining daily VT calls.
    Synchronous — safe to call from async context for a quick check.
    """
    path = usage_file or _default_usage_file()
    data = _read_json_safe(path)
    if data is None:
        return DAILY_QUOTA
    today = _utc_date_str()
    if data.get("date_utc") != today:
        return DAILY_QUOTA
    used = int(data.get("daily_lookups_used", 0) or 0)
    return max(0, DAILY_QUOTA - used)


# ── Quota increment ────────────────────────────────────────────────────────────

async def increment_quota(
    amount: int = 1,
    usage_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Atomically increment the daily VT usage counter by *amount*.

    Protected by in-process asyncio.Lock.
    Uses tmp → os.replace() for atomic write.
    """
    path = usage_file or _default_usage_file()
    async with _QUOTA_LOCK:
        return _do_increment(path, amount)


def _do_increment(path: Path, amount: int) -> Dict[str, Any]:
    """Synchronous body of increment_quota — called under the lock."""
    today = _utc_date_str()
    data = _read_json_safe(path)

    if data is None or data.get("date_utc") != today:
        data = {"date_utc": today, "daily_lookups_used": 0}

    prev = int(data.get("daily_lookups_used", 0) or 0)
    new_count = prev + amount
    new_data = {"date_utc": today, "daily_lookups_used": new_count}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(new_data))
        os.replace(tmp, path)
    except Exception as exc:
        logger.error("Failed to write VT usage file %s: %s", path, exc)
        raise

    return new_data


# ── Usage history append ───────────────────────────────────────────────────────

def append_usage_history(
    record: Dict[str, Any],
    history_file: Optional[Path] = None,
) -> None:
    """
    Append a metadata-only record to the JSONL usage history file.

    Synchronous — failure is logged and swallowed (does not affect the job).
    NEVER include raw domains, URLs, or item-level content in *record*.
    """
    path = history_file or _default_history_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.warning("Failed to append usage history to %s: %s", path, exc)


# ── Daily history update ───────────────────────────────────────────────────────

def update_daily_history(
    quota_units: int,
    daily_file: Optional[Path] = None,
) -> None:
    """
    Update the daily history JSON with today's incremental quota spend.

    Failure is logged and swallowed — does not corrupt the main job.
    """
    path = daily_file or _default_daily_file()
    today = _utc_date_str()
    try:
        data = _read_json_safe(path) or {}
        prev = int((data.get(today) or {}).get("quota_units", 0))
        data[today] = {"quota_units": prev + quota_units, "tool": "mdi"}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)
    except Exception as exc:
        logger.warning("Failed to update daily history %s: %s", path, exc)


# ── Usage history record builder ───────────────────────────────────────────────

def build_usage_history_record(
    job_id: str,
    items_attempted: int,
    items_completed: int,
    quota_units_consumed: int,
    quota_blocked_count: int,
    errors_count: int,
    held_skipped_count: int,
    processing_options_summary: Dict[str, Any],
    status: str,
) -> Dict[str, Any]:
    """
    Build a metadata-only usage history record.

    MUST NOT contain raw domains, URLs, or individual result rows.
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_name": "mdi",
        "job_id": job_id,
        "operation": "report_lookup",
        "items_attempted": items_attempted,
        "items_completed": items_completed,
        "quota_units_consumed": quota_units_consumed,
        "quota_blocked_count": quota_blocked_count,
        "errors_count": errors_count,
        "held_skipped_count": held_skipped_count,
        "processing_options_summary": processing_options_summary,
        "status": status,
    }
