"""
MDI-59 — Progress-phase UX tests.

Guarantees:
  - All file I/O uses tmp_path / explicit file= kwargs.
  - No /var/lib/dns-tool access.
  - No VT quota consumed (VT HTTP mocked).
  - No live Cloudflare / RDAP / WHOIS / DNS / live-check calls.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    AgeBucket,
    Freshness,
    InputType,
    JobActionRequest,
    JobStatusResponse,
    LiveStatus,
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
    RecommendedAction,
    RefreshScanScope,
    TriageBucket,
    VtModeUsed,
)
from routers.mdi import _build_job_status_response
from services import cloudflare_radar, job_actions, job_persistence, job_processor, job_store
from services.job_actions import ActionStats
from services.job_store import InMemoryJob, clear_all_jobs, register_recovered_job


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    clear_all_jobs()
    monkeypatch.setenv("MDI_LATEST_JOB_FILE", str(tmp_path / "mdi_latest_job.json"))
    monkeypatch.setenv("VT_USAGE_FILE", str(tmp_path / "vt_usage.json"))
    monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(tmp_path / "vt_usage_history.jsonl"))
    monkeypatch.setenv("VT_DAILY_HISTORY_FILE", str(tmp_path / "vt_daily_history.jsonl"))
    (tmp_path / "vt_usage.json").write_text(
        '{"date_utc": "2099-01-01", "daily_lookups_used": 0}'
    )
    yield
    clear_all_jobs()


def _make_queued_job(
    job_id: str,
    items: list,
    *,
    cloudflare_rank_lookup_enabled: bool = False,
) -> InMemoryJob:
    job = InMemoryJob(
        job_id=job_id,
        status="queued",
        submitted_at=time.time(),
        total=len(items),
        use_domain_reports=True,
        stale_threshold_days=30,
        cloudflare_rank_lookup_enabled=cloudflare_rank_lookup_enabled,
    )
    for pos, (normalized, original, itype) in enumerate(items, start=1):
        job.results[normalized] = MdiResultItem(
            input_original=original,
            input_normalized=normalized,
            input_type=itype,
            position=pos,
            processing_status=MdiProcessingStatus.PENDING,
        )
        job.item_order.append(normalized)
    _run(job_store.create_job(job))
    return job


def _make_done_result(
    normalized: str,
    *,
    position: int = 1,
    input_type: InputType = InputType.DOMAIN,
    freshness=Freshness.STALE,
    vt_hits: int = 1,
) -> MdiResultItem:
    return MdiResultItem(
        input_original=normalized,
        input_normalized=normalized,
        input_type=input_type,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        vt_mode_used=VtModeUsed.DOMAIN_REPORT if input_type == InputType.DOMAIN else VtModeUsed.URL_REPORT,
        vt_hits=vt_hits,
        vt_suspicious=0,
        vt_total_engines=75,
        vt_ratio=f"{vt_hits}/75",
        vt_scan_date="2026-01-01T00:00:00Z",
        freshness=freshness,
        triage_bucket=TriageBucket.MALICIOUS if vt_hits else TriageBucket.CLEAN,
        live_status=LiveStatus.NOT_CHECKED,
        age_bucket=AgeBucket.MATURE,
        recommended_action=RecommendedAction.REFRESH_REPORT,
    )


def _make_pending_url(normalized: str = "https://pending.example/path", *, position: int = 1) -> MdiResultItem:
    return MdiResultItem(
        input_original=normalized,
        input_normalized=normalized,
        input_type=InputType.URL,
        position=position,
        processing_status=MdiProcessingStatus.DONE,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=0,
        vt_ratio="",
        vt_scan_date=None,
        freshness=Freshness.NEVER_SCANNED,
        triage_bucket=TriageBucket.PENDING,
        recommended_action=RecommendedAction.REFRESH_REPORT,
        live_status=LiveStatus.NOT_CHECKED,
        age_bucket=AgeBucket.UNKNOWN,
        errors=[MdiError(
            code="vt_scan_pending",
            message="VT analysis pending.",
            source="vt_service",
            retriable=True,
            severity="warning",
            blocks_triage=False,
        )],
    )


def _make_done_job(items: list[MdiResultItem], *, job_id: str = "mdi59-job") -> InMemoryJob:
    job = InMemoryJob(
        job_id=job_id,
        status="done",
        submitted_at=time.time() - 100,
        completed_at=time.time() - 50,
        total=len(items),
        processed=len(items),
    )
    for item in items:
        job.results[item.input_normalized] = item
        job.item_order.append(item.input_normalized)
    return job


def _ok_stats() -> ActionStats:
    return ActionStats(items_attempted=1, items_completed=1, quota_units=1)


# ── Defaults / schema ─────────────────────────────────────────────────────────


def test_current_phase_defaults_null_on_new_job():
    job = InMemoryJob(job_id="phase-default", status="queued", submitted_at=time.time())
    assert job.current_phase is None
    assert job.current_phase_detail is None


def test_job_status_response_phase_fields_optional_null():
    resp = JobStatusResponse(
        job_id="schema-phase",
        status="done",
        submitted_at=1.0,
        total=0,
        processed=0,
        held_skipped=0,
        rejected_count=0,
        queued=0,
        estimated_requests=0,
        lookups_used=0,
        quota_blocked_count=0,
        use_domain_reports=True,
        stale_threshold_days=30,
    )
    assert resp.current_phase is None
    assert resp.current_phase_detail is None
    dumped = resp.model_dump()
    assert dumped["current_phase"] is None
    assert dumped["current_phase_detail"] is None


# ── Initial job phase transitions ─────────────────────────────────────────────


def test_process_job_phase_transitions_and_clears(tmp_path):
    job_id = "mdi59-phases"
    _make_queued_job(job_id, [("phase.example.com", "phase.example.com", InputType.DOMAIN)])
    seen: List[Optional[str]] = []

    async def enrich_wrap(job):
        seen.append(job.current_phase)
        return None

    async def run_wrap(job, usage_file=None):
        seen.append(job.current_phase)
        job.processed = job.total
        for key, result in list(job.results.items()):
            job.results[key] = result.model_copy(update={
                "processing_status": MdiProcessingStatus.DONE,
                "vt_hits": 0,
                "vt_total_engines": 70,
                "triage_bucket": TriageBucket.CLEAN,
            })
        return None

    async def live_wrap(job):
        seen.append(job.current_phase)
        assert job.processed == job.total
        assert job.status == "running"
        return None

    async def cf_wrap(job):
        # Cloudflare disabled → must not flip to checking_cloudflare_rank
        seen.append(job.current_phase)
        return None

    def finalize_wrap(job):
        seen.append(job.current_phase)
        return None

    with patch.object(job_processor, "_enrich_items", new=enrich_wrap), \
         patch.object(job_processor, "_run_items", new=run_wrap), \
         patch.object(job_processor, "_live_check_items", new=live_wrap), \
         patch.object(job_processor, "_cloudflare_rank_items", new=cf_wrap), \
         patch.object(job_processor, "_apply_hold_impact_guidance", new=finalize_wrap):
        _run(job_processor.process_job(
            job_id,
            usage_file=tmp_path / "u.json",
            job_file=tmp_path / "mdi_latest_job.json",
        ))

    job = job_store.get_job_sync(job_id)
    assert job.status == "done"
    assert job.current_phase is None
    assert job.current_phase_detail is None
    assert seen == [
        "enriching",
        "checking_virustotal",
        "checking_live_site",
        "checking_live_site",  # CF skipped; phase unchanged until finalizing
        "finalizing",
    ]


def test_process_job_sets_cloudflare_phase_when_pass_runs(tmp_path):
    job_id = "mdi59-cf-phase"
    _make_queued_job(
        job_id,
        [("cf.example.com", "cf.example.com", InputType.DOMAIN)],
        cloudflare_rank_lookup_enabled=True,
    )
    phases: List[str] = []

    async def enrich_wrap(job):
        phases.append(job.current_phase)
        return None

    async def run_wrap(job, usage_file=None):
        phases.append(job.current_phase)
        job.processed = job.total
        for key, result in list(job.results.items()):
            job.results[key] = result.model_copy(update={
                "processing_status": MdiProcessingStatus.DONE,
                "vt_hits": 2,
                "vt_total_engines": 70,
                "triage_bucket": TriageBucket.MALICIOUS,
            })
        return None

    async def live_wrap(job):
        phases.append(job.current_phase)
        return None

    async def cf_wrap(job):
        assert job.cloudflare_rank_lookup_enabled
        job.current_phase = "checking_cloudflare_rank"
        phases.append(job.current_phase)
        return None

    def finalize_wrap(job):
        phases.append(job.current_phase)
        return None

    with patch.object(job_processor, "_enrich_items", new=enrich_wrap), \
         patch.object(job_processor, "_run_items", new=run_wrap), \
         patch.object(job_processor, "_live_check_items", new=live_wrap), \
         patch.object(job_processor, "_cloudflare_rank_items", new=cf_wrap), \
         patch.object(job_processor, "_apply_hold_impact_guidance", new=finalize_wrap):
        _run(job_processor.process_job(
            job_id,
            usage_file=tmp_path / "u.json",
            job_file=tmp_path / "mdi_latest_job.json",
        ))

    job = job_store.get_job_sync(job_id)
    assert job.status == "done"
    assert job.current_phase is None
    assert phases == [
        "enriching",
        "checking_virustotal",
        "checking_live_site",
        "checking_cloudflare_rank",
        "finalizing",
    ]


def test_cloudflare_rank_items_sets_phase_only_when_running():
    job = InMemoryJob(
        job_id="cf-only",
        status="running",
        submitted_at=time.time(),
        cloudflare_rank_lookup_enabled=True,
        item_order=["example.com"],
        results={
            "example.com": MdiResultItem(
                input_original="example.com",
                input_normalized="example.com",
                input_type=InputType.DOMAIN,
                position=1,
                processing_status=MdiProcessingStatus.DONE,
                vt_total_engines=70,
            ),
        },
    )
    job.current_phase = "checking_live_site"

    async def _req(domain, token):
        return 200, {
            "success": True,
            "errors": [],
            "result": {
                "details_0": {"rank": 10, "bucket": "200"},
                "meta": {"dateRange": [{"startTime": "t0", "endTime": "t1"}]},
            },
        }

    with patch.dict(os.environ, {"CLOUDFLARE_RADAR_API_TOKEN": "tok"}), \
         patch.object(cloudflare_radar, "_default_request", _req):
        _run(job_processor._cloudflare_rank_items(job))

    assert job.current_phase == "checking_cloudflare_rank"


def test_cloudflare_rank_items_skips_phase_when_disabled():
    job = InMemoryJob(
        job_id="cf-off",
        status="running",
        submitted_at=time.time(),
        cloudflare_rank_lookup_enabled=False,
        item_order=["example.com"],
        results={
            "example.com": MdiResultItem(
                input_original="example.com",
                input_normalized="example.com",
                input_type=InputType.DOMAIN,
                position=1,
                processing_status=MdiProcessingStatus.DONE,
            ),
        },
    )
    job.current_phase = "checking_live_site"
    _run(job_processor._cloudflare_rank_items(job))
    assert job.current_phase == "checking_live_site"


def test_process_job_error_clears_phase(tmp_path):
    job_id = "mdi59-error-phase"
    _make_queued_job(job_id, [("err.example.com", "err.example.com", InputType.DOMAIN)])

    async def boom(job):
        assert job.current_phase == "enriching"
        raise RuntimeError("forced failure")

    with patch.object(job_processor, "_enrich_items", new=boom):
        _run(job_processor.process_job(
            job_id,
            usage_file=tmp_path / "u.json",
            job_file=tmp_path / "mdi_latest_job.json",
        ))

    job = job_store.get_job_sync(job_id)
    assert job.status == "error"
    assert job.current_phase is None
    assert job.current_phase_detail is None


# ── Manual action phases ──────────────────────────────────────────────────────


def test_refresh_selected_sets_refresh_report_phase(tmp_path):
    item = _make_done_result("refresh-ok.example")
    job = _make_done_job([item])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])
    seen: List[Optional[str]] = []

    async def capture_run(job_obj, eligible, action, **kwargs):
        seen.append(job_obj.current_phase)
        assert job_obj.action_in_progress is True
        return _ok_stats()

    with patch.object(job_actions, "_run_items", new=capture_run):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    assert seen == ["refresh_report"]
    assert job.action_in_progress is False
    assert job.current_phase is None
    assert job.last_action_type == "refresh"


def test_refresh_pending_sets_refresh_pending_phase(tmp_path):
    item = _make_pending_url()
    job = _make_done_job([item])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.PENDING)
    seen: List[Optional[str]] = []

    async def capture_run(job_obj, eligible, action, **kwargs):
        seen.append(job_obj.current_phase)
        return _ok_stats()

    with patch.object(job_actions, "_run_items", new=capture_run):
        _run(job_actions.run_refresh_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    assert seen == ["refresh_pending"]
    assert job.action_in_progress is False
    assert job.current_phase is None
    assert job.last_action_type == "refresh"


def test_scan_selected_sets_request_new_scan_phase(tmp_path):
    item = _make_done_result("scan-ok.example")
    job = _make_done_job([item])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1], confirm=True)
    seen: List[Optional[str]] = []

    async def capture_run(job_obj, eligible, action, **kwargs):
        seen.append(job_obj.current_phase)
        return _ok_stats()

    with patch.object(job_actions, "_run_items", new=capture_run):
        _run(job_actions.run_scan_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    assert seen == ["request_new_scan"]
    assert job.action_in_progress is False
    assert job.current_phase is None
    assert job.last_action_type == "scan"


def test_scan_stale_sets_rescan_stale_phase(tmp_path):
    item = _make_done_result("stale-ok.example", freshness=Freshness.STALE, vt_hits=2)
    job = _make_done_job([item])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.STALE, confirm=True)
    seen: List[Optional[str]] = []

    async def capture_run(job_obj, eligible, action, **kwargs):
        seen.append(job_obj.current_phase)
        return _ok_stats()

    with patch.object(job_actions, "_run_items", new=capture_run):
        _run(job_actions.run_scan_action(
            job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
        ))

    assert seen == ["rescan_stale"]
    assert job.current_phase is None
    assert job.last_action_type == "scan"


def test_action_phase_clears_on_failure(tmp_path):
    item = _make_done_result("refresh-fail.example")
    job = _make_done_job([item])
    register_recovered_job(job)
    req = JobActionRequest(scope=RefreshScanScope.SELECTED, positions=[1])

    async def boom(*args, **kwargs):
        raise RuntimeError("action boom")

    with patch.object(job_actions, "_run_items", new=boom):
        with pytest.raises(RuntimeError):
            _run(job_actions.run_refresh_action(
                job.job_id, req, usage_file=tmp_path / "u.json", job_file=tmp_path / "j.json",
            ))

    assert job.action_in_progress is False
    assert job.current_phase is None


# ── Persistence / recovery ────────────────────────────────────────────────────


def test_sanitize_terminal_clears_stale_phase():
    job = _make_done_job([_make_done_result("stale-phase.example")])
    job.current_phase = "refresh_pending"
    job.current_phase_detail = "should clear"
    job.action_in_progress = False
    sanitized = job_persistence.sanitize_terminal_action_state(job)
    assert sanitized.current_phase is None
    assert sanitized.current_phase_detail is None


def test_sanitize_terminal_clears_phase_with_stale_action_flag():
    job = _make_done_job([_make_done_result("stale-both.example")])
    job.current_phase = "checking_virustotal"
    job.action_in_progress = True
    sanitized = job_persistence.sanitize_terminal_action_state(job)
    assert sanitized.action_in_progress is False
    assert sanitized.current_phase is None


def test_sanitize_running_keeps_phase():
    job = _make_done_job([_make_done_result("running-phase.example")])
    job.status = "running"
    job.completed_at = None
    job.current_phase = "enriching"
    job.action_in_progress = False
    unchanged = job_persistence.sanitize_terminal_action_state(job)
    assert unchanged.current_phase == "enriching"


def test_phase_not_persisted_in_serialized_job(tmp_path):
    """v1 keeps phase in-memory only; recovered jobs get null phase."""
    job = _make_done_job([_make_done_result("persist.example")])
    job.current_phase = "finalizing"
    data = job_persistence.serialize_job(job)
    assert "current_phase" not in data
    job_file = tmp_path / "mdi_latest_job.json"
    _run(job_persistence.write_latest_job(job, job_file=job_file))
    recovered = job_persistence.read_latest_job(job_file=job_file)
    assert recovered is not None
    assert recovered.current_phase is None


def test_router_status_includes_phase_fields():
    job = _make_done_job([_make_done_result("api.example")])
    job.current_phase = None
    resp = _build_job_status_response(job)
    assert resp.current_phase is None
    assert resp.current_phase_detail is None

    job.status = "running"
    job.current_phase = "enriching"
    resp2 = _build_job_status_response(job)
    assert resp2.current_phase == "enriching"
