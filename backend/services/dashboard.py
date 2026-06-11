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

VALID_SOURCE_FILTERS = frozenset({"all", "mdi", "vt_bulk_check"})
SOURCE_LABELS = {
    "mdi": "MDI",
    "vt_bulk_check": "VT Bulk Check",
    "legacy": "Legacy / Unattributed",
}
_AGGREGATION_FIELD_KEYS = frozenset({
    "operation", "items_attempted", "items_completed", "quota_blocked_count",
    "errors_count", "held_skipped_count", "rdap_enriched_count", "rdap_failed_count",
    "whois_fallback_count", "live_check_count", "live_check_skipped_count",
    "live_check_error_count", "refresh_count", "scan_requested_count",
    "scan_completed_count", "scan_failed_count", "auto_rescan_attempted_count",
    "auto_rescan_completed_count", "auto_rescan_failed_count", "auto_rescan_skipped_count",
    "auto_rescan_quota_blocked_count", "flagged_count", "clean_count", "unknown_count",
    "error_item_count", "held_count", "triage_bucket_counts", "error_code_counts",
    "job_duration_seconds",
})


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
    """Keep only MDI tool records (raw JSONL dicts)."""
    return [r for r in records if r.get("tool_name") == "mdi"]


def _format_timestamp_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def detect_source_tool(raw: Dict[str, Any]) -> str:
    tool_name = raw.get("tool_name")
    if tool_name == "mdi":
        return "mdi"
    if tool_name == "vt_bulk_check":
        return "vt_bulk_check"
    return "legacy"


def _aggregation_fields_for_record(raw: Dict[str, Any], source_tool: str) -> Dict[str, Any]:
    """Map raw JSONL fields to aggregate_window-compatible metadata."""
    out: Dict[str, Any] = {}
    for key in _AGGREGATION_FIELD_KEYS:
        if key in raw:
            out[key] = raw[key]

    quota = raw.get("quota_units_consumed")
    if quota is None:
        quota = raw.get("actual_lookups", 0)
    out["quota_units_consumed"] = int(safe_number(quota, 0))

    if source_tool in ("vt_bulk_check", "legacy"):
        out.setdefault("operation", "report_lookup")
        completed = raw.get("items_completed")
        if completed is None:
            completed = raw.get("processed")
        if completed is None:
            completed = raw.get("total") or raw.get("accepted_count")
        out.setdefault("items_completed", int(safe_number(completed, 0)))
        attempted = raw.get("items_attempted")
        if attempted is None:
            attempted = raw.get("total") or raw.get("accepted_count") or out["items_completed"]
        out.setdefault("items_attempted", int(safe_number(attempted, 0)))
        if out.get("job_duration_seconds") is None:
            submitted = raw.get("submitted_at")
            completed_at = raw.get("completed_at")
            if completed_at is None:
                completed_at = raw.get("ts")
            if submitted is not None and completed_at is not None:
                out["job_duration_seconds"] = max(0.0, float(completed_at) - float(submitted))

    return out


def normalize_usage_history_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one JSONL record for shared dashboard attribution (VTFIX-02C)."""
    source_tool = detect_source_tool(raw)
    source_label = SOURCE_LABELS[source_tool]

    ts_iso: Optional[str] = None
    raw_ts = raw.get("timestamp")
    if raw_ts is not None:
        if isinstance(raw_ts, (int, float)):
            ts_iso = _format_timestamp_iso(float(raw_ts))
        else:
            ts_iso = str(raw_ts)
    elif raw.get("ts") is not None:
        ts_iso = _format_timestamp_iso(float(raw["ts"]))

    quota = raw.get("quota_units_consumed")
    if quota is None:
        quota = raw.get("actual_lookups", 0)

    record: Dict[str, Any] = {
        "source_tool": source_tool,
        "source_label": source_label,
        "timestamp": ts_iso,
        "quota_units_consumed": int(safe_number(quota, 0)),
        "job_id": raw.get("job_id"),
        "status": raw.get("status"),
    }
    record.update(_aggregation_fields_for_record(raw, source_tool))
    _assert_no_forbidden_keys(record)
    return record


def filter_by_source(
    records: List[Dict[str, Any]],
    source_filter: str,
) -> List[Dict[str, Any]]:
    if source_filter == "all":
        return list(records)
    return [r for r in records if r.get("source_tool") == source_filter]


def _parse_record_timestamp(record: Dict[str, Any]) -> Optional[datetime]:
    ts = record.get("timestamp")
    if ts is not None:
        try:
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(float(ts), tz=timezone.utc)
            text = str(ts).replace("Z", "+00:00")
            return datetime.fromisoformat(text)
        except (TypeError, ValueError, OSError):
            pass
    ts_unix = record.get("ts")
    if ts_unix is not None:
        try:
            return datetime.fromtimestamp(float(ts_unix), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
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
                from services.error_taxonomy import normalize_error_code

                error_code_counts[normalize_error_code(err.code)] += 1

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
        "quota_lock_timeout_count": job.quota_lock_timeout_count,
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


def _mdi_source_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Records that contribute to MDI-only triage/enrichment metrics."""
    mdi: List[Dict[str, Any]] = []
    for record in records:
        source_tool = record.get("source_tool")
        if source_tool == "mdi":
            mdi.append(record)
        elif source_tool is None and record.get("tool_name") == "mdi":
            mdi.append(record)
    return mdi


def _triage_metrics_applicable_for_filter(source_filter: str) -> bool:
    return source_filter in ("mdi", "all")


def _aggregate_shared_operational(
    records: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """Shared VT operational metrics across MDI, VT Bulk Check, and legacy records."""
    quality = {"records_missing_duration_fields": 0}

    report_lookup = [r for r in records if r.get("operation") == "report_lookup"]
    jobs_run = len(report_lookup)
    items_attempted = _sum_field(records, "items_attempted")
    items_completed = _sum_field(records, "items_completed")

    duration_values: List[float] = []
    for record in records:
        if record.get(_DURATION_FIELD) is not None:
            duration_values.append(safe_number(record.get(_DURATION_FIELD)))
        elif record.get("operation") == "report_lookup":
            quality["records_missing_duration_fields"] += 1

    avg_runtime = None
    if duration_values:
        avg_runtime = round(sum(duration_values) / len(duration_values), 2)

    quota_total = _sum_field(records, "quota_units_consumed")
    summary: Dict[str, Any] = {
        "jobs_run": jobs_run,
        "items_attempted": int(items_attempted),
        "items_completed": int(items_completed),
        "quota_units_consumed": int(quota_total),
        "quota_blocked_count": int(_sum_field(records, "quota_blocked_count")),
        "scan_requested_count": int(_sum_field(records, "scan_requested_count")),
        "scan_completed_count": int(_sum_field(records, "scan_completed_count")),
        "scan_failed_count": int(_sum_field(records, "scan_failed_count")),
        "avg_runtime_seconds": avg_runtime,
        "avg_items_per_job": round(items_completed / jobs_run, 2) if jobs_run else None,
        "avg_quota_per_job": round(quota_total / jobs_run, 2) if jobs_run else None,
    }
    _assert_no_forbidden_keys(summary)
    return summary, quality


def _aggregate_mdi_triage_metrics(
    mdi_records: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """MDI-only triage, enrichment, and workflow metrics."""
    quality = {"records_missing_triage_fields": 0}

    operation_counts: Dict[str, int] = defaultdict(int)
    for record in mdi_records:
        op = record.get("operation") or "unknown"
        operation_counts[str(op)] += 1

    items_attempted = _sum_field(mdi_records, "items_attempted")
    items_completed = _sum_field(mdi_records, "items_completed")

    flagged_total = 0.0
    clean_total = 0.0
    unknown_total = 0.0
    error_item_total = 0.0
    held_total = 0.0
    triage_merged: Dict[str, int] = defaultdict(int)
    error_codes_merged: Dict[str, int] = defaultdict(int)
    triage_records = 0

    for record in mdi_records:
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
            from services.error_taxonomy import normalize_error_code

            for k, v in (record.get("error_code_counts") or {}).items():
                error_codes_merged[normalize_error_code(str(k))] += int(safe_number(v))
        else:
            quality["records_missing_triage_fields"] += 1

    item_basis = items_completed or items_attempted
    triage_available = triage_records > 0

    summary: Dict[str, Any] = {
        "triage_metrics_applicable": True,
        "triage_metrics_scope": "mdi",
        "errors_count": int(_sum_field(mdi_records, "errors_count")),
        "held_skipped_count": int(_sum_field(mdi_records, "held_skipped_count")),
        "rdap_enriched_count": int(_sum_field(mdi_records, "rdap_enriched_count")),
        "rdap_failed_count": int(_sum_field(mdi_records, "rdap_failed_count")),
        "whois_fallback_count": int(_sum_field(mdi_records, "whois_fallback_count")),
        "live_check_count": int(_sum_field(mdi_records, "live_check_count")),
        "live_check_skipped_count": int(_sum_field(mdi_records, "live_check_skipped_count")),
        "live_check_error_count": int(_sum_field(mdi_records, "live_check_error_count")),
        "refresh_count": int(_sum_field(mdi_records, "refresh_count")),
        "auto_rescan_attempted_count": int(_sum_field(mdi_records, "auto_rescan_attempted_count")),
        "auto_rescan_completed_count": int(_sum_field(mdi_records, "auto_rescan_completed_count")),
        "auto_rescan_failed_count": int(_sum_field(mdi_records, "auto_rescan_failed_count")),
        "auto_rescan_skipped_count": int(_sum_field(mdi_records, "auto_rescan_skipped_count")),
        "auto_rescan_quota_blocked_count": int(
            _sum_field(mdi_records, "auto_rescan_quota_blocked_count")
        ),
        "operation_counts": dict(operation_counts),
        "error_rate": round(_sum_field(mdi_records, "errors_count") / items_attempted, 4)
        if items_attempted
        else None,
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


def _empty_mdi_triage_summary() -> Dict[str, Any]:
    """Placeholder when MDI triage metrics do not apply to the selected source."""
    return {
        "triage_metrics_applicable": False,
        "triage_metrics_scope": None,
        "errors_count": None,
        "held_skipped_count": None,
        "rdap_enriched_count": None,
        "rdap_failed_count": None,
        "whois_fallback_count": None,
        "live_check_count": None,
        "live_check_skipped_count": None,
        "live_check_error_count": None,
        "refresh_count": None,
        "auto_rescan_attempted_count": None,
        "auto_rescan_completed_count": None,
        "auto_rescan_failed_count": None,
        "auto_rescan_skipped_count": None,
        "auto_rescan_quota_blocked_count": None,
        "operation_counts": None,
        "error_rate": None,
        "triage_bucket_counts": None,
        "error_code_counts": None,
        "flagged_percent": None,
        "clean_percent": None,
        "unknown_error_percent": None,
        "held_percent": None,
        "flagged_count": None,
        "clean_count": None,
        "unknown_count": None,
        "error_item_count": None,
        "held_count": None,
        "triage_metrics_available": False,
    }


def aggregate_window(
    records: List[Dict[str, Any]],
    *,
    source_filter: str = "mdi",
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """
    Aggregate dashboard window with metric ownership by source.

    Shared operational metrics use all records in the filtered set.
    MDI triage/enrichment metrics use MDI-tagged records only.
    """
    if source_filter not in VALID_SOURCE_FILTERS:
        source_filter = "mdi"

    shared, shared_quality = _aggregate_shared_operational(records)
    quality = {
        "records_missing_triage_fields": 0,
        "records_missing_duration_fields": shared_quality["records_missing_duration_fields"],
    }

    if _triage_metrics_applicable_for_filter(source_filter):
        mdi_records = _mdi_source_records(records)
        mdi_summary, mdi_quality = _aggregate_mdi_triage_metrics(mdi_records)
        quality["records_missing_triage_fields"] = mdi_quality["records_missing_triage_fields"]
        if source_filter == "all":
            mdi_summary["triage_metrics_label"] = "MDI only"
        summary = {**shared, **mdi_summary}
    else:
        summary = {**shared, **_empty_mdi_triage_summary()}

    _assert_no_forbidden_keys(summary)
    return summary, quality


def _assert_no_forbidden_keys(obj: Dict[str, Any]) -> None:
    """Sanity check — dashboard summaries must not include investigation content keys."""
    for key in obj:
        if key in _FORBIDDEN_RESPONSE_KEYS:
            raise ValueError(f"Dashboard summary must not include forbidden key: {key}")


def _contains_leaked_domain(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


def _tool_quota_units(normalized_day: Dict[str, Any], tool: str) -> int:
    tools = normalized_day.get("tools") or {}
    stats = tools.get(tool)
    if isinstance(stats, dict):
        return int(safe_number(stats.get("quota_units"), 0))
    return 0


def build_quota_trend(daily_file: Optional[Path] = None, days: int = 7) -> Dict[str, Any]:
    """Read-only quota trend from vt_daily_history.json (VTFIX-02G per-tool visibility)."""
    from services import daily_history

    path = daily_file or _default_daily_file()
    if not path.exists():
        return {"available": False, "source": "vt_daily_history.json", "last_7_days": []}
    data = daily_history.load_history_file(path)
    if not data:
        return {"available": False, "source": "vt_daily_history.json", "last_7_days": []}

    today = datetime.now(timezone.utc).date()
    rows: List[Dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        entry = data.get(day)
        normalized = daily_history.normalize_day_entry(entry)
        units = daily_history.extract_day_quota_units(entry)
        rows.append({
            "date": day,
            "quota_units": units,
            "mdi_quota_units": _tool_quota_units(normalized, "mdi"),
            "vt_bulk_check_quota_units": _tool_quota_units(normalized, "vt_bulk_check"),
            "legacy_quota_units": _tool_quota_units(normalized, "legacy"),
            "schema_version": normalized.get("schema_version"),
        })

    return {
        "available": True,
        "source": "vt_daily_history.json",
        "last_7_days": rows,
    }


def _read_live_quota_summary() -> Dict[str, Any]:
    """Read-only shared live counter for dashboard display (no writes)."""
    from services.vt_quota import get_usage_summary

    try:
        usage = get_usage_summary()
    except Exception as exc:
        return {"available": False, "error": str(exc)}

    if usage.get("error"):
        return {
            "available": False,
            "error": usage.get("error"),
            "date_utc": usage.get("date_utc"),
        }

    return {
        "available": True,
        "date_utc": usage.get("date_utc"),
        "daily_lookups_used": int(safe_number(usage.get("daily_lookups_used"), 0)),
        "daily_limit": int(safe_number(usage.get("daily_limit"), 500)),
        "remaining": int(safe_number(usage.get("remaining"), 0)),
        "error": None,
    }


def build_dashboard_summary(
    current_job: Optional[InMemoryJob] = None,
    *,
    history_file: Optional[Path] = None,
    daily_file: Optional[Path] = None,
    now: Optional[datetime] = None,
    source_filter: str = "mdi",
) -> Dict[str, Any]:
    """Build full dashboard payload for all windows."""
    now = now or datetime.now(timezone.utc)
    hist_path = history_file or _default_history_file()
    if source_filter not in VALID_SOURCE_FILTERS:
        source_filter = "mdi"

    data_quality: Dict[str, Any] = {
        "history_file_present": hist_path.exists(),
        "source_filter": source_filter,
        "records_read": 0,
        "records_skipped": 0,
        "records_non_mdi_skipped": 0,
        "records_filtered_out": 0,
        "records_by_source": {"mdi": 0, "vt_bulk_check": 0, "legacy": 0},
        "records_missing_triage_fields": 0,
        "records_missing_duration_fields": 0,
        "notes": [],
    }

    normalized: List[Dict[str, Any]] = []
    for line in read_usage_history_lines(hist_path):
        data_quality["records_read"] += 1
        raw = parse_history_line(line)
        if raw is None:
            data_quality["records_skipped"] += 1
            continue
        try:
            record = normalize_usage_history_record(raw)
        except (TypeError, ValueError):
            data_quality["records_skipped"] += 1
            continue
        source_tool = record.get("source_tool", "legacy")
        if source_tool in data_quality["records_by_source"]:
            data_quality["records_by_source"][source_tool] += 1
        normalized.append(record)

    filtered = filter_by_source(normalized, source_filter)
    data_quality["records_filtered_out"] = len(normalized) - len(filtered)
    if source_filter == "mdi":
        data_quality["records_non_mdi_skipped"] = data_quality["records_filtered_out"]

    if not hist_path.exists():
        data_quality["notes"].append("Usage history file not found; historical windows are empty.")
    elif data_quality["records_by_source"]["legacy"] > 0 and source_filter == "all":
        legacy_n = data_quality["records_by_source"]["legacy"]
        data_quality["notes"].append(
            f"Includes {legacy_n} Legacy / Unattributed record(s) without tool_name."
        )

    windows_quality = {"records_missing_triage_fields": 0, "records_missing_duration_fields": 0}

    def _agg(days: Optional[int]) -> Dict[str, Any]:
        nonlocal windows_quality
        subset = window_filter(filtered, now, days)
        summary, q = aggregate_window(subset, source_filter=source_filter)
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

    if data_quality["records_missing_triage_fields"] > 0 and source_filter in ("mdi", "all"):
        data_quality["notes"].append(
            "Older MDI history records lack triage aggregate fields; "
            "MDI triage percentages unavailable until new jobs complete after MDI-17."
        )
    if data_quality["records_missing_duration_fields"] > 0:
        data_quality["notes"].append(
            "Some history records lack job_duration_seconds; average runtime may be partial."
        )
    if data_quality["records_skipped"] > 0:
        data_quality["notes"].append(
            f"Skipped {data_quality['records_skipped']} malformed JSONL line(s)."
        )
    if source_filter != "mdi" and data_quality["records_filtered_out"] > 0:
        data_quality["notes"].append(
            f"Excluded {data_quality['records_filtered_out']} record(s) by source filter."
        )

    if source_filter == "all" and (
        data_quality["records_by_source"]["vt_bulk_check"] > 0
        or data_quality["records_by_source"]["legacy"] > 0
    ):
        data_quality["notes"].append(
            "Shared operational metrics include all selected VT tools; "
            "MDI triage metrics reflect MDI records only."
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
        current["triage_metrics_applicable"] = source_filter != "vt_bulk_check"
        current["triage_metrics_scope"] = "mdi"
        if source_filter == "all":
            current["triage_metrics_label"] = "MDI only"
        if source_filter == "vt_bulk_check":
            current["triage_metrics_available"] = False

    payload = {
        "generated_at": now.isoformat(),
        "source_filter": source_filter,
        "windows": {
            "current": current,
            "last_7_days": last_7,
            "last_30_days": last_30,
            "all_time": all_time,
        },
        "quota_trend": build_quota_trend(daily_file),
        "live_quota": _read_live_quota_summary(),
        "data_quality": data_quality,
    }
    return payload
