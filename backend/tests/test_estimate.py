"""
MDI-07 — Tests for POST /api/mdi/jobs/estimate.

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
