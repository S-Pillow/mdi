"""
MDI-22A error taxonomy and triage-blocking behavior tests.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from models import (
    AgeBucket,
    Freshness,
    InputType,
    LiveStatus,
    MdiError,
    MdiProcessingStatus,
    MdiResultItem,
    RecommendedAction,
    TriageBucket,
)
from services import job_persistence, job_processor, job_store, triage_rules
from services.error_taxonomy import (
    ErrorCategory,
    ErrorSeverity,
    error_blocks_triage,
    has_blocking_errors,
    infer_error_category,
    infer_error_severity,
    make_mdi_error,
    normalize_error_code,
)
from services.triage_rules import TriageInput, decide


# ── Model / taxonomy helpers ───────────────────────────────────────────────────


def test_old_mdi_error_shape_loads_and_infers_taxonomy():
    err = MdiError.model_validate({
        "code": "vt_429",
        "message": "Rate limited",
        "source": "vt_service",
        "retriable": True,
    })
    assert err.category == ErrorCategory.VT_LOOKUP.value
    assert err.severity == ErrorSeverity.ERROR.value
    assert err.blocks_triage is True


def test_new_mdi_error_includes_explicit_taxonomy():
    err = make_mdi_error(
        "whois_failed",
        "Both failed",
        "domain_enrichment",
        retriable=True,
    )
    assert err.category == ErrorCategory.RDAP_WHOIS.value
    assert err.severity == ErrorSeverity.WARNING.value
    assert err.blocks_triage is False


def test_normalize_error_code_aliases():
    assert normalize_error_code("vt_429") == "rate_limited"
    assert normalize_error_code("quota_exhausted") == "quota_blocked"
    assert normalize_error_code("scan_not_supported") == "vt_scan_not_supported"
    assert normalize_error_code("live_check_dns_failure") == "dns_failed"


def test_quota_blocked_skip_severity():
    err = make_mdi_error(
        "quota_exhausted",
        "Quota exhausted",
        "job_processor",
        retriable=True,
    )
    assert err.severity == ErrorSeverity.SKIP.value
    assert error_blocks_triage(err) is False
    assert normalize_error_code(err.code) == "quota_blocked"


def test_quota_lock_timeout_is_blocking():
    err = make_mdi_error(
        "quota_lock_timeout",
        "Lock unavailable",
        "job_processor",
        retriable=True,
    )
    assert err.category == ErrorCategory.QUOTA_LOCK.value
    assert err.severity == ErrorSeverity.ERROR.value
    assert error_blocks_triage(err) is True


def test_scan_not_supported_is_skip():
    err = make_mdi_error(
        "scan_not_supported",
        "Not supported",
        "vt_service",
        retriable=False,
    )
    assert err.severity == ErrorSeverity.SKIP.value
    assert error_blocks_triage(err) is False


# ── Triage rules ───────────────────────────────────────────────────────────────


def _vt_success_input(**kwargs) -> TriageInput:
    base = dict(
        processing_status=MdiProcessingStatus.DONE,
        vt_hits=0,
        vt_suspicious=0,
        vt_total_engines=70,
        freshness=Freshness.FRESH,
        live_status=LiveStatus.NOT_CHECKED,
        age_bucket=AgeBucket.UNKNOWN,
        errors=[],
    )
    base.update(kwargs)
    return TriageInput(**base)


def test_whois_failed_warning_does_not_force_error_triage():
    warn = make_mdi_error("whois_failed", "RDAP+WHOIS failed", "domain_enrichment", retriable=True)
    d = decide(_vt_success_input(errors=[warn]))
    assert d.triage_bucket == TriageBucket.CLEAN
    assert d.recommended_action == RecommendedAction.NO_ACTION_BASED_ON_VT


def test_enrichment_error_warning_does_not_force_error_triage():
    warn = make_mdi_error("enrichment_error", "Unexpected", "domain_enrichment", retriable=True)
    d = decide(_vt_success_input(errors=[warn]))
    assert d.triage_bucket == TriageBucket.CLEAN


def test_flagged_vt_live_check_warning_stays_malicious():
    warn = make_mdi_error(
        "live_check_dns_failure",
        "DNS failed",
        "live_check",
        retriable=True,
    )
    d = decide(_vt_success_input(
        vt_hits=3,
        live_status=LiveStatus.DNS_FAILURE,
        errors=[warn],
    ))
    assert d.triage_bucket == TriageBucket.MALICIOUS
    assert d.recommended_action != RecommendedAction.RETRY_LOOKUP


def test_clean_vt_live_check_warning_stays_clean():
    warn = make_mdi_error(
        "live_check_dns_failure",
        "DNS failed",
        "live_check",
        retriable=True,
    )
    d = decide(_vt_success_input(
        live_status=LiveStatus.DNS_FAILURE,
        errors=[warn],
    ))
    assert d.triage_bucket == TriageBucket.CLEAN


def test_vt_blocking_error_still_routes_to_error():
    err = make_mdi_error("vt_timeout", "Timed out", "vt_service", retriable=True)
    d = decide(TriageInput(
        processing_status=MdiProcessingStatus.ERROR,
        vt_total_engines=0,
        errors=[err],
    ))
    assert d.triage_bucket == TriageBucket.ERROR
    assert d.recommended_action == RecommendedAction.RETRY_LOOKUP


def test_scan_not_supported_with_prior_vt_does_not_force_error():
    skip = make_mdi_error("scan_not_supported", "Domain report mode", "vt_service", retriable=False)
    d = decide(_vt_success_input(vt_hits=2, vt_suspicious=0, errors=[skip]))
    assert d.triage_bucket == TriageBucket.MALICIOUS
    assert has_blocking_errors([skip]) is False


# ── Integration: job submit paths ─────────────────────────────────────────────


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def _make_job(job_id, items):
    job = job_store.InMemoryJob(
        job_id=job_id,
        status="queued",
        submitted_at=time.time(),
        total=len(items),
        item_order=[],
    )
    for i, (orig, norm, itype) in enumerate(items, start=1):
        job.results[norm] = MdiResultItem(
            input_original=orig,
            input_normalized=norm,
            input_type=itype,
            position=i,
        )
        job.item_order.append(norm)
    job_store._JOBS[job_id] = job
    return job


def test_persisted_job_old_errors_recover(tmp_path):
    import asyncio

    job = _make_job("persist-old-err", [("a.com", "a.com", InputType.DOMAIN)])
    job.status = "done"
    job.completed_at = time.time()
    job.results["a.com"] = job.results["a.com"].model_copy(update={
        "errors": [
            MdiError(code="vt_429", message="old", source="vt_service", retriable=True),
        ],
    })
    path = tmp_path / "mdi_latest_job.json"
    asyncio.run(job_persistence.write_latest_job(job, job_file=path))
    raw = json.loads(path.read_text())
    assert raw["results"]["a.com"]["errors"][0]["code"] == "vt_429"

    recovered = job_persistence.read_latest_job(job_file=path)
    assert recovered is not None
    err = recovered.results["a.com"].errors[0]
    assert err.severity is not None
    assert err.category is not None


# ── Export / dashboard ─────────────────────────────────────────────────────────


def test_export_error_detail_structured():
    from services.export_service import export_error_detail

    detail = export_error_detail("no_flagged_rows")
    assert detail["code"] == "no_flagged_rows"
    assert detail["category"] == ErrorCategory.EXPORT.value
    assert detail["message"] == "no_flagged_rows"
    assert "severity" in detail


def test_dashboard_normalizes_legacy_and_canonical_codes():
    from services.dashboard import compute_job_result_aggregates

    job = job_store.InMemoryJob(
        job_id="dash-norm",
        status="done",
        submitted_at=time.time(),
        total=2,
        item_order=["a.com", "b.com"],
    )
    job.results["a.com"] = MdiResultItem(
        input_original="a.com",
        input_normalized="a.com",
        input_type=InputType.DOMAIN,
        position=1,
        processing_status=MdiProcessingStatus.ERROR,
        triage_bucket=TriageBucket.ERROR,
        errors=[MdiError(code="vt_429", message="x", source="vt_service", retriable=True)],
    )
    job.results["b.com"] = MdiResultItem(
        input_original="b.com",
        input_normalized="b.com",
        input_type=InputType.DOMAIN,
        position=2,
        processing_status=MdiProcessingStatus.ERROR,
        triage_bucket=TriageBucket.ERROR,
        errors=[make_mdi_error("rate_limited", "y", "vt_service", retriable=True)],
    )
    agg = compute_job_result_aggregates(job)
    assert agg["error_code_counts"].get("rate_limited") == 2


def test_infer_helpers_cover_upload_codes():
    assert infer_error_category("unsupported_format", "upload_parser") == ErrorCategory.UPLOAD_PARSE.value
    assert infer_error_severity("empty_file", ErrorCategory.UPLOAD_PARSE.value) == ErrorSeverity.ERROR.value
