"""
MDI in-memory job store.

Stores InMemoryJob instances in a process-local dict protected by asyncio.Lock.
Jobs are NOT persisted to disk by this module.  Disk persistence is handled by
job_persistence.py which writes the latest completed job to mdi_latest_job.json.
On service restart the in-memory store is empty; the recovery endpoint reads
mdi_latest_job.json and re-registers the job here via register_recovered_job().

Usage from async context:
    job = InMemoryJob(job_id=..., ...)
    await create_job(job)
    ...
    job = await get_job(job_id)

Usage in tests (synchronous):
    job = get_job_sync(job_id)   # bypasses the lock; safe for single-threaded tests
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from models import MdiResultItem


@dataclass
class InMemoryJob:
    """Mutable in-memory job state. Not a Pydantic model — must be freely mutable."""
    job_id: str
    status: str                       # "queued" | "running" | "done" | "error"
    submitted_at: float               # time.time()
    completed_at: Optional[float] = None
    total: int = 0                    # eligible VT-queue items
    processed: int = 0                # items where VT attempt finished
    held_skipped: int = 0             # items skipped because of hold
    rejected_count: int = 0           # parse-rejected items
    quota_blocked_count: int = 0      # items blocked mid-run by quota exhaustion
    quota_lock_timeout_count: int = 0  # items skipped due to shared quota lock timeout
    estimated_requests: int = 0       # pre-submit conservative estimate
    lookups_used: int = 0             # actual VT API calls consumed
    use_domain_reports: bool = False
    stale_threshold_days: int = 30
    auto_rescan_stale: bool = False
    max_auto_rescans: int = 3
    cloudflare_rank_lookup_enabled: bool = False
    input_mode: str = "paste"
    error_message: Optional[str] = None
    item_order: List[str] = field(default_factory=list)  # input_normalized, in submission order
    results: Dict[str, MdiResultItem] = field(default_factory=dict)
    usage_history_written: bool = False
    # ── MDI-11 enrichment counters (metadata-only — counts, no raw domain values) ──
    rdap_enriched_count: int = 0
    rdap_failed_count: int = 0
    whois_fallback_count: int = 0
    hold_detected_by_enrichment_count: int = 0
    enrichment_skipped_uploaded_hold_count: int = 0
    # ── MDI-12 live-check counters (metadata-only — counts only, no URLs or IPs) ──
    live_check_count: int = 0           # items that received a live check
    live_check_skipped_count: int = 0   # items skipped (clean, held, error, no VT data)
    live_check_error_count: int = 0     # items where live check returned an error
    # ── MDI-15 job action state ────────────────────────────────────────────────
    action_in_progress: bool = False
    last_action_type: Optional[str] = None
    last_action_at: Optional[float] = None
    vt_refresh_count: int = 0
    vt_scan_requested_count: int = 0
    vt_scan_failed_count: int = 0
    # ── MDI-15A auto-rescan (initial job processing only) ─────────────────────
    auto_rescan_attempted_count: int = 0
    auto_rescan_completed_count: int = 0
    auto_rescan_failed_count: int = 0
    auto_rescan_skipped_count: int = 0
    auto_rescan_quota_blocked_count: int = 0
    auto_rescanned_items: Set[str] = field(default_factory=set)


# ── Store ──────────────────────────────────────────────────────────────────────

_JOBS: Dict[str, InMemoryJob] = {}
_STORE_LOCK = asyncio.Lock()


async def create_job(job: InMemoryJob) -> None:
    """Register a new job in the store."""
    async with _STORE_LOCK:
        _JOBS[job.job_id] = job


async def get_job(job_id: str) -> Optional[InMemoryJob]:
    """Retrieve a job by ID; returns None if not found."""
    async with _STORE_LOCK:
        return _JOBS.get(job_id)


def get_job_sync(job_id: str) -> Optional[InMemoryJob]:
    """
    Synchronous dict lookup — safe for single-threaded tests only.
    Do not call from concurrent async contexts; use get_job() instead.
    """
    return _JOBS.get(job_id)


def get_latest_completed_job_sync() -> Optional[InMemoryJob]:
    """
    Return the most recently completed (done/error) job from the store, or None.

    Synchronous — safe for single-threaded use and endpoint handlers.
    Returns None if no completed job exists.  Never returns queued/running jobs.
    """
    completed = [
        j for j in _JOBS.values()
        if j.status in ("done", "error") and j.completed_at is not None
    ]
    if not completed:
        return None
    return max(completed, key=lambda j: j.completed_at)  # type: ignore[return-value]


def register_recovered_job(job: InMemoryJob) -> None:
    """
    Insert a job recovered from disk back into the store using its original job_id.

    Preserves all original fields: job_id, status, results, counts, timestamps.
    Safe to call from synchronous endpoint handlers.
    """
    _JOBS[job.job_id] = job


def clear_all_jobs() -> None:
    """Clear the entire store. For test isolation only."""
    _JOBS.clear()
