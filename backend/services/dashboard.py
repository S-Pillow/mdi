"""
MDI operational dashboard service (MDI-17).

Read-only aggregation from vt_usage_history.jsonl and optional vt_daily_history.json.
No external calls. No runtime file writes. Metadata-only — never exposes raw domains/URLs.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from models import MdiProcessingStatus, TriageBucket
from services.job_store import InMemoryJob

# Fields echoed in dashboard output — must never contain raw investigation content.
_FORBIDDEN_RESPONSE_KEYS = frozenset({
    "input_original",
    "input_normalized",
    "item_order",
    "vt_engine_results",
    "nameservers",
    "epp_status",
    "registrar",
    "results",
})

_TRIAGE_FIELDS = (
    "triage_bucket_counts",
    "flagged_count",
    "clean_count",
    "unknown_count",
    "error_item_count",
    "held_count",
)
_DURATION_FIELD = "job_duration_seconds"


def _default_history_file() -> Path:
    return Path(os.environ.get("VT_USAGE_HISTORY_FILE", "/var/lib/dns-tool/vt_usage_history.jsonl"))


def _default_daily_file() -> Path:
    return Path(os.environ.get("VT_DAILY_HISTORY_FILE", "/var/lib/dns-tool/vt_daily_history.json"))


def safe_number(value: Any, default: float = 0) -> float:
    """Coerce numeric history values; return default on None/invalid."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def merge_counter_dicts(*dicts: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Sum integer counters across dicts."""
    merged: Dict[str, int] = defaultdict(int)
    for d in dicts:
        if not d:
            continue
        for key, val in d.items():
            merged[str(key)] += int(safe_number(val, 0))
    return dict(merged)


def read_usage_history_lines(path: Path) -> Iterator[str]:
    """Yield non-empty lines from JSONL history file."""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                yield stripped


def parse_history_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse one JSONL line; return None if malformed."""
    try:
        data = json.loads(line)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return None


def filter_mdi_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only MDI tool records."""
    return [r for r in records if r.get("tool_name") == "mdi"]


def _parse_record_timestamp(record: Dict[str, Any]) -> Optional[datetime]:
    ts = record.get("timestamp")
    if not ts:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        text = str(ts).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except (TypeError, ValueError, OSError):
        return None


def window_filter(
    records: List[Dict[str, Any]],
    now: datetime,
    days: Optional[int],
) -> List[Dict[str, Any]]:
    """Filter records to last N days (UTC); days=None means all time."""
    if days is None:
        return list(records)
    cutoff = now - timedelta(days=days)
    filtered: List[Dict[str, Any]] = []
    for record in records:
        ts = _parse_record_timestamp(record)
        if ts is None or ts >= cutoff:
            filtered.append(record)
    return filtered


def _is_held_result(bucket: str, processing_status: str, has_hold: bool) -> bool:
    return (
        bucket == TriageBucket.HELD.value
        or processing_status == MdiProcessingStatus.HOLD_SKIPPED.value
        or has_hold
    )


def compute_job_result_aggregates(job: InMemoryJob) -> Dict[str, Any]:
    """
    Compute aggregate-only counters from in-memory job results.
    Never includes raw domains, URLs, or row payloads.
    """
    triage_bucket_counts: Dict[str, int] = defaultdict(int)
    error_code_counts: Dict[str, int] = defaultdict(int)
    flagged_count = 0
    clean_count = 0
    unknown_count = 0
    error_item_count = 0
    held_count = 0

    for result in job.results.values():
        bucket = (
            result.triage_bucket.value
            if hasattr(result.triage_bucket, "value")
            else str(result.triage_bucket)
        )
        proc = (
            result.processing_status.value
            if hasattr(result.processing_status, "value")
            else str(result.processing_status)
        )
        has_hold = bool(result.domain_hold and result.domain_hold.has_hold)

        triage_bucket_counts[bucket] += 1

        if _is_held_result(bucket, proc, has_hold):
            held_count += 1
        elif bucket in (TriageBucket.MALICIOUS.value, TriageBucket.SUSPICIOUS.value) or (
            (result.vt_hits or 0) > 0 or (result.vt_suspicious or 0) > 0
        ):
            flagged_count += 1
        elif bucket == TriageBucket.CLEAN.value:
            clean_count += 1
        elif bucket == TriageBucket.ERROR.value or proc == MdiProcessingStatus.ERROR.value:
            error_item_count += 1
        else:
            unknown_count += 1

        for err in result.errors:
            if err.code:
                error_code_counts[err.code] += 1

    return {
        "triage_bucket_counts": dict(triage_bucket_counts),
        "flagged_count": flagged_count,
        "clean_count": clean_count,
        "unknown_count": unknown_count,
        "error_item_count": error_item_count,
        "held_count": held_count,
        "error_code_counts": dict(error_code_counts),
    }


def build_current_job_summary(job: Optional[InMemoryJob]) -> Dict[str, Any]:
    """Build Current Job window from live/recovered job — aggregates only."""
    if job is None:
        return {"available": False}

    aggregates = compute_job_result_aggregates(job)
    duration = None
    if job.completed_at is not None and job.submitted_at:
        duration = max(0.0, job.completed_at - job.submitted_at)

    total_items = job.total or len(job.results)
    processed = job.processed or len(job.results)

    summary = {
        "available": True,
        "job_id": job.job_id,
        "status": job.status,
        "total": total_items,
        "processed": processed,
        "lookups_used": job.lookups_used,
        "quota_blocked_count": job.quota_blocked_count,
        "rdap_enriched_count": job.rdap_enriched_count,
        "rdap_failed_count": job.rdap_failed_count,
        "whois_fallback_count": job.whois_fallback_count,
        "live_check_count": job.live_check_count,
        "live_check_skipped_count": job.live_check_skipped_count,
        "live_check_error_count": job.live_check_error_count,
        "auto_rescan_attempted_count": job.auto_rescan_attempted_count,
        "auto_rescan_completed_count": job.auto_rescan_completed_count,
        "auto_rescan_failed_count": job.auto_rescan_failed_count,
        "auto_rescan_skipped_count": job.auto_rescan_skipped_count,
        "auto_rescan_quota_blocked_count": job.auto_rescan_quota_blocked_count,
        "job_duration_seconds": duration,
        **aggregates,
    }
    _assert_no_forbidden_keys(summary)
    return summary


def _sum_field(records: List[Dict[str, Any]], field: str) -> float:
    return sum(safe_number(r.get(field), 0) for r in records)


def _pct(numerator: float, denominator: float) -> Optional[float]:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 2)


def aggregate_window(records: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """
    Aggregate historical window metrics from MDI history records.
    Returns (summary, quality_counters).
    """
    quality = {
        "records_missing_triage_fields": 0,
        "records_missing_duration_fields": 0,
    }

    report_lookup = [r for r in records if r.get("operation") == "report_lookup"]
    jobs_run = len(report_lookup)

    operation_counts: Dict[str, int] = defaultdict(int)
    for record in records:
        op = record.get("operation") or "unknown"
        operation_counts[str(op)] += 1

    items_attempted = _sum_field(records, "items_attempted")
    items_completed = _sum_field(records, "items_completed")

    flagged_total = 0.0
    clean_total = 0.0
    unknown_total = 0.0
    error_item_total = 0.0
    held_total = 0.0
    triage_merged: Dict[str, int] = defaultdict(int)
    error_codes_merged: Dict[str, int] = defaultdict(int)
    duration_values: List[float] = []
    triage_records = 0

    for record in records:
        has_triage = all(record.get(f) is not None for f in ("flagged_count", "clean_count"))
        if record.get("triage_bucket_counts") is not None:
            has_triage = True
        if has_triage and (
            record.get("triage_bucket_counts") is not None
            or record.get("flagged_count") is not None
        ):
            triage_records += 1
            flagged_total += safe_number(record.get("flagged_count"))
            clean_total += safe_number(record.get("clean_count"))
            unknown_total += safe_number(record.get("unknown_count"))
            error_item_total += safe_number(record.get("error_item_count"))
            held_total += safe_number(record.get("held_count"))
            for k, v in (record.get("triage_bucket_counts") or {}).items():
                triage_merged[str(k)] += int(safe_number(v))
            for k, v in (record.get("error_code_counts") or {}).items():
                error_codes_merged[str(k)] += int(safe_number(v))
        else:
            quality["records_missing_triage_fields"] += 1

        if record.get(_DURATION_FIELD) is not None:
            duration_values.append(safe_number(record.get(_DURATION_FIELD)))
        elif record.get("operation") == "report_lookup":
            quality["records_missing_duration_fields"] += 1

    item_basis = items_completed or items_attempted
    triage_available = triage_records > 0

    avg_runtime = None
    if duration_values:
        avg_runtime = round(sum(duration_values) / len(duration_values), 2)

    summary: Dict[str, Any] = {
        "jobs_run": jobs_run,
        "items_attempted": int(items_attempted),
        "items_completed": int(items_completed),
        "quota_units_consumed": int(_sum_field(records, "quota_units_consumed")),
        "quota_blocked_count": int(_sum_field(records, "quota_blocked_count")),
        "errors_count": int(_sum_field(records, "errors_count")),
        "held_skipped_count": int(_sum_field(records, "held_skipped_count")),
        "rdap_enriched_count": int(_sum_field(records, "rdap_enriched_count")),
        "rdap_failed_count": int(_sum_field(records, "rdap_failed_count")),
        "whois_fallback_count": int(_sum_field(records, "whois_fallback_count")),
        "live_check_count": int(_sum_field(records, "live_check_count")),
        "live_check_skipped_count": int(_sum_field(records, "live_check_skipped_count")),
        "live_check_error_count": int(_sum_field(records, "live_check_error_count")),
        "refresh_count": int(_sum_field(records, "refresh_count")),
        "scan_requested_count": int(_sum_field(records, "scan_requested_count")),
        "scan_completed_count": int(_sum_field(records, "scan_completed_count")),
        "scan_failed_count": int(_sum_field(records, "scan_failed_count")),
        "auto_rescan_attempted_count": int(_sum_field(records, "auto_rescan_attempted_count")),
        "auto_rescan_completed_count": int(_sum_field(records, "auto_rescan_completed_count")),
        "auto_rescan_failed_count": int(_sum_field(records, "auto_rescan_failed_count")),
        "auto_rescan_skipped_count": int(_sum_field(records, "auto_rescan_skipped_count")),
        "auto_rescan_quota_blocked_count": int(
            _sum_field(records, "auto_rescan_quota_blocked_count")
        ),
        "operation_counts": dict(operation_counts),
        "avg_items_per_job": round(items_completed / jobs_run, 2) if jobs_run else None,
        "avg_quota_per_job": round(
            _sum_field(records, "quota_units_consumed") / jobs_run, 2
        ) if jobs_run else None,
        "error_rate": round(_sum_field(records, "errors_count") / items_attempted, 4)
        if items_attempted else None,
        "avg_runtime_seconds": avg_runtime,
        "triage_bucket_counts": dict(triage_merged) if triage_available else None,
        "error_code_counts": dict(error_codes_merged) if error_codes_merged else None,
        "flagged_percent": _pct(flagged_total, item_basis) if triage_available else None,
        "clean_percent": _pct(clean_total, item_basis) if triage_available else None,
        "unknown_error_percent": _pct(unknown_total + error_item_total, item_basis)
        if triage_available
        else None,
        "held_percent": _pct(held_total, item_basis) if triage_available else None,
        "flagged_count": int(flagged_total) if triage_available else None,
        "clean_count": int(clean_total) if triage_available else None,
        "unknown_count": int(unknown_total) if triage_available else None,
        "error_item_count": int(error_item_total) if triage_available else None,
        "held_count": int(held_total) if triage_available else None,
        "triage_metrics_available": triage_available,
    }
    _assert_no_forbidden_keys(summary)
    return summary, quality


def _assert_no_forbidden_keys(obj: Dict[str, Any]) -> None:
    """Sanity check — dashboard summaries must not include investigation content keys."""
    for key in obj:
        if key in _FORBIDDEN_RESPONSE_KEYS:
            raise ValueError(f"Dashboard summary must not include forbidden key: {key}")


def _contains_leaked_domain(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


def build_quota_trend(daily_file: Optional[Path] = None, days: int = 7) -> Dict[str, Any]:
    """Read-only quota trend from vt_daily_history.json."""
    path = daily_file or _default_daily_file()
    if not path.exists():
        return {"available": False, "source": "vt_daily_history.json", "last_7_days": []}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {"available": False, "source": "vt_daily_history.json", "last_7_days": []}
    except Exception:
        return {"available": False, "source": "vt_daily_history.json", "last_7_days": []}

    today = datetime.now(timezone.utc).date()
    rows: List[Dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        entry = data.get(day)
        units = 0
        if isinstance(entry, dict):
            units = int(safe_number(entry.get("quota_units"), 0))
        elif entry is not None:
            units = int(safe_number(entry, 0))
        rows.append({"date": day, "quota_units": units})

    return {
        "available": True,
        "source": "vt_daily_history.json",
        "last_7_days": rows,
    }


def build_dashboard_summary(
    current_job: Optional[InMemoryJob] = None,
    *,
    history_file: Optional[Path] = None,
    daily_file: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build full dashboard payload for all windows."""
    now = now or datetime.now(timezone.utc)
    hist_path = history_file or _default_history_file()

    data_quality: Dict[str, Any] = {
        "history_file_present": hist_path.exists(),
        "records_read": 0,
        "records_skipped": 0,
        "records_non_mdi_skipped": 0,
        "records_missing_triage_fields": 0,
        "records_missing_duration_fields": 0,
        "notes": [],
    }

    parsed: List[Dict[str, Any]] = []
    for line in read_usage_history_lines(hist_path):
        data_quality["records_read"] += 1
        record = parse_history_line(line)
        if record is None:
            data_quality["records_skipped"] += 1
            continue
        if record.get("tool_name") != "mdi":
            data_quality["records_non_mdi_skipped"] += 1
            continue
        parsed.append(record)

    if not hist_path.exists():
        data_quality["notes"].append("Usage history file not found; historical windows are empty.")
    elif data_quality["records_missing_triage_fields"] == 0 and parsed:
        # Will be updated during aggregation
        pass

    mdi_records = parsed
    windows_quality = {"records_missing_triage_fields": 0, "records_missing_duration_fields": 0}

    def _agg(days: Optional[int]) -> Dict[str, Any]:
        nonlocal windows_quality
        subset = window_filter(mdi_records, now, days)
        summary, q = aggregate_window(subset)
        windows_quality["records_missing_triage_fields"] += q["records_missing_triage_fields"]
        windows_quality["records_missing_duration_fields"] += q["records_missing_duration_fields"]
        return summary

    last_7 = _agg(7)
    last_30 = _agg(30)
    all_time = _agg(None)

    data_quality["records_missing_triage_fields"] = windows_quality[
        "records_missing_triage_fields"
    ]
    data_quality["records_missing_duration_fields"] = windows_quality[
        "records_missing_duration_fields"
    ]

    if data_quality["records_missing_triage_fields"] > 0:
        data_quality["notes"].append(
            "Older history records lack triage aggregate fields; "
            "percentages unavailable until new jobs complete after MDI-17."
        )
    if data_quality["records_missing_duration_fields"] > 0:
        data_quality["notes"].append(
            "Some history records lack job_duration_seconds; average runtime may be partial."
        )
    if data_quality["records_skipped"] > 0:
        data_quality["notes"].append(
            f"Skipped {data_quality['records_skipped']} malformed JSONL line(s)."
        )

    current = build_current_job_summary(current_job)
    if current.get("available"):
        total = current.get("processed") or current.get("total") or 0
        if total > 0:
            current["flagged_percent"] = _pct(current.get("flagged_count", 0), total)
            current["clean_percent"] = _pct(current.get("clean_count", 0), total)
            current["unknown_error_percent"] = _pct(
                safe_number(current.get("unknown_count"))
                + safe_number(current.get("error_item_count")),
                total,
            )
            current["held_percent"] = _pct(current.get("held_count", 0), total)

    payload = {
        "generated_at": now.isoformat(),
        "windows": {
            "current": current,
            "last_7_days": last_7,
            "last_30_days": last_30,
            "all_time": all_time,
        },
        "quota_trend": build_quota_trend(daily_file),
        "data_quality": data_quality,
    }
    return payload
