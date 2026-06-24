"""
MDI-49 — Limited VT URL evidence fields.

All tests use fixtures/mocks only. No live VT calls. No quota consumed.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    ExportFormat,
    ExportScope,
    Freshness,
    InputType,
    MdiProcessingStatus,
    MdiResultItem,
    TriageBucket,
    TriageConfidence,
    VtModeUsed,
)
from services import export_service, job_store, vt_service
from services.export_service import CSV_HEADERS
from services.job_persistence import deserialize_job, serialize_job
from services.job_store import InMemoryJob, clear_all_jobs
from services.vt_service import (
    classify_triage,
    extract_vt_url_evidence,
    parse_vt_response,
)


def _run(coro):
    return asyncio.run(coro)


def _vt_url_report_with_evidence(
    *,
    malicious: int = 1,
    suspicious: int = 0,
    targeted_brand: dict | None = None,
    redirection_chain: list | None = None,
    last_final_url: str | None = None,
) -> dict:
    attrs = {
        "last_analysis_stats": {
            "malicious": malicious,
            "suspicious": suspicious,
            "harmless": 70,
            "undetected": 5,
            "timeout": 0,
        },
        "last_analysis_date": int(time.time()),
    }
    if targeted_brand is not None:
        attrs["targeted_brand"] = targeted_brand
    if redirection_chain is not None:
        attrs["redirection_chain"] = redirection_chain
    if last_final_url is not None:
        attrs["last_final_url"] = last_final_url
    return {"data": {"attributes": attrs}}


class TestVtUrlEvidenceExtraction:
    def test_extract_from_url_report_fixture(self):
        attrs = _vt_url_report_with_evidence(
            targeted_brand={"PhishTank": "PayPal", "OpenPhish": "PayPal"},
            redirection_chain=[
                "http://evil.example/landing",
                "https://phish.example/signin",
            ],
            last_final_url="https://phish.example/signin/final",
        )["data"]["attributes"]

        brand, sources, chain, final_url = extract_vt_url_evidence(
            attrs, VtModeUsed.URL_REPORT
        )
        assert brand == "PayPal"
        assert sources == ["OpenPhish", "PhishTank"]
        assert chain == [
            "http://evil.example/landing",
            "https://phish.example/signin",
        ]
        assert final_url == "https://phish.example/signin/final"

    def test_missing_evidence_defaults(self):
        attrs = _vt_url_report_with_evidence()["data"]["attributes"]
        brand, sources, chain, final_url = extract_vt_url_evidence(
            attrs, VtModeUsed.URL_REPORT
        )
        assert brand is None
        assert sources == []
        assert chain == []
        assert final_url is None

    def test_domain_report_mode_returns_empty(self):
        attrs = _vt_url_report_with_evidence(
            targeted_brand={"PhishTank": "PayPal"},
            redirection_chain=["http://a.example"],
            last_final_url="http://b.example",
        )["data"]["attributes"]
        brand, sources, chain, final_url = extract_vt_url_evidence(
            attrs, VtModeUsed.DOMAIN_REPORT
        )
        assert brand is None
        assert sources == []
        assert chain == []
        assert final_url is None

    def test_parse_vt_response_includes_url_evidence(self):
        report = _vt_url_report_with_evidence(
            targeted_brand={"BrandDB": "Microsoft"},
            redirection_chain=["http://redirect.example"],
            last_final_url="http://final.example/path",
        )
        result = parse_vt_response(report, VtModeUsed.URL_REPORT)
        assert result.vt_targeted_brand == "Microsoft"
        assert result.vt_targeted_brand_sources == ["BrandDB"]
        assert result.vt_redirection_chain == ["http://redirect.example"]
        assert result.vt_last_final_url == "http://final.example/path"

    def test_triage_unchanged_with_url_evidence(self):
        report = _vt_url_report_with_evidence(
            malicious=2,
            suspicious=1,
            targeted_brand={"PhishTank": "PayPal"},
            redirection_chain=["http://a.example"],
            last_final_url="http://b.example",
        )
        parsed = parse_vt_response(report, VtModeUsed.URL_REPORT)
        baseline = parse_vt_response(
            _vt_url_report_with_evidence(malicious=2, suspicious=1),
            VtModeUsed.URL_REPORT,
        )
        assert classify_triage(parsed) == classify_triage(baseline)
        assert parsed.vt_hits == baseline.vt_hits
        assert parsed.vt_ratio == baseline.vt_ratio


class TestPersistenceCompatibility:
    def test_old_job_without_fields_deserializes_with_defaults(self):
        legacy = {
            "job_id": "legacy-mdi49",
            "status": "done",
            "submitted_at": time.time(),
            "completed_at": time.time(),
            "total": 1,
            "processed": 1,
            "held_skipped": 0,
            "rejected_count": 0,
            "estimated_requests": 1,
            "lookups_used": 1,
            "use_domain_reports": False,
            "stale_threshold_days": 7,
            "item_order": ["example.com"],
            "results": {
                "example.com": {
                    "input_original": "example.com",
                    "input_normalized": "example.com",
                    "input_type": "domain",
                    "position": 1,
                    "processing_status": "done",
                    "vt_hits": 0,
                    "vt_total_engines": 72,
                    "vt_ratio": "0/72",
                    "freshness": "fresh",
                    "triage_bucket": "clean",
                    "triage_confidence": "high",
                    "recommended_action": "clear",
                    "evidence_status": "complete",
                    "vt_mode_used": "url_report",
                    "live_status": "not_checked",
                }
            },
        }
        job = deserialize_job(legacy)
        row = job.results["example.com"]
        assert row.vt_targeted_brand is None
        assert row.vt_targeted_brand_sources == []
        assert row.vt_redirection_chain == []
        assert row.vt_last_final_url is None

    def test_round_trip_preserves_url_evidence(self):
        row = MdiResultItem(
            input_original="http://evil.example/",
            input_normalized="http://evil.example/",
            input_type=InputType.URL,
            position=1,
            processing_status=MdiProcessingStatus.DONE,
            vt_mode_used=VtModeUsed.URL_REPORT,
            vt_hits=1,
            vt_total_engines=72,
            vt_ratio="1/72",
            freshness=Freshness.FRESH,
            triage_bucket=TriageBucket.MALICIOUS,
            triage_confidence=TriageConfidence.HIGH,
            vt_targeted_brand="PayPal",
            vt_targeted_brand_sources=["PhishTank"],
            vt_redirection_chain=["http://a.example", "http://b.example"],
            vt_last_final_url="http://b.example/final",
        )
        job = InMemoryJob(
            job_id="mdi49-roundtrip",
            status="done",
            submitted_at=time.time(),
            completed_at=time.time(),
            total=1,
            processed=1,
            item_order=["http://evil.example/"],
            results={"http://evil.example/": row},
        )
        payload = serialize_job(job)
        restored = deserialize_job(payload)
        restored_row = restored.results["http://evil.example/"]
        assert restored_row.vt_targeted_brand == "PayPal"
        assert restored_row.vt_targeted_brand_sources == ["PhishTank"]
        assert restored_row.vt_redirection_chain == [
            "http://a.example",
            "http://b.example",
        ]
        assert restored_row.vt_last_final_url == "http://b.example/final"


class TestExportIncludesUrlEvidence:
    @pytest.fixture(autouse=True)
    def _clear(self):
        clear_all_jobs()
        yield
        clear_all_jobs()

    def test_csv_headers_include_mdi49_fields(self):
        for field in (
            "vt_targeted_brand",
            "vt_targeted_brand_sources",
            "vt_redirection_chain",
            "vt_last_final_url",
        ):
            assert field in CSV_HEADERS

    def test_json_export_includes_mdi49_fields(self):
        row = MdiResultItem(
            input_original="http://evil.example/",
            input_normalized="http://evil.example/",
            input_type=InputType.URL,
            position=1,
            processing_status=MdiProcessingStatus.DONE,
            vt_targeted_brand="PayPal",
            vt_targeted_brand_sources=["PhishTank"],
            vt_redirection_chain=["http://hop.example"],
            vt_last_final_url="http://final.example",
        )
        job = InMemoryJob(
            job_id="mdi49-export",
            status="done",
            submitted_at=time.time(),
            completed_at=time.time(),
            total=1,
            processed=1,
            item_order=["http://evil.example/"],
            results={"http://evil.example/": row},
        )
        payload = export_service.build_evidence_json_export(job, [row], ExportScope.ALL)
        data = json.loads(payload)
        item = data["results"][0]
        assert item["vt_targeted_brand"] == "PayPal"
        assert item["vt_targeted_brand_sources"] == ["PhishTank"]
        assert item["vt_redirection_chain"] == ["http://hop.example"]
        assert item["vt_last_final_url"] == "http://final.example"


class TestNoExtraVtLookups:
    def test_fetch_report_call_count_unchanged(self):
        report = _vt_url_report_with_evidence(
            targeted_brand={"PhishTank": "PayPal"},
            redirection_chain=["http://a.example"],
            last_final_url="http://b.example",
        )

        async def _fetch():
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = report
            with patch.object(vt_service._VT_LIMITER, "acquire", new=AsyncMock()):
                with patch(
                    "services.vt_service._vt_request",
                    new=AsyncMock(return_value=mock_resp),
                ) as mock_req:
                    with patch.dict("os.environ", {"VT_API_KEY": "test-key"}):
                        result = await vt_service.fetch_report(
                            input_normalized="http://evil.example/",
                            input_type=InputType.URL,
                            use_domain_reports=False,
                        )
            assert mock_req.await_count == 1
            assert result.calls_made == 1
            assert result.vt_targeted_brand == "PayPal"
            return result

        parsed = _run(_fetch())
        bucket, _conf, _action, _evidence = classify_triage(parsed)
        assert bucket == TriageBucket.MALICIOUS
        assert parsed.vt_hits == 1
