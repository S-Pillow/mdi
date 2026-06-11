#!/usr/bin/env python3
"""
VTFIX-02H — Daily-history metadata backfill dry-run (read-only by default).

Analyzes vt_daily_history.json against vt_usage_history.jsonl and proposes a
per-date schema v2 normalization plan. Approved runtime write is available only
via --write-approved-normalization (operator-approved dates only).

Usage:
  python3 scripts/vtfix-02h-daily-history-backfill-dry-run.py
  python3 scripts/vtfix-02h-daily-history-backfill-dry-run.py \\
      --daily-file /path/to/vt_daily_history.json \\
      --jsonl-file /path/to/vt_usage_history.jsonl
  python3 scripts/vtfix-02h-daily-history-backfill-dry-run.py \\
      --write-approved-normalization
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow importing backend daily_history when run from repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services import daily_history  # noqa: E402

DEFAULT_DAILY = Path("/var/lib/dns-tool/vt_daily_history.json")
DEFAULT_JSONL = Path("/var/lib/dns-tool/vt_usage_history.jsonl")

DATE_FIELDS = ("timestamp", "submitted_at", "completed_at", "ts")
QUOTA_FIELDS = ("quota_units_consumed", "actual_lookups")
KNOWN_TOOLS = frozenset({"mdi", "vt_bulk_check"})

# Operator-approved normalization targets (VTFIX-02H-RUNTIME).
APPROVED_WRITE_DATES: Dict[str, Dict[str, int]] = {
    "2026-06-05": {"total": 1, "proposed_mdi": 0, "proposed_legacy": 1},
    "2026-06-06": {"total": 1478, "proposed_mdi": 1478, "proposed_legacy": 0},
    "2026-06-08": {"total": 89, "proposed_mdi": 89, "proposed_legacy": 0},
    "2026-06-09": {"total": 4, "proposed_mdi": 4, "proposed_legacy": 0},
    "2026-06-10": {"total": 242, "proposed_mdi": 0, "proposed_legacy": 242},
}

MANUAL_REVIEW_DATES: Dict[str, Dict[str, int]] = {
    "2026-06-03": {"total": 138},
    "2026-06-07": {"total": 5},
}

PRESERVE_V2_DATE = "2026-06-11"
PRESERVE_V2_EXPECTED = {
    "total": 4,
    "proposed_mdi": 2,
    "proposed_vt_bulk_check": 2,
    "proposed_legacy": 0,
}


def classify_day_shape(raw: Any) -> str:
    if raw is None:
        return "missing"
    if isinstance(raw, (int, float)):
        return "legacy_int"
    if not isinstance(raw, dict):
        return "malformed"
    if "tools" in raw and isinstance(raw.get("tools"), dict):
        return "v2_tools"
    if "quota_units" in raw:
        return "legacy_dict"
    return "other"


def current_day_total(raw: Any) -> int:
    return daily_history.extract_day_quota_units(raw)


def derive_record_date(record: Dict[str, Any]) -> Optional[str]:
    for field in DATE_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and len(value) >= 10:
            return value[:10]
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")
            except (OSError, OverflowError, ValueError):
                continue
    return None


def derive_record_quota(record: Dict[str, Any]) -> int:
    for field in QUOTA_FIELDS:
        if field in record and record[field] is not None:
            try:
                return int(record[field])
            except (TypeError, ValueError):
                continue
    return 0


def aggregate_jsonl(path: Path) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int]]:
    """Return per-date tool buckets and field-presence counts (no raw records)."""
    by_date: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"mdi": 0, "vt_bulk_check": 0, "legacy": 0, "lines": 0}
    )
    field_presence: Dict[str, int] = defaultdict(int)
    malformed_lines = 0
    legacy_line_count = 0
    total_lines = 0

    if not path.exists():
        return {}, {"total_lines": 0, "malformed_lines": 0, "legacy_or_missing_tool_lines": 0}

    for line in path.read_text().splitlines():
        total_lines += 1
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines += 1
            continue
        if not isinstance(record, dict):
            malformed_lines += 1
            continue

        for field in ("tool_name", "timestamp", "quota_units_consumed", "actual_lookups", "job_id", "status"):
            if field in record and record[field] is not None and record[field] != "":
                field_presence[field] += 1

        tool = record.get("tool_name")
        if tool not in KNOWN_TOOLS:
            legacy_line_count += 1
        bucket = tool if tool in KNOWN_TOOLS else "legacy"
        quota = derive_record_quota(record)
        date = derive_record_date(record) or "unknown"
        by_date[date][bucket] += quota
        by_date[date]["lines"] += 1

    meta: Dict[str, int] = {
        "total_lines": total_lines,
        "malformed_lines": malformed_lines,
        "legacy_or_missing_tool_lines": legacy_line_count,
    }
    meta.update(field_presence)
    return dict(by_date), meta


def summarize_daily_shapes(data: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for entry in data.values():
        counts[classify_day_shape(entry)] += 1
    return dict(counts)


def proposed_from_daily_only(raw: Any) -> Dict[str, Any]:
    """Propose v2 entry using existing daily-history evidence only."""
    return daily_history.normalize_day_entry(raw)


def jsonl_quota_sum(buckets: Dict[str, int]) -> int:
    return int(buckets.get("mdi", 0) + buckets.get("vt_bulk_check", 0) + buckets.get("legacy", 0))


def assess_confidence(
    *,
    current_shape: str,
    raw: Any,
    current_total: int,
    proposed: Dict[str, Any],
    jsonl_buckets: Optional[Dict[str, int]],
) -> Tuple[str, str, bool]:
    """Return confidence, reason, write_recommended."""
    tools = proposed.get("tools") or {}
    mdi = int((tools.get("mdi") or {}).get("quota_units", 0) or 0)
    vt_bulk = int((tools.get("vt_bulk_check") or {}).get("quota_units", 0) or 0)
    legacy = int((tools.get("legacy") or {}).get("quota_units", 0) or 0)
    proposed_total = int(proposed.get("total_quota_units", 0) or 0)

    if proposed_total != current_total:
        return (
            "manual_review",
            f"Proposed total {proposed_total} differs from current total {current_total}",
            False,
        )

    if current_shape == "v2_tools" and isinstance(raw, dict) and raw.get("schema_version") == 2:
        unchanged = (
            int(raw.get("total_quota_units", 0) or 0) == proposed_total
            and mdi == int((raw.get("tools", {}).get("mdi") or {}).get("quota_units", 0) or 0)
            and vt_bulk == int((raw.get("tools", {}).get("vt_bulk_check") or {}).get("quota_units", 0) or 0)
            and legacy == int((raw.get("tools", {}).get("legacy") or {}).get("quota_units", 0) or 0)
        )
        if unchanged:
            return "high", "Already persisted schema v2 with matching buckets; no write needed", False
        return "medium", "Schema v2 present but bucket values differ after normalization; review before write", False

    if current_shape == "legacy_int":
        reason = "Legacy integer day; normalize to schema v2 with legacy bucket only (totals preserved)"
        return "high", reason, True

    if current_shape == "legacy_dict":
        tool = (raw.get("tool") or raw.get("tool_name")) if isinstance(raw, dict) else None
        if tool == "mdi":
            return (
                "high",
                "Legacy dict includes tool=mdi; normalize to schema v2 mdi bucket (field evidence)",
                True,
            )
        if tool == "vt_bulk_check":
            return (
                "high",
                "Legacy dict includes tool=vt_bulk_check; normalize to schema v2 vt_bulk_check bucket",
                True,
            )
        return (
            "high",
            "Legacy dict without known tool; normalize to schema v2 legacy bucket",
            True,
        )

    if current_shape in ("malformed", "missing", "other"):
        return "manual_review", f"Unreadable or unsupported day shape: {current_shape}", False

    return "medium", "Normalization applied; review before write", False


def apply_jsonl_conflict_rules(
    confidence: str,
    reason: str,
    write_recommended: bool,
    *,
    current_total: int,
    jsonl_buckets: Optional[Dict[str, int]],
) -> Tuple[str, str, bool]:
    if not jsonl_buckets or jsonl_buckets.get("lines", 0) == 0:
        return confidence, reason, write_recommended

    js = jsonl_quota_sum(jsonl_buckets)
    if js == current_total and jsonl_buckets.get("mdi", 0) == 0 and jsonl_buckets.get("vt_bulk_check", 0) == 0:
        # JSONL confirms legacy-only attribution for the day; still no tool upgrade without tool_name.
        if "JSONL" not in reason:
            reason = f"{reason}; JSONL legacy-only sum matches daily total"
        return confidence, reason, write_recommended

    if js == 0:
        return confidence, f"{reason}; no JSONL records for date", write_recommended

    if js != current_total:
        return (
            "manual_review",
            f"{reason}; JSONL attributed sum {js} != daily total {current_total}",
            False,
        )

    # Exact JSONL match with tagged tools — informational only; proposal stays daily-history based.
    mdi_j = jsonl_buckets.get("mdi", 0)
    vt_j = jsonl_buckets.get("vt_bulk_check", 0)
    leg_j = jsonl_buckets.get("legacy", 0)
    if mdi_j or vt_j:
        note = f"; JSONL tagged split mdi={mdi_j} vt_bulk={vt_j} legacy={leg_j} matches total"
        if confidence == "high":
            return confidence, reason + note, write_recommended
        return "medium", reason + note, write_recommended

    return confidence, reason, write_recommended


def build_plan(
    daily_file: Path,
    jsonl_file: Path,
) -> Dict[str, Any]:
    daily_data = daily_history.load_history_file(daily_file)
    jsonl_by_date, jsonl_meta = aggregate_jsonl(jsonl_file)
    shape_summary = summarize_daily_shapes(daily_data)

    plans: List[Dict[str, Any]] = []
    for date in sorted(daily_data.keys()):
        raw = daily_data[date]
        current_shape = classify_day_shape(raw)
        current_total = current_day_total(raw)
        proposed = proposed_from_daily_only(raw)
        tools = proposed.get("tools") or {}

        jsonl_buckets = jsonl_by_date.get(date)
        confidence, reason, write_recommended = assess_confidence(
            current_shape=current_shape,
            raw=raw,
            current_total=current_total,
            proposed=proposed,
            jsonl_buckets=jsonl_buckets,
        )
        confidence, reason, write_recommended = apply_jsonl_conflict_rules(
            confidence,
            reason,
            write_recommended,
            current_total=current_total,
            jsonl_buckets=jsonl_buckets,
        )

        plans.append(
            {
                "date": date,
                "current_shape": current_shape,
                "current_total": current_total,
                "proposed_schema_version": proposed.get("schema_version"),
                "proposed_total": int(proposed.get("total_quota_units", 0) or 0),
                "proposed_mdi": int((tools.get("mdi") or {}).get("quota_units", 0) or 0),
                "proposed_vt_bulk_check": int((tools.get("vt_bulk_check") or {}).get("quota_units", 0) or 0),
                "proposed_legacy": int((tools.get("legacy") or {}).get("quota_units", 0) or 0),
                "confidence": confidence,
                "reason": reason,
                "write_recommended": write_recommended,
            }
        )

    return {
        "daily_file": str(daily_file),
        "jsonl_file": str(jsonl_file),
        "daily_date_count": len(daily_data),
        "daily_shape_summary": shape_summary,
        "jsonl_meta": jsonl_meta,
        "jsonl_dates_with_records": sorted(k for k in jsonl_by_date if k != "unknown"),
        "plans": plans,
    }


def format_report(result: Dict[str, Any]) -> str:
    lines = [
        "VTFIX-02H daily-history backfill dry-run",
        f"daily_file: {result['daily_file']}",
        f"jsonl_file: {result['jsonl_file']}",
        f"daily_date_count: {result['daily_date_count']}",
        f"daily_shape_summary: {json.dumps(result['daily_shape_summary'], sort_keys=True)}",
        f"jsonl_meta: {json.dumps(result['jsonl_meta'], sort_keys=True)}",
        "",
        "proposed_backfill_plan:",
    ]
    header = (
        "date | shape | cur_total | prop_total | mdi | vt_bulk | legacy | "
        "confidence | write?"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for row in result["plans"]:
        lines.append(
            "{date} | {current_shape} | {current_total} | {proposed_total} | "
            "{proposed_mdi} | {proposed_vt_bulk_check} | {proposed_legacy} | "
            "{confidence} | {write_flag}".format(
                write_flag="yes" if row["write_recommended"] else "no",
                **row,
            )
        )
        lines.append(f"  reason: {row['reason']}")
    eligible = [r["date"] for r in result["plans"] if r["confidence"] == "high" and r["write_recommended"]]
    review = [r["date"] for r in result["plans"] if r["confidence"] == "manual_review"]
    lines.extend(
        [
            "",
            f"high_confidence_write_candidates: {eligible or '(none)'}",
            f"manual_review_dates: {review or '(none)'}",
            "",
            "NOTE: This script is dry-run only. No runtime files were modified.",
        ]
    )
    return "\n".join(lines)


def _plan_row_for_date(plans: List[Dict[str, Any]], date: str) -> Optional[Dict[str, Any]]:
    for row in plans:
        if row["date"] == date:
            return row
    return None


def validate_approved_write_preconditions(
    data: Dict[str, Any],
    plans: List[Dict[str, Any]],
) -> List[str]:
    """Return validation errors; empty list means safe to proceed."""
    errors: List[str] = []

    required_dates = set(APPROVED_WRITE_DATES) | set(MANUAL_REVIEW_DATES) | {PRESERVE_V2_DATE}
    missing = required_dates - set(data.keys())
    if missing:
        errors.append(f"Missing expected dates: {sorted(missing)}")

    for date, expected in APPROVED_WRITE_DATES.items():
        row = _plan_row_for_date(plans, date)
        if row is None:
            errors.append(f"Approved date missing from plan: {date}")
            continue
        if row["current_total"] != expected["total"]:
            errors.append(
                f"{date}: current total {row['current_total']} != expected {expected['total']}"
            )
        if row["proposed_total"] != expected["total"]:
            errors.append(
                f"{date}: proposed total {row['proposed_total']} != expected {expected['total']}"
            )
        if row["proposed_mdi"] != expected["proposed_mdi"]:
            errors.append(
                f"{date}: proposed mdi {row['proposed_mdi']} != expected {expected['proposed_mdi']}"
            )
        if row["proposed_legacy"] != expected["proposed_legacy"]:
            errors.append(
                f"{date}: proposed legacy {row['proposed_legacy']} != expected {expected['proposed_legacy']}"
            )
        if row["confidence"] != "high" or not row["write_recommended"]:
            errors.append(f"{date}: dry-run no longer high-confidence write candidate")

    for date, expected in MANUAL_REVIEW_DATES.items():
        raw = data.get(date)
        if raw is None:
            errors.append(f"Manual-review date missing: {date}")
            continue
        if current_day_total(raw) != expected["total"]:
            errors.append(
                f"{date}: manual-review total {current_day_total(raw)} != expected {expected['total']}"
            )

    v2_raw = data.get(PRESERVE_V2_DATE)
    if v2_raw is None:
        errors.append(f"Preserve date missing: {PRESERVE_V2_DATE}")
    else:
        if classify_day_shape(v2_raw) != "v2_tools":
            errors.append(f"{PRESERVE_V2_DATE}: expected v2_tools shape")
        row = _plan_row_for_date(plans, PRESERVE_V2_DATE)
        if row:
            exp = PRESERVE_V2_EXPECTED
            for key in ("total", "proposed_mdi", "proposed_vt_bulk_check", "proposed_legacy"):
                field = "current_total" if key == "total" else key
                if row.get(field) != exp[key if key != "total" else "total"]:
                    errors.append(f"{PRESERVE_V2_DATE}: {field} mismatch vs expected v2 state")

    return errors


def create_daily_history_backup(daily_file: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = daily_file.parent / "backups" / f"vtfix-02h-runtime-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / daily_file.name
    shutil.copy2(daily_file, backup_path)
    return backup_path


def execute_approved_normalization(
    daily_file: Path,
    jsonl_file: Path,
    *,
    require_production_path: bool = False,
) -> Dict[str, Any]:
    """Normalize approved dates only; refuse on validation failure."""
    if require_production_path and daily_file.resolve() != DEFAULT_DAILY.resolve():
        raise ValueError("Approved write mode only supports the production daily-history path")

    data = daily_history.load_history_file(daily_file)
    plan = build_plan(daily_file, jsonl_file)
    errors = validate_approved_write_preconditions(data, plan["plans"])
    if errors:
        raise RuntimeError("Pre-write validation failed: " + "; ".join(errors))

    preserve_dates = list(MANUAL_REVIEW_DATES.keys()) + [PRESERVE_V2_DATE]
    preserved: Dict[str, Any] = {d: copy.deepcopy(data[d]) for d in preserve_dates if d in data}

    totals_before = {d: current_day_total(data[d]) for d in data}
    shapes_before = {d: classify_day_shape(data[d]) for d in data}

    new_data = copy.deepcopy(data)
    written: List[str] = []
    for date in sorted(APPROVED_WRITE_DATES.keys()):
        normalized = proposed_from_daily_only(new_data[date])
        new_data[date] = normalized
        written.append(date)

    for date, original in preserved.items():
        if new_data.get(date) != original:
            raise RuntimeError(f"Preserve invariant violated for {date}")

    totals_after = {d: current_day_total(new_data[d]) for d in new_data}
    if totals_before != totals_after:
        raise RuntimeError("Total preservation check failed")

    # Validate serialized JSON before touching runtime file.
    payload = json.dumps(new_data, indent=2, sort_keys=True)
    json.loads(payload)

    backup_path = create_daily_history_backup(daily_file)
    mode = daily_file.stat().st_mode
    daily_history.save_history_file(daily_file, new_data, indent=2)
    os.chmod(daily_file, mode)

    shapes_after = {d: classify_day_shape(new_data[d]) for d in new_data}
    return {
        "status": "written",
        "daily_file": str(daily_file),
        "backup_path": str(backup_path),
        "dates_written": written,
        "dates_preserved": preserve_dates,
        "totals_before": totals_before,
        "totals_after": totals_after,
        "shapes_before": shapes_before,
        "shapes_after": shapes_after,
        "daily_shape_summary_after": summarize_daily_shapes(new_data),
    }


def format_write_summary(result: Dict[str, Any]) -> str:
    lines = [
        "VTFIX-02H approved normalization write complete",
        f"daily_file: {result['daily_file']}",
        f"backup_path: {result['backup_path']}",
        f"dates_written: {result['dates_written']}",
        f"dates_preserved: {result['dates_preserved']}",
        f"daily_shape_summary_after: {json.dumps(result['daily_shape_summary_after'], sort_keys=True)}",
        "totals preserved: yes",
    ]
    for date in result["dates_written"]:
        lines.append(
            f"  {date}: {result['shapes_before'][date]} -> {result['shapes_after'][date]} "
            f"total={result['totals_after'][date]}"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    cli = argv if argv is not None else sys.argv[1:]
    if "--write" in cli or "--apply" in cli:
        print("ERROR: Use --write-approved-normalization for approved runtime write.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description="VTFIX-02H daily-history backfill dry-run")
    parser.add_argument("--daily-file", type=Path, default=DEFAULT_DAILY)
    parser.add_argument("--jsonl-file", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    parser.add_argument(
        "--write-approved-normalization",
        action="store_true",
        help="Write operator-approved high-confidence schema v2 normalization only",
    )
    args = parser.parse_args(cli)

    if args.write_approved_normalization:
        if args.daily_file.resolve() != DEFAULT_DAILY.resolve():
            print(
                "ERROR: Approved write requires production daily-history path "
                f"({DEFAULT_DAILY}) without --daily-file override.",
                file=sys.stderr,
            )
            return 2
        try:
            result = execute_approved_normalization(
                args.daily_file,
                args.jsonl_file,
            )
        except (RuntimeError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(format_write_summary(result))
        return 0

    result = build_plan(args.daily_file, args.jsonl_file)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
