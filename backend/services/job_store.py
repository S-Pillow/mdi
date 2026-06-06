"""
MDI in-memory job store.

Stores InMemoryJob instances in a process-local dict protected by asyncio.Lock.
Jobs are NOT persisted to disk. On service restart, all in-flight and completed
jobs are lost. This is a documented MDI-06 limitation; job recovery is out of scope.

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
from typing import Dict, List, Optional

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
    quota_blocked_count: int = 0      # items blocked mid-run by quota
    estimated_requests: int = 0       # pre-submit conservative estimate
    lookups_used: int = 0             # actual VT API calls consumed
    use_domain_reports: bool = False
    stale_threshold_days: int = 5
    error_message: Optional[str] = None
    item_order: List[str] = field(default_factory=list)  # input_normalized, in submission order
    results: Dict[str, MdiResultItem] = field(default_factory=dict)
    usage_history_written: bool = False


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


def clear_all_jobs() -> None:
    """Clear the entire store. For test isolation only."""
    _JOBS.clear()
