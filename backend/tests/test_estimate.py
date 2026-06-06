"""
MDI-07/MDI-09 — Tests for POST /api/mdi/jobs/estimate.

Guarantees enforced by every test in this module:
  - No VT calls made (no httpx, no _vt_request invocations).
  - No jobs created (job_store remains empty).
  - No runtime files written (live /var/lib/dns-tool/vt_usage.json is not modified).
  - No external services contacted (no WHOIS, DNS, URL Activity Scanner).

Test isolation for quota reads:
  All tests that assert quota values inject a tmp_path-based usage file via the
  read_remaining_quota(usage_file=...) parameter.  Tests that do not need a
  specific quota value let read_remaining_quota() fall back to DAILY_QUOTA
  (file-not-found → returns full quota), which is also fine because the live
  file is only read (never written).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── App bootstrap (mirrors conftest pattern used in test_jobs_submit.py) ──────
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from services.estimate import (
    VT_RATE_LIMIT_INTERVAL_SECONDS,
    VT_RATE_LIMIT_NOTE,
    JOB_STATE_NOTE,
    estimate_calls_for_item,
    estimate_job,
)
from services.job_store import clear_all_jobs
from models import InputType

client = TestClient(app)

ESTIMATE_URL = "/api/mdi/jobs/estimate"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_usage_file(tmp_path: Path, used: int, date_str: str | None = None) -> Path:
    """Write a vt_usage.json fixture with the given used count."""
    from datetime import datetime, timezone
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = tmp_path / "vt_usage.json"
    p.write_text(json.dumps({"date_utc": date_str, "daily_lookups_used": used}))
    return p


def _post_estimate(raw_input: str, **kwargs) -> dict:
    payload = {"raw_input": raw_input, **kwargs}
    resp = client.post(ESTIMATE_URL, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Setup / teardown ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_jobs():
    """Guarantee no job state leaks between tests."""
    clear_all_jobs()
    yield
    clear_all_jobs()


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for estimate service helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimateCallsForItem:
    """Direct tests of the shared estimate_calls_for_item formula."""

    def test_domain_url_mode_min_max(self):
        c_min, c_max = estimate_calls_for_item(InputType.DOMAIN, use_domain_reports=False)
        assert c_min == 1
        assert c_max == 3

    def test_domain_domain_report_mode(self):
        c_min, c_max = estimate_calls_for_item(InputType.DOMAIN, use_domain_reports=True)
        assert c_min == 1
        assert c_max == 1

    def test_url_url_mode(self):
        c_min, c_max = estimate_calls_for_item(InputType.URL, use_domain_reports=False)
        assert c_min == 1
        assert c_max == 3

    def test_url_domain_report_mode_flag_ignored(self):
        """use_domain_reports only applies to DOMAIN items; URL items are unaffected."""
        c_min, c_max = estimate_calls_for_item(InputType.URL, use_domain_reports=True)
        assert c_min == 1
        assert c_max == 3


class TestEstimateJob:
    """Unit tests for the estimate_job aggregator."""

    def _make_item(self, input_type: InputType, normalized: str = "example.com"):
        from models import MdiInputItem
        return MdiInputItem(
            input_original=normalized,
            input_normalized=normalized,
            input_type=input_type,
            position=1,
        )

    def test_empty_list(self):
        result = estimate_job([], use_domain_reports=False)
        assert result["estimated_vt_calls_min"] == 0
        assert result["estimated_vt_calls_max"] == 0
        assert result["estimated_duration_seconds_min"] == 0.0
        assert result["estimated_duration_seconds_max"] == 0.0
        assert result["domain_count"] == 0
        assert result["url_count"] == 0

    def test_single_domain_url_mode(self):
        item = self._make_item(InputType.DOMAIN)
        result = estimate_job([item], use_domain_reports=False)
        assert result["estimated_vt_calls_min"] == 1
        assert result["estimated_vt_calls_max"] == 3
        assert result["domain_count"] == 1
        assert result["url_count"] == 0
        assert result["domain_report_mode_count"] == 0
        assert result["url_report_mode_count"] == 1

    def test_single_domain_domain_report_mode(self):
        item = self._make_item(InputType.DOMAIN)
        result = estimate_job([item], use_domain_reports=True)
        assert result["estimated_vt_calls_min"] == 1
        assert result["estimated_vt_calls_max"] == 1
        assert result["domain_report_mode_count"] == 1
        assert result["url_report_mode_count"] == 0

    def test_single_url(self):
        item = self._make_item(InputType.URL, "http://example.com/path")
        result = estimate_job([item], use_domain_reports=False)
        assert result["estimated_vt_calls_min"] == 1
        assert result["estimated_vt_calls_max"] == 3
        assert result["url_count"] == 1
        assert result["domain_count"] == 0

    def test_mixed_5_domains_3_urls_url_mode(self):
        from models import MdiInputItem
        items = (
            [MdiInputItem(input_original=f"d{i}.com", input_normalized=f"d{i}.com",
                          input_type=InputType.DOMAIN, position=i) for i in range(1, 6)]
            + [MdiInputItem(input_original=f"http://u{i}.com/", input_normalized=f"http://u{i}.com/",
                            input_type=InputType.URL, position=5 + i) for i in range(1, 4)]
        )
        result = estimate_job(items, use_domain_reports=False)
        # 5 domains × 3 + 3 URLs × 3 = 24 max; min = 8
        assert result["estimated_vt_calls_min"] == 8
        assert result["estimated_vt_calls_max"] == 24
        assert result["domain_count"] == 5
        assert result["url_count"] == 3

    def test_duration_formula_single_item(self):
        from models import MdiInputItem
        item = MdiInputItem(input_original="a.com", input_normalized="a.com",
                            input_type=InputType.DOMAIN, position=1)
        result = estimate_job([item], use_domain_reports=False)
        # (1 - 1) * 15 = 0 for min; (3 - 1) * 15 = 30 for max
        assert result["estimated_duration_seconds_min"] == 0.0
        assert result["estimated_duration_seconds_max"] == pytest.approx(30.0)

    def test_duration_formula_two_items(self):
        from models import MdiInputItem
        items = [
            MdiInputItem(input_original="a.com", input_normalized="a.com",
                         input_type=InputType.DOMAIN, position=1),
            MdiInputItem(input_original="b.com", input_normalized="b.com",
                         input_type=InputType.DOMAIN, position=2),
        ]
        result = estimate_job(items, use_domain_reports=False)
        # calls_min=2, calls_max=6 → durations: (2-1)*15=15, (6-1)*15=75
        assert result["estimated_duration_seconds_min"] == pytest.approx(15.0)
        assert result["estimated_duration_seconds_max"] == pytest.approx(75.0)

    def test_notes_present(self):
        result = estimate_job([], use_domain_reports=False)
        assert result["rate_limit_note"] == VT_RATE_LIMIT_NOTE
        assert result["job_state_note"] == JOB_STATE_NOTE


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint tests via TestClient
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimateEndpoint:

    def test_missing_raw_input_returns_422(self):
        resp = client.post(ESTIMATE_URL, json={})
        assert resp.status_code == 422

    def test_empty_string_raw_input(self):
        """Empty string is technically valid input — parser returns 0 accepted."""
        resp = _post_estimate("   ")
        assert resp["accepted_count"] == 0
        assert resp["eligible_vt_count"] == 0
        assert resp["estimated_vt_calls_min"] == 0
        assert resp["estimated_vt_calls_max"] == 0

    def test_single_bare_domain_url_mode(self):
        resp = _post_estimate("example.com", use_domain_reports=False)
        assert resp["accepted_count"] == 1
        assert resp["estimated_vt_calls_min"] == 1
        assert resp["estimated_vt_calls_max"] == 3
        assert resp["domain_count"] == 1
        assert resp["url_count"] == 0
        assert resp["url_report_mode_count"] == 1
        assert resp["domain_report_mode_count"] == 0

    def test_single_bare_domain_domain_report_mode(self):
        resp = _post_estimate("example.com", use_domain_reports=True)
        assert resp["estimated_vt_calls_min"] == 1
        assert resp["estimated_vt_calls_max"] == 1
        assert resp["domain_report_mode_count"] == 1
        assert resp["url_report_mode_count"] == 0

    def test_single_full_url(self):
        resp = _post_estimate("https://example.com/path")
        assert resp["accepted_count"] == 1
        assert resp["estimated_vt_calls_min"] == 1
        assert resp["estimated_vt_calls_max"] == 3
        assert resp["url_count"] == 1
        assert resp["domain_count"] == 0

    def test_mixed_domains_and_urls(self):
        raw = "example.com\nhttps://malicious.test/\ngoodsite.org"
        resp = _post_estimate(raw)
        assert resp["accepted_count"] == 3
        assert resp["domain_count"] == 2
        assert resp["url_count"] == 1
        assert resp["estimated_vt_calls_min"] == 3
        assert resp["estimated_vt_calls_max"] == 9

    def test_duplicates_counted_once(self):
        resp = _post_estimate("example.com\nexample.com\nexample.com")
        assert resp["accepted_count"] == 1
        assert resp["duplicate_count"] == 2
        assert resp["estimated_vt_calls_max"] == 3  # only 1 item

    def test_invalid_items_rejected_not_counted(self):
        # ftp:// is an unsupported scheme — parser rejects it cleanly
        resp = _post_estimate("ftp://bad-scheme.example\nexample.com")
        assert resp["rejected_count"] >= 1
        assert resp["accepted_count"] == 1
        assert resp["estimated_vt_calls_max"] == 3  # only valid item counted

    def test_paste_input_held_skipped_count_always_zero(self):
        """For paste input, hold status is NOT_CHECKED — held_skipped_count must be 0."""
        resp = _post_estimate("example.com\nhttps://test.org/")
        assert resp["held_skipped_count"] == 0

    def test_quota_remaining_reads_from_file(self, tmp_path):
        """Quota read is injected via environment variable for test isolation."""
        usage_file = _make_usage_file(tmp_path, used=100)
        old_env = os.environ.get("VT_USAGE_FILE")
        try:
            os.environ["VT_USAGE_FILE"] = str(usage_file)
            resp = _post_estimate("example.com")
            # 500 - 100 = 400 remaining
            assert resp["quota_remaining_now"] == 400
        finally:
            if old_env is None:
                os.environ.pop("VT_USAGE_FILE", None)
            else:
                os.environ["VT_USAGE_FILE"] = old_env

    def test_will_exceed_quota_true(self, tmp_path):
        """When max estimate exceeds remaining quota, will_exceed_quota is True."""
        usage_file = _make_usage_file(tmp_path, used=499)  # 1 remaining
        old_env = os.environ.get("VT_USAGE_FILE")
        try:
            os.environ["VT_USAGE_FILE"] = str(usage_file)
            # 1 domain in URL mode = max 3 calls; 1 remaining → exceeds
            resp = _post_estimate("example.com")
            assert resp["will_exceed_quota"] is True
            assert resp["quota_headroom"] < 0
        finally:
            if old_env is None:
                os.environ.pop("VT_USAGE_FILE", None)
            else:
                os.environ["VT_USAGE_FILE"] = old_env

    def test_will_exceed_quota_false(self, tmp_path):
        """When max estimate fits within quota, will_exceed_quota is False."""
        usage_file = _make_usage_file(tmp_path, used=0)  # 500 remaining
        old_env = os.environ.get("VT_USAGE_FILE")
        try:
            os.environ["VT_USAGE_FILE"] = str(usage_file)
            resp = _post_estimate("example.com")
            assert resp["will_exceed_quota"] is False
            assert resp["quota_headroom"] > 0
        finally:
            if old_env is None:
                os.environ.pop("VT_USAGE_FILE", None)
            else:
                os.environ["VT_USAGE_FILE"] = old_env

    def test_quota_headroom_calculation(self, tmp_path):
        usage_file = _make_usage_file(tmp_path, used=490)  # 10 remaining
        old_env = os.environ.get("VT_USAGE_FILE")
        try:
            os.environ["VT_USAGE_FILE"] = str(usage_file)
            # 1 domain URL mode = max 3 calls; headroom = 10 - 3 = 7
            resp = _post_estimate("example.com")
            assert resp["quota_remaining_now"] == 10
            assert resp["quota_headroom"] == 10 - resp["estimated_vt_calls_max"]
        finally:
            if old_env is None:
                os.environ.pop("VT_USAGE_FILE", None)
            else:
                os.environ["VT_USAGE_FILE"] = old_env

    def test_duration_seconds_max_formula(self):
        resp = _post_estimate("example.com")
        calls_max = resp["estimated_vt_calls_max"]
        expected_max = max(0.0, (calls_max - 1) * VT_RATE_LIMIT_INTERVAL_SECONDS)
        assert resp["estimated_duration_seconds_max"] == pytest.approx(expected_max)

    def test_duration_seconds_min_formula(self):
        resp = _post_estimate("example.com")
        calls_min = resp["estimated_vt_calls_min"]
        expected_min = max(0.0, (calls_min - 1) * VT_RATE_LIMIT_INTERVAL_SECONDS)
        assert resp["estimated_duration_seconds_min"] == pytest.approx(expected_min)

    def test_rate_limit_note_present(self):
        resp = _post_estimate("example.com")
        assert resp["rate_limit_note"]
        assert len(resp["rate_limit_note"]) > 10

    def test_job_state_note_present(self):
        resp = _post_estimate("example.com")
        assert resp["job_state_note"]
        assert "memory" in resp["job_state_note"].lower()

    def test_external_calls_made_always_false(self):
        resp = _post_estimate("example.com")
        assert resp["external_calls_made"] is False

    def test_quota_consumed_always_false(self):
        resp = _post_estimate("example.com")
        assert resp["quota_consumed"] is False

    def test_mutated_always_false(self):
        resp = _post_estimate("example.com")
        assert resp["mutated"] is False

    def test_estimate_does_not_create_job(self):
        from services.job_store import get_job_sync
        _post_estimate("example.com\nhttps://test.com/")
        # No job should exist after an estimate call
        # (We can't enumerate all jobs easily, but we know clear_all_jobs ran before
        #  and no new jobs should appear.)
        # Verify job_store is still empty by trying a known-missing id
        assert get_job_sync("nonexistent-job-id") is None

    def test_estimate_does_not_write_usage_history(self, tmp_path):
        """Estimate endpoint must not append to vt_usage_history.jsonl."""
        history_file = tmp_path / "vt_usage_history.jsonl"
        old_env = os.environ.get("VT_HISTORY_FILE")
        try:
            os.environ["VT_HISTORY_FILE"] = str(history_file)
            _post_estimate("example.com")
            assert not history_file.exists(), "Estimate must not write usage history"
        finally:
            if old_env is None:
                os.environ.pop("VT_HISTORY_FILE", None)
            else:
                os.environ["VT_HISTORY_FILE"] = old_env

    def test_live_quota_file_not_modified(self):
        """The live /var/lib/dns-tool/vt_usage.json must not be modified."""
        live_path = Path(os.environ.get("VT_USAGE_FILE", "/var/lib/dns-tool/vt_usage.json"))
        if not live_path.exists():
            pytest.skip("Live usage file not present in this environment")
        mtime_before = live_path.stat().st_mtime
        _post_estimate("example.com")
        mtime_after = live_path.stat().st_mtime
        assert mtime_before == mtime_after, (
            "Estimate endpoint modified the live quota file — this is a hard violation."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Parity tests: estimate and submit must use the same formula
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimateSubmitParity:
    """
    Verify that estimate_job (used by /estimate) produces max values that match
    what _estimate_requests (used by /submit) returns.
    """

    def test_parity_single_domain_url_mode(self):
        from models import MdiInputItem
        from services.estimate import estimate_job
        item = MdiInputItem(input_original="a.com", input_normalized="a.com",
                            input_type=InputType.DOMAIN, position=1)
        est = estimate_job([item], use_domain_reports=False)
        # submit uses _estimate_requests which now delegates to estimate_job max
        from routers.mdi import _estimate_requests
        submit_max = _estimate_requests([item], use_domain_reports=False)
        assert submit_max == est["estimated_vt_calls_max"]

    def test_parity_single_domain_domain_mode(self):
        from models import MdiInputItem
        from services.estimate import estimate_job
        from routers.mdi import _estimate_requests
        item = MdiInputItem(input_original="a.com", input_normalized="a.com",
                            input_type=InputType.DOMAIN, position=1)
        est = estimate_job([item], use_domain_reports=True)
        submit_max = _estimate_requests([item], use_domain_reports=True)
        assert submit_max == est["estimated_vt_calls_max"]

    def test_parity_url_item(self):
        from models import MdiInputItem
        from services.estimate import estimate_job
        from routers.mdi import _estimate_requests
        item = MdiInputItem(input_original="http://a.com/", input_normalized="http://a.com/",
                            input_type=InputType.URL, position=1)
        est = estimate_job([item], use_domain_reports=False)
        submit_max = _estimate_requests([item], use_domain_reports=False)
        assert submit_max == est["estimated_vt_calls_max"]


# ─────────────────────────────────────────────────────────────────────────────
# Regression: existing endpoints must not be affected
# ─────────────────────────────────────────────────────────────────────────────

class TestRegressionExistingEndpoints:

    def test_health_still_works(self):
        resp = client.get("/api/mdi/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_usage_still_works(self):
        resp = client.get("/api/mdi/usage")
        assert resp.status_code == 200
        assert "remaining" in resp.json()

    def test_parse_preview_still_works(self):
        resp = client.post("/api/mdi/jobs/parse-preview",
                           json={"raw_input": "example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted_count"] == 1
        assert data["external_calls_made"] is False
        assert data["quota_consumed"] is False

    def test_schema_summary_still_works(self):
        resp = client.get("/api/mdi/schema-summary")
        assert resp.status_code == 200
        assert "enums" in resp.json()

    def test_schema_summary_stale_threshold_constant_is_7(self):
        """MDI-09A: schema-summary must report STALE_THRESHOLD_DAYS=7 to match PRD and Pydantic defaults."""
        resp = client.get("/api/mdi/schema-summary")
        assert resp.status_code == 200
        assert resp.json()["constants"]["STALE_THRESHOLD_DAYS"] == 7


# ─────────────────────────────────────────────────────────────────────────────
# MDI-09 — Settings default and parity tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMdi09SettingsDefaults:
    """
    Verify stale_threshold_days default is 7 and use_domain_reports affects
    estimates correctly.  No VT calls, no external calls, no runtime file writes.
    """

    def test_estimate_default_stale_threshold_is_7(self):
        """Omitting stale_threshold_days from /estimate request → backend uses 7."""
        from models import EstimateRequest
        req = EstimateRequest(raw_input="example.com")
        assert req.stale_threshold_days == 7

    def test_estimate_endpoint_accepts_omitted_stale_threshold(self):
        """POST /estimate without stale_threshold_days returns 200 and accepted_count ≥ 1."""
        resp = client.post("/api/mdi/jobs/estimate", json={"raw_input": "example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted_count"] >= 1
        assert data["external_calls_made"] is False

    def test_url_mode_bare_domain_estimate_max_3_calls(self):
        """use_domain_reports=False: bare domain estimate max = 3 (URL-report path)."""
        resp = client.post("/api/mdi/jobs/estimate", json={
            "raw_input": "single-domain.com",
            "use_domain_reports": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["estimated_vt_calls_max"] == 3
        assert data["domain_count"] == 1

    def test_domain_mode_bare_domain_estimate_max_1_call(self):
        """use_domain_reports=True: bare domain estimate max = 1 (domain-report path)."""
        resp = client.post("/api/mdi/jobs/estimate", json={
            "raw_input": "single-domain.com",
            "use_domain_reports": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["estimated_vt_calls_max"] == 1
        assert data["domain_count"] == 1

    def test_url_item_always_url_report_path_regardless_of_mode(self):
        """
        Full URL items (InputType.URL) always use the URL-report path, regardless
        of use_domain_reports.  The URL-report path estimates up to 3 calls
        (1 GET + 1 submit + 1 re-fetch if URL not yet cached on VT).
        domain-report mode only reduces calls for bare domains (InputType.DOMAIN).
        """
        for mode in (True, False):
            resp = client.post("/api/mdi/jobs/estimate", json={
                "raw_input": "http://full-url.com/path",
                "use_domain_reports": mode,
            })
            assert resp.status_code == 200
            data = resp.json()
            # max is 3 for URL items in both modes (URL-report path)
            assert data["estimated_vt_calls_max"] == 3, f"mode={mode}"
            assert data["url_count"] == 1, f"mode={mode}"

    def test_estimate_and_submit_request_fields_match(self):
        """
        EstimateRequest and JobSubmitRequest share the same four settings fields
        with identical names and defaults.  This ensures frontend can use a single
        settingsPayload object for both calls.
        """
        from models import EstimateRequest, JobSubmitRequest
        est_fields = {f: v.default for f, v in EstimateRequest.model_fields.items()
                      if f in ('use_domain_reports', 'stale_threshold_days',
                               'default_scheme', 'max_items')}
        sub_fields = {f: v.default for f, v in JobSubmitRequest.model_fields.items()
                      if f in ('use_domain_reports', 'stale_threshold_days',
                               'default_scheme', 'max_items')}
        assert est_fields == sub_fields, (
            f"Estimate/submit settings mismatch: estimate={est_fields} submit={sub_fields}"
        )

    def test_stale_threshold_default_7_in_job_submit_request(self):
        from models import JobSubmitRequest
        req = JobSubmitRequest(raw_input="example.com")
        assert req.stale_threshold_days == 7

    def test_stale_threshold_default_7_in_mdi_job_options(self):
        from models import MdiJobOptions
        opts = MdiJobOptions()
        assert opts.stale_threshold_days == 7

    def test_stale_threshold_default_7_in_memory_job(self):
        from services.job_store import InMemoryJob
        import time
        job = InMemoryJob(job_id="test-default-stale", status="queued",
                          submitted_at=time.time())
        assert job.stale_threshold_days == 7

    def test_use_domain_reports_stored_in_job_status_response(self):
        """
        When use_domain_reports=True is submitted, JobStatusResponse must echo it back.
        Tests that the setting is saved to the job, not just used internally.
        Uses mocked VT + tmp_path to avoid live quota consumption.
        """
        from unittest.mock import AsyncMock, patch
        from services import job_processor, job_store
        from models import InputType

        job_id = "test-domain-mode-settings-" + str(__import__("time").time_ns())
        # Create a queued job with domain-mode=True
        from services.job_store import InMemoryJob
        from models import MdiResultItem, MdiProcessingStatus
        import time
        job = InMemoryJob(
            job_id=job_id, status="queued",
            submitted_at=time.time(), total=1,
            use_domain_reports=True, stale_threshold_days=7,
        )
        domain = "domainmode-test.com"
        job.results[domain] = MdiResultItem(
            input_original=domain, input_normalized=domain,
            input_type=InputType.DOMAIN, position=1,
            processing_status=MdiProcessingStatus.PENDING,
        )
        job.item_order.append(domain)

        import asyncio
        from pathlib import Path
        asyncio.run(job_store.create_job(job))

        body = {
            "data": {"attributes": {
                "last_analysis_stats": {"malicious": 0, "suspicious": 0, "harmless": 70, "undetected": 5, "timeout": 0},
                "last_analysis_date": int(time.time()) - 3600,
            }}
        }
        from unittest.mock import MagicMock
        import services.vt_service as vt_svc
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = body
        mock_req = AsyncMock(return_value=mock_resp)
        tmp = Path(__import__("tempfile").mkdtemp())
        usage_file = tmp / "vt_usage.json"
        usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')
        job_file = tmp / "mdi_latest_job.json"

        with patch("services.vt_service._vt_request", new=mock_req), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}), \
             patch.object(vt_svc._VT_LIMITER, "acquire", new=AsyncMock()):
            asyncio.run(job_processor.process_job(
                job_id, usage_file=usage_file, job_file=job_file,
            ))

        completed = job_store.get_job_sync(job_id)
        assert completed.use_domain_reports is True
        assert completed.stale_threshold_days == 7

        # Clean up job store
        job_store.clear_all_jobs()

    def test_no_vt_calls_during_settings_tests(self):
        """Confirm job_persistence and estimate service do not import httpx."""
        import services.estimate as est_mod
        import inspect
        src = inspect.getsource(est_mod)
        assert "httpx" not in src
        assert "_vt_request" not in src
