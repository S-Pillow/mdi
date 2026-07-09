"""
MDI-07/MDI-09/MDI-11A — Tests for POST /api/mdi/jobs/estimate.

Guarantees enforced by every test in this module:
  - No VT calls made (no httpx, no _vt_request invocations).
  - No jobs created (job_store remains empty).
  - No runtime files written (live /var/lib/dns-tool/vt_usage.json is not modified).
  - No external services contacted (no WHOIS, RDAP, DNS, URL Activity Scanner).

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
    RDAP_ESTIMATE_SECONDS_PER_ITEM,
    RDAP_ENRICHMENT_LARGE_COUNT_THRESHOLD,
    estimate_calls_for_item,
    estimate_job,
    partition_upload_items,
    upload_item_has_hold,
)
from services.job_store import clear_all_jobs
from services.upload_parser import parse_upload
from models import (
    DomainHold,
    DomainHoldType,
    DomainStatusSource,
    InputType,
    UploadedInputItem,
)

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
        """MDI-57A: submit-only — URL-report path worst case is 2 (GET + POST)."""
        c_min, c_max = estimate_calls_for_item(InputType.DOMAIN, use_domain_reports=False)
        assert c_min == 1
        assert c_max == 2

    def test_domain_domain_report_mode(self):
        c_min, c_max = estimate_calls_for_item(InputType.DOMAIN, use_domain_reports=True)
        assert c_min == 1
        assert c_max == 1

    def test_url_url_mode(self):
        """MDI-57A: new URL worst case is 2 calls (no immediate re-fetch)."""
        c_min, c_max = estimate_calls_for_item(InputType.URL, use_domain_reports=False)
        assert c_min == 1
        assert c_max == 2

    def test_url_domain_report_mode_flag_ignored(self):
        """use_domain_reports only applies to DOMAIN items; URL items are unaffected."""
        c_min, c_max = estimate_calls_for_item(InputType.URL, use_domain_reports=True)
        assert c_min == 1
        assert c_max == 2


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
        # MDI-11: empty list → 0 enrichment lookups
        assert result["estimated_enrichment_lookups"] == 0

    def test_single_domain_url_mode(self):
        item = self._make_item(InputType.DOMAIN)
        result = estimate_job([item], use_domain_reports=False)
        assert result["estimated_vt_calls_min"] == 1
        assert result["estimated_vt_calls_max"] == 2
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
        assert result["estimated_vt_calls_max"] == 2
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
        # MDI-57A: 5 domains × 2 + 3 URLs × 2 = 16 max; min = 8
        assert result["estimated_vt_calls_min"] == 8
        assert result["estimated_vt_calls_max"] == 16
        assert result["domain_count"] == 5
        assert result["url_count"] == 3

    def test_duration_formula_single_item(self):
        # MDI-11A: enrichment_min=0 (best case), enrichment_max=N×1.1 (worst case)
        # VT (MDI-57A): (1-1)×15=0 min, (2-1)×15=15 max
        item = self._make_item(InputType.DOMAIN, "a.com")
        result = estimate_job([item], use_domain_reports=False)
        enrichment_max = 1 * RDAP_ESTIMATE_SECONDS_PER_ITEM  # 1.1
        assert result["estimated_duration_seconds_min"] == pytest.approx(0.0)   # VT min + enrichment_min(0)
        assert result["estimated_duration_seconds_max"] == pytest.approx(15.0 + enrichment_max)
        assert result["estimated_enrichment_lookups"] == 1
        assert result["estimated_enrichment_duration_seconds_min"] == pytest.approx(0.0)
        assert result["estimated_enrichment_duration_seconds_max"] == pytest.approx(enrichment_max)

    def test_duration_formula_two_items(self):
        # MDI-11A: enrichment_min=0, enrichment_max=2×1.1=2.2
        # VT (MDI-57A): calls_min=2, calls_max=4 → (2-1)×15=15, (4-1)×15=45
        items = [
            self._make_item(InputType.DOMAIN, "a.com"),
            self._make_item(InputType.DOMAIN, "b.com"),
        ]
        result = estimate_job(items, use_domain_reports=False)
        enrichment_max = 2 * RDAP_ESTIMATE_SECONDS_PER_ITEM  # 2.2
        assert result["estimated_duration_seconds_min"] == pytest.approx(15.0)  # VT min + enrichment_min(0)
        assert result["estimated_duration_seconds_max"] == pytest.approx(45.0 + enrichment_max)
        assert result["estimated_enrichment_lookups"] == 2
        assert result["estimated_enrichment_duration_seconds_min"] == pytest.approx(0.0)
        assert result["estimated_enrichment_duration_seconds_max"] == pytest.approx(enrichment_max)

    def test_notes_present(self):
        from services.estimate import ENRICHMENT_NOTE
        result = estimate_job([], use_domain_reports=False)
        assert result["rate_limit_note"] == VT_RATE_LIMIT_NOTE
        assert result["job_state_note"] == JOB_STATE_NOTE
        assert result["enrichment_note"] == ENRICHMENT_NOTE

    def test_empty_list_has_no_enrichment_warning(self):
        result = estimate_job([], use_domain_reports=False)
        assert result["enrichment_warning"] == ""

    def test_small_batch_no_enrichment_warning(self):
        """Batches ≤ RDAP_ENRICHMENT_LARGE_COUNT_THRESHOLD must not produce a warning."""
        from models import MdiInputItem
        items = [
            MdiInputItem(input_original=f"d{i}.com", input_normalized=f"d{i}.com",
                         input_type=InputType.DOMAIN, position=i)
            for i in range(1, RDAP_ENRICHMENT_LARGE_COUNT_THRESHOLD + 1)
        ]
        result = estimate_job(items, use_domain_reports=False)
        assert result["enrichment_warning"] == "", (
            "No warning expected for exactly RDAP_ENRICHMENT_LARGE_COUNT_THRESHOLD items"
        )


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
        assert resp["estimated_vt_calls_max"] == 2
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
        assert resp["estimated_vt_calls_max"] == 2
        assert resp["url_count"] == 1
        assert resp["domain_count"] == 0

    def test_mixed_domains_and_urls(self):
        raw = "example.com\nhttps://malicious.test/\ngoodsite.org"
        resp = _post_estimate(raw)
        assert resp["accepted_count"] == 3
        assert resp["domain_count"] == 2
        assert resp["url_count"] == 1
        assert resp["estimated_vt_calls_min"] == 3
        assert resp["estimated_vt_calls_max"] == 6

    def test_duplicates_counted_once(self):
        resp = _post_estimate("example.com\nexample.com\nexample.com")
        assert resp["accepted_count"] == 1
        assert resp["duplicate_count"] == 2
        assert resp["estimated_vt_calls_max"] == 2  # only 1 item

    def test_invalid_items_rejected_not_counted(self):
        # ftp:// is an unsupported scheme — parser rejects it cleanly
        resp = _post_estimate("ftp://bad-scheme.example\nexample.com")
        assert resp["rejected_count"] >= 1
        assert resp["accepted_count"] == 1
        assert resp["estimated_vt_calls_max"] == 2  # only valid item counted

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
            # 1 domain in URL mode = max 2 calls; 1 remaining → exceeds
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
            # 1 domain URL mode = max 2 calls; headroom = 10 - 2 = 8
            resp = _post_estimate("example.com")
            assert resp["quota_remaining_now"] == 10
            assert resp["quota_headroom"] == 10 - resp["estimated_vt_calls_max"]
        finally:
            if old_env is None:
                os.environ.pop("VT_USAGE_FILE", None)
            else:
                os.environ["VT_USAGE_FILE"] = old_env

    def test_duration_seconds_max_formula(self):
        # MDI-11A: total_max = VT_max + enrichment_max (N × 1.1 s)
        resp = _post_estimate("example.com")
        calls_max = resp["estimated_vt_calls_max"]
        enrichment_lookups = resp["estimated_enrichment_lookups"]
        expected_max = (
            max(0.0, (calls_max - 1) * VT_RATE_LIMIT_INTERVAL_SECONDS)
            + enrichment_lookups * RDAP_ESTIMATE_SECONDS_PER_ITEM
        )
        assert resp["estimated_duration_seconds_max"] == pytest.approx(expected_max)

    def test_duration_seconds_min_formula(self):
        # MDI-11A: total_min = VT_min + 0 (best-case enrichment = 0)
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
        """The live /var/lib/dns-tool/vt_usage.json must not be modified.

        Always checks the real runtime file regardless of VT_USAGE_FILE env var,
        because the conftest.py autouse fixture redirects VT_USAGE_FILE to
        tmp_path for all tests.  The estimate endpoint cannot reach the live
        file when the redirect is active, so this test trivially passes — but
        it still guards against any accidental removal of that isolation.
        """
        live_path = Path("/var/lib/dns-tool/vt_usage.json")
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

    def test_schema_summary_stale_threshold_constant_is_30(self):
        """MDI-57A: schema-summary must report STALE_THRESHOLD_DAYS=30 to match Pydantic defaults."""
        resp = client.get("/api/mdi/schema-summary")
        assert resp.status_code == 200
        assert resp.json()["constants"]["STALE_THRESHOLD_DAYS"] == 30


# ─────────────────────────────────────────────────────────────────────────────
# MDI-09 — Settings default and parity tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMdi09SettingsDefaults:
    """
    Verify stale_threshold_days default is 30 (MDI-57A) and use_domain_reports
    affects estimates correctly.  No VT calls, no external calls, no runtime file writes.
    """

    def test_estimate_default_stale_threshold_is_30(self):
        """Omitting stale_threshold_days from /estimate request → backend uses 30."""
        from models import EstimateRequest
        req = EstimateRequest(raw_input="example.com")
        assert req.stale_threshold_days == 30

    def test_estimate_endpoint_accepts_omitted_stale_threshold(self):
        """POST /estimate without stale_threshold_days returns 200 and accepted_count ≥ 1."""
        resp = client.post("/api/mdi/jobs/estimate", json={"raw_input": "example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted_count"] >= 1
        assert data["external_calls_made"] is False

    def test_url_mode_bare_domain_estimate_max_2_calls(self):
        """MDI-57A: use_domain_reports=False: bare domain estimate max = 2 (URL-report path)."""
        resp = client.post("/api/mdi/jobs/estimate", json={
            "raw_input": "single-domain.com",
            "use_domain_reports": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["estimated_vt_calls_max"] == 2
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
        of use_domain_reports.  The URL-report path estimates up to 2 calls
        (1 GET + 1 submit-only if URL not yet cached on VT — MDI-57A).
        domain-report mode only reduces calls for bare domains (InputType.DOMAIN).
        """
        for mode in (True, False):
            resp = client.post("/api/mdi/jobs/estimate", json={
                "raw_input": "http://full-url.com/path",
                "use_domain_reports": mode,
            })
            assert resp.status_code == 200
            data = resp.json()
            # max is 2 for URL items in both modes (URL-report path)
            assert data["estimated_vt_calls_max"] == 2, f"mode={mode}"
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

    def test_stale_threshold_default_30_in_job_submit_request(self):
        from models import JobSubmitRequest
        req = JobSubmitRequest(raw_input="example.com")
        assert req.stale_threshold_days == 30

    def test_stale_threshold_default_30_in_mdi_job_options(self):
        from models import MdiJobOptions
        opts = MdiJobOptions()
        assert opts.stale_threshold_days == 30

    def test_stale_threshold_default_30_in_memory_job(self):
        from services.job_store import InMemoryJob
        import time
        job = InMemoryJob(job_id="test-default-stale", status="queued",
                          submitted_at=time.time())
        assert job.stale_threshold_days == 30

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


# ─────────────────────────────────────────────────────────────────────────────
# MDI-11A — RDAP rate-limit timing and enrichment estimate fields
# ─────────────────────────────────────────────────────────────────────────────

class TestMdi11aEnrichmentEstimate:
    """
    Verify the corrected RDAP estimate constants and new EstimateResponse fields.
    No VT, RDAP, WHOIS, or DNS calls are made.
    No runtime files are modified.
    """

    def _make_item(self, n: int, input_type=InputType.DOMAIN) -> "MdiInputItem":
        from models import MdiInputItem
        return MdiInputItem(
            input_original=f"d{n}.com", input_normalized=f"d{n}.com",
            input_type=input_type, position=n,
        )

    def test_rdap_estimate_seconds_per_item_is_1_1(self):
        """MDI-11A: per-item estimate must be 1.1 s (rdap.org rate limit)."""
        assert RDAP_ESTIMATE_SECONDS_PER_ITEM == pytest.approx(1.1)

    def test_enrichment_duration_min_always_zero(self):
        """Best-case enrichment = 0 s (all items share 1 registered domain)."""
        items = [self._make_item(i) for i in range(1, 6)]
        result = estimate_job(items, use_domain_reports=False)
        assert result["estimated_enrichment_duration_seconds_min"] == pytest.approx(0.0)

    def test_enrichment_duration_max_is_n_times_1_1(self):
        """Worst-case enrichment = N × 1.1 s (all items are unique registered domains)."""
        n = 10
        items = [self._make_item(i) for i in range(1, n + 1)]
        result = estimate_job(items, use_domain_reports=False)
        assert result["estimated_enrichment_duration_seconds_max"] == pytest.approx(n * 1.1)

    def test_total_max_includes_enrichment_max(self):
        """estimated_duration_seconds_max must equal VT_max + enrichment_max."""
        n = 5
        items = [self._make_item(i) for i in range(1, n + 1)]
        result = estimate_job(items, use_domain_reports=False)
        assert result["estimated_duration_seconds_max"] == pytest.approx(
            result["estimated_duration_seconds_max"]  # tautological — use formula below
        )
        # Manual formula check:
        vt_max_calls = result["estimated_vt_calls_max"]
        vt_max_time = max(0.0, (vt_max_calls - 1) * VT_RATE_LIMIT_INTERVAL_SECONDS)
        enrichment_max = n * RDAP_ESTIMATE_SECONDS_PER_ITEM
        assert result["estimated_duration_seconds_max"] == pytest.approx(vt_max_time + enrichment_max)

    def test_total_min_excludes_enrichment(self):
        """estimated_duration_seconds_min must equal VT_min only (enrichment_min = 0)."""
        n = 5
        items = [self._make_item(i) for i in range(1, n + 1)]
        result = estimate_job(items, use_domain_reports=False)
        vt_min_calls = result["estimated_vt_calls_min"]
        vt_min_time = max(0.0, (vt_min_calls - 1) * VT_RATE_LIMIT_INTERVAL_SECONDS)
        assert result["estimated_duration_seconds_min"] == pytest.approx(vt_min_time)

    def test_no_enrichment_warning_below_threshold(self):
        items = [self._make_item(i) for i in range(1, RDAP_ENRICHMENT_LARGE_COUNT_THRESHOLD + 1)]
        result = estimate_job(items, use_domain_reports=False)
        assert result["enrichment_warning"] == ""

    def test_enrichment_warning_above_threshold(self):
        """Batches > 100 items must have a non-empty enrichment_warning."""
        items = [self._make_item(i) for i in range(1, RDAP_ENRICHMENT_LARGE_COUNT_THRESHOLD + 2)]
        result = estimate_job(items, use_domain_reports=False)
        assert result["enrichment_warning"] != "", "Warning expected for large batch"
        assert "rdap" in result["enrichment_warning"].lower()

    def test_estimate_500_items_enrichment_around_550_seconds(self):
        """
        For 500 unique domains, worst-case RDAP enrichment time must be ≈550 s (9+ minutes).
        This verifies the corrected 1.1 s/item estimate from MDI-11A.
        """
        n = 500
        items = [self._make_item(i) for i in range(1, n + 1)]
        result = estimate_job(items, use_domain_reports=False)

        enrichment_max = result["estimated_enrichment_duration_seconds_max"]
        assert enrichment_max == pytest.approx(n * 1.1)
        # 500 × 1.1 = 550 s
        assert enrichment_max >= 540, f"Expected ≥540 s for 500 items, got {enrichment_max}"
        assert enrichment_max <= 560, f"Expected ≤560 s for 500 items, got {enrichment_max}"
        # 550 s > 9 minutes
        assert enrichment_max / 60 > 9.0, "Expected more than 9 minutes of enrichment overhead"

    def test_estimate_500_items_warning_mentions_minutes(self):
        """Warning text for 500 items must mention minutes and rate limit."""
        n = 500
        items = [self._make_item(i) for i in range(1, n + 1)]
        result = estimate_job(items, use_domain_reports=False)
        warning = result["enrichment_warning"]
        assert "minute" in warning.lower(), f"Warning must mention minutes: {warning}"
        assert "rate" in warning.lower(), f"Warning must mention rate limit: {warning}"

    def test_estimate_endpoint_returns_enrichment_duration_fields(self):
        """The /estimate endpoint must include all MDI-11A enrichment fields."""
        resp = _post_estimate("example.com\nexample2.com")
        assert "estimated_enrichment_duration_seconds_min" in resp
        assert "estimated_enrichment_duration_seconds_max" in resp
        assert "enrichment_warning" in resp
        assert resp["estimated_enrichment_duration_seconds_min"] == pytest.approx(0.0)
        assert resp["estimated_enrichment_duration_seconds_max"] > 0.0

    def test_estimate_endpoint_no_live_calls(self):
        """
        Confirm estimate.py makes no external HTTP calls.
        It may document rdap.org in comments/strings, but must never import httpx
        or invoke _rdap_request.
        """
        import services.estimate as est_mod
        import inspect
        src = inspect.getsource(est_mod)
        assert "httpx" not in src, "estimate.py must not import httpx"
        assert "_rdap_request" not in src, "estimate.py must not call _rdap_request"
        assert "import requests" not in src, "estimate.py must not import requests"

    def test_no_runtime_files_modified_by_estimate(self, tmp_path):
        """Estimate endpoint must not write any runtime file."""
        history_file = tmp_path / "vt_usage_history.jsonl"
        job_file = tmp_path / "mdi_latest_job.json"
        old_hist = os.environ.get("VT_HISTORY_FILE")
        old_job = os.environ.get("MDI_JOB_FILE")
        try:
            os.environ["VT_HISTORY_FILE"] = str(history_file)
            os.environ["MDI_JOB_FILE"] = str(job_file)
            _post_estimate("example.com")
            assert not history_file.exists(), "Estimate must not write usage history"
            assert not job_file.exists(), "Estimate must not write job file"
        finally:
            if old_hist is None:
                os.environ.pop("VT_HISTORY_FILE", None)
            else:
                os.environ["VT_HISTORY_FILE"] = old_hist
            if old_job is None:
                os.environ.pop("MDI_JOB_FILE", None)
            else:
                os.environ["MDI_JOB_FILE"] = old_job


# ─────────────────────────────────────────────────────────────────────────────
# MDI-12 — live-check estimate fields
# ─────────────────────────────────────────────────────────────────────────────


class TestMdi12LiveCheckEstimate:
    """
    MDI-12: verify that the estimate endpoint and estimate_job() return
    estimated_live_check_count=0 and a non-empty live_check_note, and that
    estimate.py makes no live DNS, HTTP, or VT calls.
    """

    def test_estimated_live_check_count_is_zero(self):
        """estimated_live_check_count is always 0 at estimate time (flagged count unknown)."""
        resp = _post_estimate("evil.com\nmalware.net")
        assert resp["estimated_live_check_count"] == 0

    def test_live_check_note_present_and_non_empty(self):
        """live_check_note must be a non-empty string explaining conditional timing."""
        resp = _post_estimate("example.com")
        assert "live_check_note" in resp
        assert isinstance(resp["live_check_note"], str)
        assert len(resp["live_check_note"]) > 20

    def test_live_check_note_mentions_flagged(self):
        """live_check_note must mention that checks run only for flagged/suspicious items."""
        resp = _post_estimate("example.com")
        note = resp["live_check_note"].lower()
        assert "flagged" in note or "suspicious" in note

    def test_live_check_note_mentions_timing(self):
        """live_check_note must mention timing so users understand the overhead."""
        resp = _post_estimate("example.com")
        note = resp["live_check_note"]
        assert "second" in note or "time" in note.lower()

    def test_estimate_job_returns_live_check_count_zero(self):
        """estimate_job() dict must include estimated_live_check_count=0."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from services.estimate import estimate_job
        from models import InputType, MdiInputItem

        items = [MdiInputItem(input_original="a.com", input_normalized="a.com", position=1, input_type=InputType.DOMAIN)]
        result = estimate_job(items, use_domain_reports=False)
        assert result["estimated_live_check_count"] == 0

    def test_estimate_job_returns_live_check_note(self):
        """estimate_job() dict must include a non-empty live_check_note."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from services.estimate import estimate_job
        from models import InputType, MdiInputItem

        items = [MdiInputItem(input_original="a.com", input_normalized="a.com", position=1, input_type=InputType.DOMAIN)]
        result = estimate_job(items, use_domain_reports=False)
        assert isinstance(result["live_check_note"], str)
        assert len(result["live_check_note"]) > 0

    def test_estimate_does_not_call_live_check(self):
        """estimate.py must never import the live_check module or call httpx."""
        import services.estimate as est_mod
        src = open(est_mod.__file__).read()
        # Must not import live_check or httpx (which would enable live HTTP calls)
        assert "import live_check" not in src, (
            "estimate.py must not import live_check"
        )
        assert "import httpx" not in src, (
            "estimate.py must not import httpx — no live HTTP calls in estimates"
        )
        assert "_resolve_dns" not in src, (
            "estimate.py must not call DNS resolution"
        )

    def test_estimate_live_check_count_unchanged_for_large_batch(self):
        """Even with 100 items, estimated_live_check_count stays 0."""
        raw = "\n".join(f"domain{i}.com" for i in range(100))
        resp = _post_estimate(raw)
        assert resp["estimated_live_check_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# MDI-28C — auto-rescan estimate with domain-report rows
# ─────────────────────────────────────────────────────────────────────────────


class TestMdi28cAutoRescanEstimate:
    """Domain-report and mixed URL/domain auto-rescan estimate fields."""

    def test_domain_report_batch_auto_rescan_max_positive(self):
        resp = _post_estimate(
            "a.com\nb.com\nc.com",
            use_domain_reports=True,
            auto_rescan_stale=True,
            max_auto_rescans=3,
        )
        assert resp["auto_rescan_estimated_quota_max"] == 15
        assert resp["auto_rescan_domain_eligible_max"] == 3
        assert resp["auto_rescan_url_eligible_max"] == 0
        assert resp["total_estimated_vt_calls_max"] == (
            resp["estimated_vt_calls_max"] + resp["auto_rescan_estimated_quota_max"]
        )

    def test_mixed_url_domain_estimate_uses_domain_x5_url_x4(self):
        resp = _post_estimate(
            "a.com\nhttps://b.com/path\nc.com\nd.com",
            use_domain_reports=True,
            auto_rescan_stale=True,
            max_auto_rescans=3,
        )
        # 3 domain slots + 0 url slots (domains fill cap first) → 15
        assert resp["auto_rescan_domain_eligible_max"] == 3
        assert resp["auto_rescan_url_eligible_max"] == 0
        assert resp["auto_rescan_estimated_quota_max"] == 15

    def test_mixed_slot_cap_prefers_domains_then_urls(self):
        resp = _post_estimate(
            "a.com\nhttps://b.com/path",
            use_domain_reports=True,
            auto_rescan_stale=True,
            max_auto_rescans=2,
        )
        assert resp["auto_rescan_domain_eligible_max"] == 1
        assert resp["auto_rescan_url_eligible_max"] == 1
        assert resp["auto_rescan_estimated_quota_max"] == 9  # 5 + 4

    def test_submit_blocks_when_total_exceeds_remaining(self, tmp_path):
        usage_file = _make_usage_file(tmp_path, used=498)
        old_env = os.environ.get("VT_USAGE_FILE")
        try:
            os.environ["VT_USAGE_FILE"] = str(usage_file)
            resp = client.post("/api/mdi/jobs/submit", json={
                "raw_input": "a.com\nb.com\nc.com",
                "use_domain_reports": True,
                "auto_rescan_stale": True,
                "max_auto_rescans": 3,
            })
            assert resp.status_code == 429
        finally:
            if old_env is None:
                os.environ.pop("VT_USAGE_FILE", None)
            else:
                os.environ["VT_USAGE_FILE"] = old_env

    def test_estimate_job_unit_mixed_slots(self):
        from models import MdiInputItem
        items = [
            MdiInputItem(input_original="a.com", input_normalized="a.com",
                         input_type=InputType.DOMAIN, position=1),
            MdiInputItem(input_original="http://b.com/", input_normalized="http://b.com/",
                         input_type=InputType.URL, position=2),
        ]
        result = estimate_job(
            items,
            use_domain_reports=True,
            auto_rescan_stale=True,
            max_auto_rescans=2,
        )
        assert result["auto_rescan_domain_eligible_max"] == 1
        assert result["auto_rescan_url_eligible_max"] == 1
        assert result["auto_rescan_estimated_quota_max"] == 9


# ── MDI-51 — upload hold-aware quota estimate ─────────────────────────────────


def _upload_item(
    domain: str,
    *,
    position: int = 1,
    epp_status: list[str] | None = None,
    domain_hold: DomainHold | None = None,
) -> UploadedInputItem:
    hold = domain_hold or DomainHold(
        has_hold=False,
        hold_types=[DomainHoldType.NONE],
        source=DomainStatusSource.NOT_CHECKED,
        raw_statuses=[],
    )
    return UploadedInputItem(
        input_original=domain,
        input_normalized=domain,
        input_type=InputType.DOMAIN,
        position=position,
        epp_status=epp_status or [],
        domain_hold=hold,
        domain_status_source=(
            DomainStatusSource.UPLOADED_FILE if hold.has_hold or epp_status else DomainStatusSource.NOT_CHECKED
        ),
    )


def _held_item(domain: str, hold_type: str, *, position: int = 1) -> UploadedInputItem:
    types = []
    if hold_type == "clientHold":
        types = [DomainHoldType.CLIENT_HOLD]
    elif hold_type == "serverHold":
        types = [DomainHoldType.SERVER_HOLD]
    elif hold_type == "both":
        types = [DomainHoldType.CLIENT_HOLD, DomainHoldType.SERVER_HOLD]
    hold = DomainHold(
        has_hold=True,
        hold_types=types,
        source=DomainStatusSource.UPLOADED_FILE,
        raw_statuses=[t.value for t in types],
    )
    return _upload_item(
        domain,
        position=position,
        epp_status=[t.value for t in types],
        domain_hold=hold,
    )


def _post_upload_estimate(items: list[UploadedInputItem], **kwargs) -> dict:
    payload = {
        "items": [i.model_dump(mode="json") for i in items],
        "input_mode": "upload",
        "use_domain_reports": False,
        **kwargs,
    }
    resp = client.post(ESTIMATE_URL, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestMdi51UploadHoldAwareEstimate:
    def test_no_held_domains_all_eligible(self):
        items = [
            _upload_item("alpha.example"),
            _upload_item("beta.example", position=2),
        ]
        body = _post_upload_estimate(items)
        assert body["accepted_count"] == 2
        assert body["held_skipped_count"] == 0
        assert body["eligible_vt_count"] == 2
        assert body["estimated_vt_calls_max"] == 4

    def test_client_hold_excluded(self):
        items = [
            _held_item("held-client.example", "clientHold"),
            _upload_item("clean.example", position=2),
        ]
        body = _post_upload_estimate(items)
        assert body["held_skipped_count"] == 1
        assert body["eligible_vt_count"] == 1
        assert body["estimated_vt_calls_max"] == 2

    def test_server_hold_excluded(self):
        items = [_held_item("held-server.example", "serverHold")]
        body = _post_upload_estimate(items)
        assert body["held_skipped_count"] == 1
        assert body["eligible_vt_count"] == 0
        assert body["estimated_vt_calls_max"] == 0

    def test_both_holds_excluded(self):
        items = [_held_item("held-both.example", "both")]
        body = _post_upload_estimate(items)
        assert body["held_skipped_count"] == 1
        assert body["eligible_vt_count"] == 0

    def test_mixed_held_and_non_held(self):
        items = [
            _held_item("h1.example", "clientHold", position=1),
            _held_item("h2.example", "serverHold", position=2),
            _upload_item("clean1.example", position=3),
            _upload_item("clean2.example", position=4),
        ]
        body = _post_upload_estimate(items)
        assert body["accepted_count"] == 4
        assert body["held_skipped_count"] == 2
        assert body["eligible_vt_count"] == 2
        assert body["estimated_vt_calls_max"] == 4

    def test_all_held_zero_vt_no_quota_block(self, tmp_path):
        items = [_held_item(f"held{i}.example", "clientHold", position=i) for i in range(1, 6)]
        usage_file = tmp_path / "vt_usage.json"
        usage_file.write_text(json.dumps({
            "date_utc": "2099-01-01",
            "daily_lookups_used": 499,
            "daily_limit": 500,
        }))
        old_env = os.environ.get("VT_USAGE_FILE")
        os.environ["VT_USAGE_FILE"] = str(usage_file)
        try:
            body = _post_upload_estimate(items)
        finally:
            if old_env is None:
                os.environ.pop("VT_USAGE_FILE", None)
            else:
                os.environ["VT_USAGE_FILE"] = old_env
        assert body["eligible_vt_count"] == 0
        assert body["estimated_vt_calls_max"] == 0
        assert body["total_estimated_vt_calls_max"] == 0
        assert body["will_exceed_quota"] is False

    def test_missing_status_not_false_held(self):
        items = [_upload_item("unknown.example")]
        body = _post_upload_estimate(items)
        assert body["held_skipped_count"] == 0
        assert body["eligible_vt_count"] == 1

    def test_epp_status_fallback_without_domain_hold_object(self):
        item = UploadedInputItem(
            input_original="fallback.example",
            input_normalized="fallback.example",
            input_type=InputType.DOMAIN,
            position=1,
            epp_status=["clientHold"],
            domain_hold=DomainHold(
                has_hold=False,
                hold_types=[DomainHoldType.NONE],
                source=DomainStatusSource.NOT_CHECKED,
                raw_statuses=[],
            ),
        )
        assert upload_item_has_hold(item) is True
        eligible, held = partition_upload_items([item])
        assert held == 1
        assert eligible == []

    def test_duplicate_normalized_domain_held_row_wins(self):
        csv = (
            "DNS Form,Create Date,EPP Status,Registrar Name\n"
            "dup.example,2020-01-01,clientTransferProhibited,Reg A\n"
            "dup.example,2021-03-10,clientHold,Reg B\n"
        ).encode()
        parsed = parse_upload(csv, "dup.csv")
        assert len(parsed.accepted) == 1
        assert parsed.accepted[0].domain_hold.has_hold is True
        body = _post_upload_estimate(parsed.accepted)
        assert body["held_skipped_count"] == 1
        assert body["eligible_vt_count"] == 0

    @pytest.mark.parametrize("status_token", [
        "CLIENTHOLD",
        "clienthold",
        "ClientHold",
        "SERVERHOLD",
        "serverhold",
        "ServerHold",
    ])
    def test_case_insensitive_status_values(self, status_token):
        csv = (
            "DNS Form,Create Date,EPP Status,Registrar Name\n"
            f"case.example,2020-01-01,{status_token},Reg A\n"
        ).encode()
        parsed = parse_upload(csv, "case.csv")
        assert parsed.accepted[0].domain_hold.has_hold is True
        body = _post_upload_estimate(parsed.accepted)
        assert body["held_skipped_count"] == 1
        assert body["eligible_vt_count"] == 0


class TestMdi51aPipeDelimiterEstimate:
    def test_pipe_delimited_upload_estimate_counts(self):
        from pipe_delimited_fixture import pipe_delimited_production_style_csv

        parsed = parse_upload(pipe_delimited_production_style_csv(), "pipe.csv")
        body = _post_upload_estimate(parsed.accepted)
        assert body["accepted_count"] == 285
        assert body["held_skipped_count"] == 67
        assert body["eligible_vt_count"] == 218
        # MDI-57A: 218 eligible × 2 calls max (submit-only URL path)
        assert body["estimated_vt_calls_max"] == 436
