"""
MDI latest-job persistence service.

Writes the latest completed/error MDI job to a dedicated recovery file
(/var/lib/dns-tool/mdi_latest_job.json by default).

Design:
  - Only completed (done/error) jobs are persisted.  Queued/running jobs
    are never written — if the backend restarts mid-job, that in-flight work
    is documented as lost (accepted MDI-08 limitation).
  - Atomic write: content → .tmp → os.replace().  Prevents partial-write corruption.
  - File permissions set to 0o600 after write (private to the running process).
  - Uses a dedicated asyncio.Lock (_PERSISTENCE_LOCK) that is entirely separate
    from the quota lock (_QUOTA_LOCK) and job store lock (_STORE_LOCK).
    The three locks are never held simultaneously.
  - Path is injectable via MDI_LATEST_JOB_FILE env var for test isolation.
  - All read failures are caught, logged, and returned as None — the backend
    must never crash because a recovery file is missing or corrupt.

Data sensitivity:
  - mdi_latest_job.json MAY contain normalized domains/URLs and per-item VT
    results because it is a private, single-slot, operator-owned recovery file.
  - This is distinct from vt_usage_history.jsonl (shared, metadata-only, audited).
  - The file is git-excluded via /var/lib/dns-tool/ in .gitignore.
  - The file is overwritten by each subsequent completed job.  No long-term
    history of domains is created.

Hard guarantees:
  - Never writes to vt_usage.json, vt_usage_history.jsonl, vt_daily_history.json,
    or vt_latest_job.json.
  - Never consumes VT quota.
  - Never appends to shared usage history.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from models import MdiResultItem

logger = logging.getLogger("mdi.job_persistence")

_PERSISTENCE_LOCK = asyncio.Lock()
_TERMINAL_JOB_STATUSES = frozenset({"done", "error"})


# ── Path helpers ───────────────────────────────────────────────────────────────

def _default_job_file() -> Path:
    return Path(os.environ.get("MDI_LATEST_JOB_FILE", "/var/lib/dns-tool/mdi_latest_job.json"))


# ── Serialization ──────────────────────────────────────────────────────────────

def serialize_job(job: "job_store.InMemoryJob") -> Dict[str, Any]:  # type: ignore[name-defined]
    """
    Serialize an InMemoryJob to a plain JSON-compatible dict.

    MdiResultItem values are serialized via .model_dump() with datetime objects
    converted to ISO-8601 strings for round-trip fidelity.
    """
    results_serialized = {}
    for key, result in job.results.items():
        results_serialized[key] = result.model_dump(mode="json")

    return {
        "job_id": job.job_id,
        "status": job.status,
        "submitted_at": job.submitted_at,
        "completed_at": job.completed_at,
        "total": job.total,
        "processed": job.processed,
        "held_skipped": job.held_skipped,
        "rejected_count": job.rejected_count,
        "quota_blocked_count": job.quota_blocked_count,
        "quota_lock_timeout_count": job.quota_lock_timeout_count,
        "estimated_requests": job.estimated_requests,
        "lookups_used": job.lookups_used,
        "use_domain_reports": job.use_domain_reports,
        "stale_threshold_days": job.stale_threshold_days,
        "auto_rescan_stale": job.auto_rescan_stale,
        "max_auto_rescans": job.max_auto_rescans,
        "cloudflare_rank_lookup_enabled": job.cloudflare_rank_lookup_enabled,
        "input_mode": job.input_mode,
        "error_message": job.error_message,
        "item_order": job.item_order,
        "results": results_serialized,
        "usage_history_written": job.usage_history_written,
        # MDI-11 enrichment counters (metadata-only — counts survive recovery)
        "rdap_enriched_count": job.rdap_enriched_count,
        "rdap_failed_count": job.rdap_failed_count,
        "whois_fallback_count": job.whois_fallback_count,
        "hold_detected_by_enrichment_count": job.hold_detected_by_enrichment_count,
        "enrichment_skipped_uploaded_hold_count": job.enrichment_skipped_uploaded_hold_count,
        # MDI-12 live-check counters (metadata-only — counts survive recovery)
        "live_check_count": job.live_check_count,
        "live_check_skipped_count": job.live_check_skipped_count,
        "live_check_error_count": job.live_check_error_count,
        # MDI-15 action state
        "action_in_progress": job.action_in_progress,
        "last_action_type": job.last_action_type,
        "last_action_at": job.last_action_at,
        "vt_refresh_count": job.vt_refresh_count,
        "vt_scan_requested_count": job.vt_scan_requested_count,
        "vt_scan_failed_count": job.vt_scan_failed_count,
        # MDI-15A auto-rescan
        "auto_rescan_attempted_count": job.auto_rescan_attempted_count,
        "auto_rescan_completed_count": job.auto_rescan_completed_count,
        "auto_rescan_failed_count": job.auto_rescan_failed_count,
        "auto_rescan_skipped_count": job.auto_rescan_skipped_count,
        "auto_rescan_quota_blocked_count": job.auto_rescan_quota_blocked_count,
    }


def deserialize_job(data: Dict[str, Any]) -> "job_store.InMemoryJob":  # type: ignore[name-defined]
    """
    Deserialize a plain dict back into an InMemoryJob.

    Reconstructs MdiResultItem values from their serialized dicts.
    Raises ValueError or ValidationError on schema mismatch — callers must catch.
    """
    from services.job_store import InMemoryJob

    results: Dict[str, MdiResultItem] = {}
    for key, raw in (data.get("results") or {}).items():
        results[key] = MdiResultItem.model_validate(raw)

    return InMemoryJob(
        job_id=data["job_id"],
        status=data["status"],
        submitted_at=float(data["submitted_at"]),
        completed_at=data.get("completed_at"),
        total=int(data.get("total", 0)),
        processed=int(data.get("processed", 0)),
        held_skipped=int(data.get("held_skipped", 0)),
        rejected_count=int(data.get("rejected_count", 0)),
        quota_blocked_count=int(data.get("quota_blocked_count", 0)),
        quota_lock_timeout_count=int(data.get("quota_lock_timeout_count", 0)),
        estimated_requests=int(data.get("estimated_requests", 0)),
        lookups_used=int(data.get("lookups_used", 0)),
        use_domain_reports=bool(data.get("use_domain_reports", False)),
        # MDI-57A: legacy recovered jobs missing a saved threshold fall back to
        # the system default (30). Saved thresholds are always preserved.
        stale_threshold_days=int(data.get("stale_threshold_days", 30)),
        auto_rescan_stale=bool(data.get("auto_rescan_stale", False)),
        max_auto_rescans=int(data.get("max_auto_rescans", 3)),
        cloudflare_rank_lookup_enabled=bool(data.get("cloudflare_rank_lookup_enabled", False)),
        input_mode=str(data.get("input_mode", "paste")),
        error_message=data.get("error_message"),
        item_order=list(data.get("item_order") or []),
        results=results,
        usage_history_written=bool(data.get("usage_history_written", False)),
        # MDI-11 enrichment counters — default 0 for jobs persisted before MDI-11
        rdap_enriched_count=int(data.get("rdap_enriched_count", 0)),
        rdap_failed_count=int(data.get("rdap_failed_count", 0)),
        whois_fallback_count=int(data.get("whois_fallback_count", 0)),
        hold_detected_by_enrichment_count=int(data.get("hold_detected_by_enrichment_count", 0)),
        enrichment_skipped_uploaded_hold_count=int(data.get("enrichment_skipped_uploaded_hold_count", 0)),
        # MDI-12 live-check counters — default 0 for jobs persisted before MDI-12
        live_check_count=int(data.get("live_check_count", 0)),
        live_check_skipped_count=int(data.get("live_check_skipped_count", 0)),
        live_check_error_count=int(data.get("live_check_error_count", 0)),
        # MDI-15 action state — default for jobs persisted before MDI-15
        action_in_progress=bool(data.get("action_in_progress", False)),
        last_action_type=data.get("last_action_type"),
        last_action_at=data.get("last_action_at"),
        vt_refresh_count=int(data.get("vt_refresh_count", 0)),
        vt_scan_requested_count=int(data.get("vt_scan_requested_count", 0)),
        vt_scan_failed_count=int(data.get("vt_scan_failed_count", 0)),
        auto_rescan_attempted_count=int(data.get("auto_rescan_attempted_count", 0)),
        auto_rescan_completed_count=int(data.get("auto_rescan_completed_count", 0)),
        auto_rescan_failed_count=int(data.get("auto_rescan_failed_count", 0)),
        auto_rescan_skipped_count=int(data.get("auto_rescan_skipped_count", 0)),
        auto_rescan_quota_blocked_count=int(data.get("auto_rescan_quota_blocked_count", 0)),
    )


def sanitize_terminal_action_state(job: "job_store.InMemoryJob") -> "job_store.InMemoryJob":  # type: ignore[name-defined]
    """
    Clear stale action_in_progress on terminal recovered jobs (MDI-59A).

    A completed job must not remain UI-blocked because a prior refresh/scan
    persisted action_in_progress=true before the in-memory flag was cleared.
    Does not modify queued/running jobs.
    """
    if job.status in _TERMINAL_JOB_STATUSES and job.action_in_progress:
        logger.info(
            "sanitize_terminal_action_state: clearing stale action_in_progress "
            "for terminal job %s (status=%s)",
            job.job_id,
            job.status,
        )
        job.action_in_progress = False
    return job


# ── Write ──────────────────────────────────────────────────────────────────────

async def write_latest_job(
    job: "job_store.InMemoryJob",  # type: ignore[name-defined]
    *,
    job_file: Optional[Path] = None,
) -> None:
    """
    Atomically write the completed job snapshot to mdi_latest_job.json.

    Only writes jobs with status 'done' or 'error'.  Queued/running jobs are
    silently skipped — callers may log this condition if desired.

    Raises on write failure — the caller (job_processor) is responsible for
    catching and logging so that a persistence failure does not corrupt the
    in-memory job result.

    Acquires _PERSISTENCE_LOCK for the duration of the write.
    """
    if job.status not in ("done", "error"):
        logger.debug(
            "write_latest_job: skipping job %s with status %s (not completed).",
            job.job_id, job.status,
        )
        return

    path = job_file or _default_job_file()

    async with _PERSISTENCE_LOCK:
        _write_sync(job, path)


def _write_sync(job: Any, path: Path) -> None:
    """Synchronous body of write_latest_job — called under the persistence lock."""
    data = serialize_job(job)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception:
        # Clean up orphaned tmp file if possible
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


# ── Read ───────────────────────────────────────────────────────────────────────

def read_latest_job(
    *,
    job_file: Optional[Path] = None,
) -> Optional["job_store.InMemoryJob"]:  # type: ignore[name-defined]
    """
    Read and deserialize the latest job snapshot from mdi_latest_job.json.

    Returns None on any failure condition:
      - File missing
      - File empty
      - JSON parse error
      - Schema/validation error
      - Permission error

    Never raises.  All failures are logged at WARNING or ERROR level.
    Never crashes the backend.
    """
    path = job_file or _default_job_file()

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except PermissionError as exc:
        logger.error("read_latest_job: permission denied reading %s: %s", path, exc)
        return None
    except Exception as exc:
        logger.warning("read_latest_job: unexpected error reading %s: %s", path, exc)
        return None

    if not raw.strip():
        logger.warning("read_latest_job: file %s is empty.", path)
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("read_latest_job: corrupt JSON in %s: %s", path, exc)
        return None

    if not isinstance(data, dict):
        logger.warning("read_latest_job: unexpected root type in %s: %s", path, type(data))
        return None

    try:
        job = deserialize_job(data)
        return sanitize_terminal_action_state(job)
    except Exception as exc:
        logger.warning("read_latest_job: schema error deserializing %s: %s", path, exc)
        return None
