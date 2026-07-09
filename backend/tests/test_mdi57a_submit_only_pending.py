"""
MDI-57A — Submit-only pending URL state, VT response-shape correctness,
quota estimate parity, pending-result truthfulness, and 30-day stale default.

All VT HTTP calls are mocked (services.vt_service._vt_request patched).
No live VT / external calls. No quota consumed. No runtime files written
(all file I/O uses tmp_path). No jobs submitted against production.

Response shapes modeled here (verified against the VT v3 contract):
  - URL report GET 404      → {"error": {"code": "NotFoundError"}} — no report,
                              NOT clean, NOT 0/N.
  - POST /urls submit 200   → {"data": {"id": "<analysis-id>", "type": "analysis"}}
                              — an analysis descriptor, NOT a completed URL report.
  - Completed URL report    → data.attributes.last_analysis_date present AND
                              last_analysis_stats engine total > 0.
  - Pending 200 URL report  → 200 with empty/zero last_analysis_stats and no
                              last_analysis_date — analysis not complete.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.vt_service as vt_svc
from models import (
    EvidenceStatus,
    Freshness,
    InputType,
    LiveStatus,
    MdiProcessingStatus,
    MdiResultItem,
    RecommendedAction,
    TriageBucket,
    TriageConfidence,
    VtModeUsed,
)
from services import job_store, triage_rules
from services.job_store import InMemoryJob
from services.vt_service import classify_freshness, report_is_completed, very_stale_after_days

# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _no_limiter():
    return patch.object(vt_svc._VT_LIMITER, "acquire", new=AsyncMock())


def _mock_resp(status_code: int, body: dict = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    return m


def _completed_url_report(malicious: int = 0, suspicious: int = 0, harmless: int = 70,
                          undetected: int = 5, age_days: int = 1) -> dict:
    """A genuinely completed URL report: scan date present, engine total > 0."""
    return {
        "data": {
            "attributes": {
                "last_analysis_stats": {
                    "malicious": malicious,
                    "suspicious": suspicious,
                    "harmless": harmless,
                    "undetected": undetected,
                    "timeout": 0,
                },
                "last_analysis_date": int(time.time()) - age_days * 86400,
            }
        }
    }


def _empty_pending_url_report() -> dict:
    """200 URL report whose analysis has not completed: zero stats, no scan date."""
    return {
        "data": {
            "attributes": {
                "last_analysis_stats": {
                    "malicious": 0, "suspicious": 0, "harmless": 0,
                    "undetected": 0, "timeout": 0,
                },
                # no last_analysis_date
                "times_submitted": 1,
            }
        }
    }


_NOT_FOUND_BODY = {"error": {"code": "NotFoundError", "message": "URL not found"}}
_SUBMIT_ANALYSIS_BODY = {"data": {"id": "u-1234abcd-1720000000", "type": "analysis"}}


def _pending_result_item(position: int = 1, url: str = "http://pending.example/") -> MdiResultItem:
    """Build the persisted row shape produced by a submit-only pending lookup."""
    pending_err = vt_svc._pending_error(vt_svc._PENDING_SUBMITTED_MSG)
    return MdiResultItem(
        input_original=url,
        input_normalized=url,
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
        triage_confidence=TriageConfidence.UNKNOWN,
        recommended_action=RecommendedAction.REFRESH_REPORT,
        evidence_status=EvidenceStatus.PARTIAL,
        triage_reason=triage_rules._pending_analysis_reason(),
        live_status=LiveStatus.NOT_CHECKED,
        errors=[pending_err],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. URL report not found → submit-only, exactly 2 calls, pending, not clean
# ─────────────────────────────────────────────────────────────────────────────

class TestSubmitOnlyNotFound:

    def _fetch_404_then_submit(self):
        calls_log = []

        async def side(method, url, *, headers, data=None):
            calls_log.append((method, url))
            if method == "GET":
                return _mock_resp(404, _NOT_FOUND_BODY)
            return _mock_resp(200, _SUBMIT_ANALYSIS_BODY)

        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=side), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.fetch_report("http://new-url.example/", InputType.URL))
        return result, calls_log

    def test_exactly_two_calls_no_third_get(self):
        result, calls_log = self._fetch_404_then_submit()
        assert result.calls_made == 2
        assert len(calls_log) == 2
        assert calls_log[0][0] == "GET"
        assert calls_log[1][0] == "POST"
        assert calls_log[1][1].endswith("/urls")

    def test_result_is_pending_not_clean(self):
        result, _ = self._fetch_404_then_submit()
        assert result.error is not None
        assert result.error.code == "vt_scan_pending"
        assert result.error.severity == "warning"
        assert result.error.blocks_triage is False
        assert result.vt_total_engines == 0
        assert result.vt_scan_date is None
        assert result.freshness == Freshness.NEVER_SCANNED
        # never a visible 0/0
        assert result.vt_ratio == ""
        # Triage must not classify this as clean
        dec = triage_rules.decide(triage_rules.TriageInput(
            processing_status=MdiProcessingStatus.DONE,
            vt_hits=0, vt_suspicious=0, vt_total_engines=0,
            freshness=Freshness.NEVER_SCANNED,
            errors=[result.error],
        ))
        assert dec.triage_bucket == TriageBucket.PENDING
        assert dec.triage_bucket != TriageBucket.CLEAN

    def test_404_not_treated_as_zero_detection_report(self):
        """VT not-found must be distinguishable from a completed 0-detection report."""
        result, _ = self._fetch_404_then_submit()
        assert not report_is_completed(result)
        assert result.vt_total_engines == 0  # no fabricated 0/92


# ─────────────────────────────────────────────────────────────────────────────
# 2. Submit response shape — analysis id is not a completed URL report
# ─────────────────────────────────────────────────────────────────────────────

class TestSubmitResponseShape:

    def test_submit_analysis_id_not_parsed_as_report(self):
        result, _calls = TestSubmitOnlyNotFound()._fetch_404_then_submit()
        # The analysis-id body must not populate report evidence fields.
        assert result.vt_total_engines == 0
        assert result.vt_hits == 0
        assert result.vt_scan_date is None
        assert result.engine_detections == []
        assert result.error is not None and result.error.code == "vt_scan_pending"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Completed zero-detection URL report → clean-equivalent per existing rules
# ─────────────────────────────────────────────────────────────────────────────

class TestCompletedZeroDetection:

    def test_completed_zero_detection_is_clean(self):
        body = _completed_url_report(malicious=0, suspicious=0)
        mock_req = AsyncMock(return_value=_mock_resp(200, body))
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=mock_req), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.fetch_report("http://known-clean.example/", InputType.URL))

        assert result.error is None
        assert result.calls_made == 1
        assert report_is_completed(result)
        assert result.vt_total_engines == 75
        dec = triage_rules.decide(triage_rules.TriageInput(
            processing_status=MdiProcessingStatus.DONE,
            vt_hits=0, vt_suspicious=0, vt_total_engines=result.vt_total_engines,
            freshness=result.freshness,
        ))
        assert dec.triage_bucket == TriageBucket.CLEAN
        assert dec.recommended_action == RecommendedAction.NO_ACTION_BASED_ON_VT


# ─────────────────────────────────────────────────────────────────────────────
# 4. Empty/incomplete 200 URL report → pending/partial, not clean
# ─────────────────────────────────────────────────────────────────────────────

class TestEmpty200Report:

    def test_200_with_empty_stats_is_pending_not_clean(self):
        mock_req = AsyncMock(return_value=_mock_resp(200, _empty_pending_url_report()))
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=mock_req), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.fetch_report("http://queued.example/", InputType.URL))

        assert result.calls_made == 1
        assert result.error is not None
        assert result.error.code == "vt_scan_pending"
        assert result.vt_total_engines == 0
        assert result.vt_ratio == ""
        assert result.freshness == Freshness.NEVER_SCANNED

    def test_stats_without_scan_date_not_provably_complete(self):
        """Malformed/partial: stats present but no scan date → not completed evidence."""
        body = _completed_url_report(malicious=0)
        del body["data"]["attributes"]["last_analysis_date"]
        mock_req = AsyncMock(return_value=_mock_resp(200, body))
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=mock_req), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.fetch_report("http://partial.example/", InputType.URL))

        assert result.error is not None
        assert result.error.code == "vt_scan_pending"

    def test_domain_report_mode_unchanged(self):
        """Completedness gating applies to URL mode only; domain mode is untouched."""
        body = _completed_url_report(malicious=0)
        mock_req = AsyncMock(return_value=_mock_resp(200, body))
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=mock_req), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.fetch_report(
                "example.com", InputType.DOMAIN, use_domain_reports=True,
            ))
        assert result.error is None
        assert result.vt_mode_used == VtModeUsed.DOMAIN_REPORT
        assert result.calls_made == 1


# ─────────────────────────────────────────────────────────────────────────────
# 5. Cached malicious URL report → 1 GET, flagged, calls_made=1
# ─────────────────────────────────────────────────────────────────────────────

class TestCachedFlagged:

    def test_cached_malicious_one_call(self):
        body = _completed_url_report(malicious=5, suspicious=2, harmless=63)
        mock_req = AsyncMock(return_value=_mock_resp(200, body))
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=mock_req), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.fetch_report("http://evil.example/", InputType.URL))

        assert result.calls_made == 1
        mock_req.assert_called_once()
        assert result.error is None
        assert result.vt_malicious == 5
        assert result.vt_suspicious == 2
        dec = triage_rules.decide(triage_rules.TriageInput(
            processing_status=MdiProcessingStatus.DONE,
            vt_hits=5, vt_suspicious=2, vt_total_engines=result.vt_total_engines,
            freshness=result.freshness,
        ))
        assert dec.triage_bucket == TriageBucket.MALICIOUS


# ─────────────────────────────────────────────────────────────────────────────
# 6. Failed submit → structured error visible, no clean classification
# ─────────────────────────────────────────────────────────────────────────────

class TestFailedSubmit:

    def _fetch_with_submit_status(self, submit_status: int):
        calls_log = []

        async def side(method, url, *, headers, data=None):
            calls_log.append(method)
            if method == "GET":
                return _mock_resp(404, _NOT_FOUND_BODY)
            return _mock_resp(submit_status, {})

        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=side), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.fetch_report("http://fail.example/", InputType.URL))
        return result, calls_log

    def test_submit_500_structured_error(self):
        result, calls_log = self._fetch_with_submit_status(500)
        assert result.calls_made == 2
        assert calls_log == ["GET", "POST"]
        assert result.error is not None
        assert result.error.code == "vt_submit_error"
        dec = triage_rules.decide(triage_rules.TriageInput(
            processing_status=MdiProcessingStatus.ERROR,
            vt_hits=0, vt_suspicious=0, vt_total_engines=0,
            errors=[result.error],
        ))
        assert dec.triage_bucket == TriageBucket.ERROR
        assert dec.triage_bucket != TriageBucket.CLEAN

    def test_submit_429_structured_error(self):
        result, _ = self._fetch_with_submit_status(429)
        assert result.calls_made == 2
        assert result.error is not None
        assert result.error.code == "vt_429"
        assert result.error.retriable is True


# ─────────────────────────────────────────────────────────────────────────────
# 7. Pending-analysis state design (triage / evidence / action / reason)
# ─────────────────────────────────────────────────────────────────────────────

class TestPendingAnalysisState:

    def _decision(self):
        pending_err = vt_svc._pending_error(vt_svc._PENDING_SUBMITTED_MSG)
        return triage_rules.decide(triage_rules.TriageInput(
            processing_status=MdiProcessingStatus.DONE,
            vt_hits=0, vt_suspicious=0, vt_total_engines=0,
            freshness=Freshness.NEVER_SCANNED,
            errors=[pending_err],
        )), pending_err

    def test_recommended_action_is_refresh_report(self):
        dec, _ = self._decision()
        assert dec.recommended_action == RecommendedAction.REFRESH_REPORT

    def test_bucket_confidence_evidence(self):
        dec, _ = self._decision()
        assert dec.triage_bucket == TriageBucket.PENDING
        assert dec.triage_confidence == TriageConfidence.UNKNOWN
        assert dec.evidence_status == EvidenceStatus.PARTIAL

    def test_warning_code_attached(self):
        _, err = self._decision()
        assert err.code == "vt_scan_pending"
        assert err.severity == "warning"

    def test_reason_text_truthful(self):
        dec, _ = self._decision()
        reason = " ".join(dec.triage_reason).lower()
        assert "submitted to virustotal" in reason
        assert "not a clean result" in reason
        assert "refresh report" in reason
        assert "request new scan" not in reason

    def test_end_to_end_job_row_is_pending_done(self, tmp_path):
        """Full job_processor path: submit-only pending row lands as DONE + PENDING."""
        from services import domain_enrichment, job_processor, live_check
        from services.domain_enrichment import EnrichmentResult
        from services.live_check import LiveCheckResult
        from models import DomainHold, DomainHoldType, DomainStatusSource

        job_id = "mdi57a-pending-" + str(time.time_ns())
        url = "http://brand-new.example/login"
        job = InMemoryJob(
            job_id=job_id, status="queued", submitted_at=time.time(), total=1,
        )
        job.results[url] = MdiResultItem(
            input_original=url, input_normalized=url,
            input_type=InputType.URL, position=1,
            processing_status=MdiProcessingStatus.PENDING,
        )
        job.item_order.append(url)
        _run(job_store.create_job(job))

        async def side(method, u, *, headers, data=None):
            if method == "GET":
                return _mock_resp(404, _NOT_FOUND_BODY)
            return _mock_resp(200, _SUBMIT_ANALYSIS_BODY)

        usage_file = tmp_path / "vt_usage.json"
        usage_file.write_text('{"date_utc": "2099-01-01", "daily_lookups_used": 0}')
        noop_enrich = EnrichmentResult(
            registered_domain="brand-new.example",
            source=DomainStatusSource.NOT_CHECKED,
            domain_hold=DomainHold(
                has_hold=False, hold_types=[DomainHoldType.NONE],
                source=DomainStatusSource.NOT_CHECKED,
            ),
        )

        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=side), \
             patch.object(domain_enrichment, "enrich_domain",
                          new=AsyncMock(return_value=noop_enrich)), \
             patch.object(live_check, "live_check_item",
                          new=AsyncMock(return_value=LiveCheckResult(live_status=LiveStatus.NOT_CHECKED))), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            _run(job_processor.process_job(
                job_id, usage_file=usage_file, job_file=tmp_path / "mdi_latest_job.json",
            ))

        done = job_store.get_job_sync(job_id)
        row = done.results[url]
        assert row.processing_status == MdiProcessingStatus.DONE
        assert row.triage_bucket == TriageBucket.PENDING
        assert row.recommended_action == RecommendedAction.REFRESH_REPORT
        assert row.evidence_status == EvidenceStatus.PARTIAL
        assert row.freshness == Freshness.NEVER_SCANNED
        assert any(e.code == "vt_scan_pending" for e in row.errors)
        assert row.vt_ratio in ("", None)
        # Quota: exactly 2 calls consumed
        usage = json.loads(usage_file.read_text())
        assert usage["daily_lookups_used"] == 2
        job_store.clear_all_jobs()


# ─────────────────────────────────────────────────────────────────────────────
# 8. Estimate model — URL worst case 2, guard parity, copy
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimateModel:

    def test_url_mode_max_is_2(self):
        from services.estimate import estimate_calls_for_item
        assert estimate_calls_for_item(InputType.URL, use_domain_reports=False) == (1, 2)
        assert estimate_calls_for_item(InputType.DOMAIN, use_domain_reports=False) == (1, 2)

    def test_cached_min_remains_1_and_domain_mode_unchanged(self):
        from services.estimate import estimate_calls_for_item
        assert estimate_calls_for_item(InputType.DOMAIN, use_domain_reports=True) == (1, 1)

    def test_submit_guard_matches_estimate(self):
        from models import MdiInputItem
        from routers.mdi import _estimate_requests
        from services.estimate import estimate_job
        items = [
            MdiInputItem(input_original="a.com", input_normalized="a.com",
                         input_type=InputType.DOMAIN, position=1),
            MdiInputItem(input_original="http://b.com/", input_normalized="http://b.com/",
                         input_type=InputType.URL, position=2),
        ]
        est = estimate_job(items, use_domain_reports=False)
        assert est["estimated_vt_calls_max"] == 4
        assert _estimate_requests(items, use_domain_reports=False) == est["total_estimated_vt_calls_max"]

    def test_url_submit_note_present_and_truthful(self):
        from services.estimate import URL_SUBMIT_NOTE, estimate_job
        from models import MdiInputItem
        items = [MdiInputItem(input_original="http://a.com/", input_normalized="http://a.com/",
                              input_type=InputType.URL, position=1)]
        est = estimate_job(items, use_domain_reports=False)
        note = est["url_submit_note"]
        assert note == URL_SUBMIT_NOTE
        low = note.lower()
        assert "submit" in low
        assert "refresh report" in low
        assert "no automatic" in low
        # Must not claim an immediate report is available
        assert "immediate" not in low

    def test_url_submit_note_empty_for_pure_domain_mode(self):
        from services.estimate import estimate_job
        from models import MdiInputItem
        items = [MdiInputItem(input_original="a.com", input_normalized="a.com",
                              input_type=InputType.DOMAIN, position=1)]
        est = estimate_job(items, use_domain_reports=True)
        assert est["url_submit_note"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# 9. Refresh pending later — 1 GET, completed report reprocesses into triage
# ─────────────────────────────────────────────────────────────────────────────

class TestRefreshPendingLater:

    def test_refresh_completed_report_one_call(self):
        body = _completed_url_report(malicious=0, suspicious=0)
        mock_req = AsyncMock(return_value=_mock_resp(200, body))
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=mock_req), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.refresh_report("http://pending.example/", InputType.URL))

        assert result.calls_made == 1
        mock_req.assert_called_once()
        assert result.error is None
        assert report_is_completed(result)

    def test_refresh_reprocesses_pending_row_into_normal_triage(self):
        from services import job_actions
        job = InMemoryJob(job_id="mdi57a-refresh", status="done",
                          submitted_at=time.time(), total=1)
        row = _pending_result_item()
        vt_result = vt_svc.parse_vt_response(
            _completed_url_report(malicious=0, suspicious=0),
            VtModeUsed.URL_REPORT,
        )
        vt_result.calls_made = 1
        updated = _run(job_actions.reprocess_item_after_vt(
            job, row, vt_result, rerun_live_check=False,
        ))
        assert updated.triage_bucket == TriageBucket.CLEAN
        assert updated.vt_total_engines == 75
        # The vt_scan_pending warning is cleared on successful refresh
        assert not any(e.code == "vt_scan_pending" for e in (updated.errors or []))

    def test_refresh_still_pending_stays_pending(self):
        mock_req = AsyncMock(return_value=_mock_resp(200, _empty_pending_url_report()))
        with _no_limiter(), \
             patch("services.vt_service._vt_request", new=mock_req), \
             patch.dict(os.environ, {"VT_API_KEY": "testkey"}):
            result = _run(vt_svc.refresh_report("http://still-pending.example/", InputType.URL))

        assert result.calls_made == 1
        assert result.error is not None
        assert result.error.code == "vt_scan_pending"


# ─────────────────────────────────────────────────────────────────────────────
# 10. Stale threshold default 30
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleDefault30:

    def test_vt_service_default(self):
        assert vt_svc.DEFAULT_STALE_THRESHOLD_DAYS == 30

    def test_job_submit_request_default(self):
        from models import JobSubmitRequest
        assert JobSubmitRequest(raw_input="a.com").stale_threshold_days == 30

    def test_estimate_request_default(self):
        from models import EstimateRequest
        assert EstimateRequest(raw_input="a.com").stale_threshold_days == 30

    def test_job_options_default(self):
        from models import MdiJobOptions
        assert MdiJobOptions().stale_threshold_days == 30

    def test_in_memory_job_default(self):
        job = InMemoryJob(job_id="d", status="queued", submitted_at=time.time())
        assert job.stale_threshold_days == 30

    def test_triage_input_default(self):
        assert triage_rules.TriageInput().stale_threshold_days == 30

    def test_frontend_default_constant_is_30(self):
        """Source-level check of the frontend DEFAULT_SETTINGS constant."""
        app_jsx = Path(__file__).parent.parent.parent / "frontend" / "src" / "App.jsx"
        if not app_jsx.exists():
            pytest.skip("frontend source not present")
        src = app_jsx.read_text()
        import re
        m = re.search(r"DEFAULT_SETTINGS\s*=\s*\{[^}]*stale_threshold_days:\s*(\d+)", src)
        assert m, "DEFAULT_SETTINGS.stale_threshold_days not found in App.jsx"
        assert int(m.group(1)) == 30

    def test_operator_can_still_override(self):
        from models import JobSubmitRequest
        assert JobSubmitRequest(raw_input="a.com", stale_threshold_days=7).stale_threshold_days == 7
        assert JobSubmitRequest(raw_input="a.com", stale_threshold_days=90).stale_threshold_days == 90


# ─────────────────────────────────────────────────────────────────────────────
# 11. Recovery — saved threshold kept; legacy missing threshold → 30
# ─────────────────────────────────────────────────────────────────────────────

class TestRecoveryThreshold:

    def _minimal_job_dict(self, **overrides) -> dict:
        from services import job_persistence
        job = InMemoryJob(
            job_id="recov-1", status="done", submitted_at=time.time() - 60,
            completed_at=time.time(), total=0, stale_threshold_days=7,
        )
        data = job_persistence.serialize_job(job)
        data.update(overrides)
        return data

    def test_saved_threshold_7_is_kept(self):
        from services import job_persistence
        data = self._minimal_job_dict()
        recovered = job_persistence.deserialize_job(data)
        assert recovered.stale_threshold_days == 7

    def test_missing_threshold_falls_back_to_30(self):
        from services import job_persistence
        data = self._minimal_job_dict()
        data.pop("stale_threshold_days", None)
        recovered = job_persistence.deserialize_job(data)
        assert recovered.stale_threshold_days == 30


# ─────────────────────────────────────────────────────────────────────────────
# 12. Freshness boundaries — very_stale_after_days = max(2×threshold, 30)
# ─────────────────────────────────────────────────────────────────────────────

def _ts_days_ago(days: float) -> int:
    return int(time.time() - days * 86400)


class TestFreshnessBoundaries:

    def test_very_stale_after_days_formula(self):
        assert very_stale_after_days(30) == 60
        assert very_stale_after_days(7) == 30   # max(14, 30)
        assert very_stale_after_days(45) == 90
        assert very_stale_after_days(1) == 30
        assert very_stale_after_days(15) == 30
        assert very_stale_after_days(16) == 32

    def test_threshold_30_bands(self):
        t = 30
        assert classify_freshness(_ts_days_ago(29), t) == Freshness.FRESH
        assert classify_freshness(_ts_days_ago(30.1), t) == Freshness.STALE
        # 60 days is inclusive-stale; probe just inside the band to avoid
        # float-clock drift pushing an exact 60-day timestamp over the edge.
        assert classify_freshness(_ts_days_ago(59.99), t) == Freshness.STALE
        assert classify_freshness(_ts_days_ago(61), t) == Freshness.VERY_STALE

    def test_threshold_7_bands(self):
        t = 7
        assert classify_freshness(_ts_days_ago(6), t) == Freshness.FRESH
        assert classify_freshness(_ts_days_ago(8), t) == Freshness.STALE
        # boundary stays 30 because max(14, 30) = 30
        assert classify_freshness(_ts_days_ago(29), t) == Freshness.STALE
        assert classify_freshness(_ts_days_ago(31), t) == Freshness.VERY_STALE

    def test_threshold_45_bands(self):
        t = 45
        assert classify_freshness(_ts_days_ago(44), t) == Freshness.FRESH
        assert classify_freshness(_ts_days_ago(46), t) == Freshness.STALE
        assert classify_freshness(_ts_days_ago(89), t) == Freshness.STALE
        assert classify_freshness(_ts_days_ago(91), t) == Freshness.VERY_STALE

    def test_never_scanned_unchanged(self):
        assert classify_freshness(None, 30) == Freshness.NEVER_SCANNED
        assert classify_freshness(0, 30) == Freshness.NEVER_SCANNED


# ─────────────────────────────────────────────────────────────────────────────
# 13. Exports — pending rows are pending_analysis, never clean, never 0/0
# ─────────────────────────────────────────────────────────────────────────────

class TestPendingExports:

    def test_result_column_pending_analysis(self):
        from services.export_service import format_export_result
        row = _pending_result_item()
        assert format_export_result(row) == "pending_analysis"

    def test_pending_never_exports_clean_or_error(self):
        from services.export_service import format_export_result
        value = format_export_result(_pending_result_item())
        assert value not in ("clean", "error", "flagged", "unknown")

    def test_detection_ratio_blank_not_0_0(self):
        from services.export_service import format_detection_ratio_plain
        ratio = format_detection_ratio_plain(_pending_result_item())
        assert ratio == ""
        assert ratio != "0/0"

    def test_last_scanned_blank(self):
        from services.export_service import format_last_scanned
        assert format_last_scanned(_pending_result_item()) == ""

    def test_json_evidence_preserves_pending_state(self):
        from services.export_service import _result_json
        payload = _result_json(_pending_result_item())
        assert payload["pending_analysis"] is True
        assert "vt_scan_pending" in payload["error_codes"]
        assert payload["triage_bucket"] == "pending"
        assert payload["recommended_action"] == "refresh_report"
        assert payload["evidence_status"] == "partial"
        assert payload["freshness"] == "never_scanned"
        assert payload["vt_ratio"] in ("", None)

    def test_json_distinguishes_pending_from_completed_clean(self):
        from services.export_service import _result_json, format_export_result
        clean_row = _pending_result_item().model_copy(update={
            "vt_total_engines": 75,
            "vt_ratio": "0/75",
            "vt_scan_date": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            "freshness": Freshness.FRESH,
            "triage_bucket": TriageBucket.CLEAN,
            "recommended_action": RecommendedAction.NO_ACTION_BASED_ON_VT,
            "evidence_status": EvidenceStatus.COMPLETE,
            "errors": [],
        })
        assert _result_json(clean_row)["pending_analysis"] is False
        assert format_export_result(clean_row) == "clean"

    def test_export_makes_no_external_calls(self):
        """export_service must not import httpx or call VT."""
        import inspect
        import services.export_service as exp_mod
        src = inspect.getsource(exp_mod)
        assert "httpx" not in src
        assert "_vt_request" not in src
