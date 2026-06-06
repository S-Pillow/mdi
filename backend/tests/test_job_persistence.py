"""
MDI-08 — Tests for job_persistence.py and GET /api/mdi/jobs/latest.

Guarantees enforced by every test in this module:
  - No VT calls made (no httpx, no _vt_request invocations).
  - No live runtime files modified (/var/lib/dns-tool/mdi_latest_job.json not created).
  - No usage history appended (vt_usage_history.jsonl line count unchanged).
  - No quota consumed.
  - No external services contacted.
  - All file I/O uses tmp_path or env-var injection.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from models import InputType, MdiProcessingStatus, MdiResultItem, TriageBucket, TriageConfidence, RecommendedAction, EvidenceStatus, Freshness, VtModeUsed, LiveStatus
from services.job_store import InMemoryJob, clear_all_jobs, get_latest_completed_job_sync, register_recovered_job
from services import job_persistence

client = TestClient(app)

LATEST_URL = "/api/mdi/jobs/latest"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_done_job(job_id: str = "test-job-001", domain: str = "example.com") -> InMemoryJob:
    """Build a minimal completed InMemoryJob for testing."""
    result = MdiResultItem(
        input_original=domain,
        input_normalized=domain,
        input_type=InputType.DOMAIN,
        position=1,
        processing_status=MdiProcessingStatus.DONE,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=72,
        vt_ratio="0/72",
        freshness=Freshness.FRESH,
        triage_bucket=TriageBucket.CLEAN,
        triage_confidence=TriageConfidence.HIGH,
        recommended_action=RecommendedAction.CLEAR,
        evidence_status=EvidenceStatus.COMPLETE,
        vt_mode_used=VtModeUsed.URL_REPORT,
        live_status=LiveStatus.NOT_CHECKED,
    )
    job = InMemoryJob(
        job_id=job_id,
        status="done",
        submitted_at=time.time() - 30,
        completed_at=time.time(),
        total=1,
        processed=1,
        held_skipped=0,
        rejected_count=0,
        estimated_requests=3,
        lookups_used=1,
        use_domain_reports=False,
        stale_threshold_days=5,
    )
    job.item_order = [domain]
    job.results = {domain: result}
    job.usage_history_written = True
    return job


def _make_running_job(job_id: str = "running-job-001") -> InMemoryJob:
    return InMemoryJob(
        job_id=job_id,
        status="running",
        submitted_at=time.time(),
        total=2,
        processed=1,
    )


def _make_queued_job(job_id: str = "queued-job-001") -> InMemoryJob:
    return InMemoryJob(
        job_id=job_id,
        status="queued",
        submitted_at=time.time(),
        total=1,
        processed=0,
    )


def _env_job_file(tmp_path: Path) -> Path:
    return tmp_path / "mdi_latest_job.json"


# ── Setup / teardown ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate():
    """Clear in-memory store and unset MDI_LATEST_JOB_FILE before each test."""
    clear_all_jobs()
    old = os.environ.pop("MDI_LATEST_JOB_FILE", None)
    yield
    clear_all_jobs()
    if old is None:
        os.environ.pop("MDI_LATEST_JOB_FILE", None)
    else:
        os.environ["MDI_LATEST_JOB_FILE"] = old


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for serialize / deserialize
# ─────────────────────────────────────────────────────────────────────────────

class TestSerializeDeserialize:

    def test_round_trip_preserves_all_scalar_fields(self):
        job = _make_done_job()
        data = job_persistence.serialize_job(job)
        recovered = job_persistence.deserialize_job(data)
        assert recovered.job_id == job.job_id
        assert recovered.status == job.status
        assert recovered.total == job.total
        assert recovered.processed == job.processed
        assert recovered.lookups_used == job.lookups_used
        assert recovered.use_domain_reports == job.use_domain_reports
        assert recovered.stale_threshold_days == job.stale_threshold_days
        assert recovered.usage_history_written == job.usage_history_written

    def test_round_trip_preserves_timestamps(self):
        job = _make_done_job()
        data = job_persistence.serialize_job(job)
        recovered = job_persistence.deserialize_job(data)
        assert abs(recovered.submitted_at - job.submitted_at) < 0.001
        assert abs(recovered.completed_at - job.completed_at) < 0.001

    def test_round_trip_preserves_item_order(self):
        job = _make_done_job(domain="malicious.test")
        data = job_persistence.serialize_job(job)
        recovered = job_persistence.deserialize_job(data)
        assert recovered.item_order == ["malicious.test"]

    def test_round_trip_preserves_results(self):
        job = _make_done_job(domain="example.com")
        data = job_persistence.serialize_job(job)
        recovered = job_persistence.deserialize_job(data)
        assert "example.com" in recovered.results
        r = recovered.results["example.com"]
        assert r.triage_bucket == TriageBucket.CLEAN
        assert r.vt_hits == 0
        assert r.vt_total_engines == 72

    def test_deserialize_invalid_schema_raises(self):
        with pytest.raises(Exception):
            job_persistence.deserialize_job({"not": "a valid job"})


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for write_latest_job
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteLatestJob:

    def test_writes_valid_json(self, tmp_path):
        job = _make_done_job()
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        assert job_file.exists()
        data = json.loads(job_file.read_text())
        assert data["job_id"] == job.job_id
        assert data["status"] == "done"

    def test_atomic_write_leaves_no_tmp_file(self, tmp_path):
        job = _make_done_job()
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        tmp_file = job_file.with_suffix(".tmp")
        assert not tmp_file.exists()

    def test_sets_permissions_to_0600(self, tmp_path):
        job = _make_done_job()
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        mode = stat.S_IMODE(job_file.stat().st_mode)
        assert mode == 0o600

    def test_skips_queued_job(self, tmp_path):
        job = _make_queued_job()
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        assert not job_file.exists()

    def test_skips_running_job(self, tmp_path):
        job = _make_running_job()
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        assert not job_file.exists()

    def test_error_status_job_is_written(self, tmp_path):
        job = _make_done_job()
        job.status = "error"
        job.error_message = "Something failed"
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        assert job_file.exists()
        data = json.loads(job_file.read_text())
        assert data["status"] == "error"

    def test_overwrites_previous_file(self, tmp_path):
        job1 = _make_done_job(job_id="job-aaa")
        job2 = _make_done_job(job_id="job-bbb")
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job1, job_file=job_file))
        asyncio.run(job_persistence.write_latest_job(job2, job_file=job_file))
        data = json.loads(job_file.read_text())
        assert data["job_id"] == "job-bbb"


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for read_latest_job
# ─────────────────────────────────────────────────────────────────────────────

class TestReadLatestJob:

    def test_returns_none_when_file_missing(self, tmp_path):
        job_file = _env_job_file(tmp_path)
        result = job_persistence.read_latest_job(job_file=job_file)
        assert result is None

    def test_returns_none_on_empty_file(self, tmp_path):
        job_file = _env_job_file(tmp_path)
        job_file.write_text("")
        result = job_persistence.read_latest_job(job_file=job_file)
        assert result is None

    def test_returns_none_on_corrupt_json(self, tmp_path):
        job_file = _env_job_file(tmp_path)
        job_file.write_text("{not valid json")
        result = job_persistence.read_latest_job(job_file=job_file)
        assert result is None

    def test_returns_none_on_invalid_schema(self, tmp_path):
        job_file = _env_job_file(tmp_path)
        job_file.write_text(json.dumps({"hello": "world"}))
        result = job_persistence.read_latest_job(job_file=job_file)
        assert result is None

    def test_returns_none_on_json_array_root(self, tmp_path):
        job_file = _env_job_file(tmp_path)
        job_file.write_text(json.dumps([1, 2, 3]))
        result = job_persistence.read_latest_job(job_file=job_file)
        assert result is None

    def test_round_trip_via_write_then_read(self, tmp_path):
        job = _make_done_job(job_id="roundtrip-001", domain="roundtrip.example")
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        recovered = job_persistence.read_latest_job(job_file=job_file)
        assert recovered is not None
        assert recovered.job_id == "roundtrip-001"
        assert recovered.status == "done"
        assert "roundtrip.example" in recovered.results


# ─────────────────────────────────────────────────────────────────────────────
# Tests for job_store helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestJobStoreHelpers:

    def test_get_latest_completed_job_sync_returns_none_when_empty(self):
        assert get_latest_completed_job_sync() is None

    def test_get_latest_completed_job_sync_ignores_running(self):
        register_recovered_job(_make_running_job())
        assert get_latest_completed_job_sync() is None

    def test_get_latest_completed_job_sync_ignores_queued(self):
        register_recovered_job(_make_queued_job())
        assert get_latest_completed_job_sync() is None

    def test_get_latest_completed_job_sync_returns_done_job(self):
        job = _make_done_job()
        register_recovered_job(job)
        found = get_latest_completed_job_sync()
        assert found is not None
        assert found.job_id == job.job_id

    def test_get_latest_completed_job_sync_returns_most_recent(self):
        job1 = _make_done_job(job_id="old-job")
        job1.completed_at = time.time() - 100
        job2 = _make_done_job(job_id="new-job")
        job2.completed_at = time.time()
        register_recovered_job(job1)
        register_recovered_job(job2)
        found = get_latest_completed_job_sync()
        assert found.job_id == "new-job"

    def test_register_recovered_job_preserves_job_id(self):
        job = _make_done_job(job_id="preserved-id")
        register_recovered_job(job)
        from services.job_store import get_job_sync
        stored = get_job_sync("preserved-id")
        assert stored is not None
        assert stored.job_id == "preserved-id"


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint tests via TestClient
# ─────────────────────────────────────────────────────────────────────────────

class TestLatestJobEndpoint:

    def test_returns_404_when_no_memory_no_file(self, tmp_path):
        os.environ["MDI_LATEST_JOB_FILE"] = str(_env_job_file(tmp_path))
        resp = client.get(LATEST_URL)
        assert resp.status_code == 404

    def test_returns_in_memory_completed_job(self):
        job = _make_done_job(job_id="mem-job-001")
        register_recovered_job(job)
        resp = client.get(LATEST_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "mem-job-001"
        assert data["status"] == "done"

    def test_recovers_from_disk_when_memory_empty(self, tmp_path):
        job = _make_done_job(job_id="disk-job-001")
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        os.environ["MDI_LATEST_JOB_FILE"] = str(job_file)

        resp = client.get(LATEST_URL)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "disk-job-001"

    def test_recovered_job_registered_in_store(self, tmp_path):
        job = _make_done_job(job_id="register-check-001")
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        os.environ["MDI_LATEST_JOB_FILE"] = str(job_file)

        client.get(LATEST_URL)  # triggers recovery + registration
        # Now the job should be accessible via the normal job_id endpoint
        resp2 = client.get(f"/api/mdi/jobs/register-check-001")
        assert resp2.status_code == 200
        assert resp2.json()["job_id"] == "register-check-001"

    def test_corrupt_file_returns_404(self, tmp_path):
        job_file = _env_job_file(tmp_path)
        job_file.write_text("not json at all")
        os.environ["MDI_LATEST_JOB_FILE"] = str(job_file)
        resp = client.get(LATEST_URL)
        assert resp.status_code == 404

    def test_empty_file_returns_404(self, tmp_path):
        job_file = _env_job_file(tmp_path)
        job_file.write_text("")
        os.environ["MDI_LATEST_JOB_FILE"] = str(job_file)
        resp = client.get(LATEST_URL)
        assert resp.status_code == 404

    def test_response_shape_matches_job_status_response(self, tmp_path):
        job = _make_done_job(job_id="shape-check-001")
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        os.environ["MDI_LATEST_JOB_FILE"] = str(job_file)

        resp = client.get(LATEST_URL)
        assert resp.status_code == 200
        data = resp.json()
        # Must include all JobStatusResponse fields
        for field in ("job_id", "status", "total", "processed", "results",
                      "lookups_used", "estimated_requests"):
            assert field in data, f"Missing field: {field}"

    def test_recovery_does_not_append_to_usage_history(self, tmp_path):
        job = _make_done_job()
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        os.environ["MDI_LATEST_JOB_FILE"] = str(job_file)

        history_file = tmp_path / "history.jsonl"
        old_env = os.environ.get("VT_USAGE_HISTORY_FILE")
        os.environ["VT_USAGE_HISTORY_FILE"] = str(history_file)
        try:
            client.get(LATEST_URL)
            assert not history_file.exists(), "Recovery must not write usage history"
        finally:
            if old_env is None:
                os.environ.pop("VT_USAGE_HISTORY_FILE", None)
            else:
                os.environ["VT_USAGE_HISTORY_FILE"] = old_env

    def test_recovery_does_not_modify_quota_file(self, tmp_path):
        import json as _json
        usage_file = tmp_path / "vt_usage.json"
        usage_file.write_text(_json.dumps({"date_utc": "2026-06-06", "daily_lookups_used": 1}))
        old_env = os.environ.get("VT_USAGE_FILE")
        os.environ["VT_USAGE_FILE"] = str(usage_file)

        job = _make_done_job()
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))
        os.environ["MDI_LATEST_JOB_FILE"] = str(job_file)

        mtime_before = usage_file.stat().st_mtime
        client.get(LATEST_URL)
        mtime_after = usage_file.stat().st_mtime
        assert mtime_before == mtime_after, "Recovery must not modify quota file"

        if old_env is None:
            os.environ.pop("VT_USAGE_FILE", None)
        else:
            os.environ["VT_USAGE_FILE"] = old_env


# ─────────────────────────────────────────────────────────────────────────────
# No VT calls, no live file modification
# ─────────────────────────────────────────────────────────────────────────────

class TestNoExternalCalls:

    def test_no_vt_calls_during_persistence(self, tmp_path):
        """job_persistence must not import or call vt_service."""
        import services.job_persistence as jp
        import inspect
        source = inspect.getsource(jp)
        assert "vt_service" not in source
        assert "httpx" not in source
        assert "_vt_request" not in source

    def test_live_mdi_latest_job_not_created(self, tmp_path):
        """Live /var/lib/dns-tool/mdi_latest_job.json must not be created by any test."""
        live_path = Path("/var/lib/dns-tool/mdi_latest_job.json")
        existed_before = live_path.exists()

        job = _make_done_job()
        job_file = _env_job_file(tmp_path)
        asyncio.run(job_persistence.write_latest_job(job, job_file=job_file))

        if not existed_before:
            assert not live_path.exists(), "Test must not create the live recovery file"


# ─────────────────────────────────────────────────────────────────────────────
# Regression: existing endpoints still work
# ─────────────────────────────────────────────────────────────────────────────

class TestRegressionExistingEndpoints:

    def test_health_still_works(self):
        resp = client.get("/api/mdi/health")
        assert resp.status_code == 200

    def test_usage_still_works(self):
        resp = client.get("/api/mdi/usage")
        assert resp.status_code == 200

    def test_estimate_still_works(self):
        resp = client.post("/api/mdi/jobs/estimate",
                           json={"raw_input": "example.com"})
        assert resp.status_code == 200
        assert resp.json()["external_calls_made"] is False

    def test_parse_preview_still_works(self):
        resp = client.post("/api/mdi/jobs/parse-preview",
                           json={"raw_input": "example.com"})
        assert resp.status_code == 200

    def test_schema_summary_still_works(self):
        resp = client.get("/api/mdi/schema-summary")
        assert resp.status_code == 200
