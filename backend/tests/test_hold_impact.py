"""Tests for hold-impact guidance (MDI-50C)."""

from __future__ import annotations

import json

import pytest

from models import InputType, MdiProcessingStatus, MdiResultItem
from services import hold_impact, job_processor, job_store
from services.cloudflare_radar import CloudflareRankBucket
from services.hold_impact import HoldImpactLevel, derive_hold_impact_from_cloudflare_bucket


class TestDeriveHoldImpactFromBucket:
    @pytest.mark.parametrize(
        "bucket,expected_level",
        [
            (CloudflareRankBucket.TOP_100, HoldImpactLevel.CRITICAL),
            (CloudflareRankBucket.TOP_1K, HoldImpactLevel.CRITICAL),
            (CloudflareRankBucket.TOP_5K, HoldImpactLevel.HIGH),
            (CloudflareRankBucket.TOP_10K, HoldImpactLevel.HIGH),
            (CloudflareRankBucket.TOP_100K, HoldImpactLevel.MEDIUM),
            (CloudflareRankBucket.TOP_1M, HoldImpactLevel.LOW),
            (CloudflareRankBucket.UNRANKED, HoldImpactLevel.NONE),
            (CloudflareRankBucket.UNKNOWN, HoldImpactLevel.UNKNOWN),
            (None, HoldImpactLevel.UNKNOWN),
        ],
    )
    def test_bucket_mapping(self, bucket, expected_level):
        level, reason = derive_hold_impact_from_cloudflare_bucket(bucket)
        assert level == expected_level
        assert reason
        assert len(reason) > 20

    def test_critical_reason_mentions_blast_radius(self):
        _, reason = derive_hold_impact_from_cloudflare_bucket(CloudflareRankBucket.TOP_100)
        assert "blast radius" in reason.lower()

    def test_none_reason_for_unranked(self):
        level, reason = derive_hold_impact_from_cloudflare_bucket(CloudflareRankBucket.UNRANKED)
        assert level == HoldImpactLevel.NONE
        assert "not ranked" in reason.lower()

    def test_unknown_reason_for_missing_bucket(self):
        level, reason = derive_hold_impact_from_cloudflare_bucket(None)
        assert level == HoldImpactLevel.UNKNOWN
        assert "unavailable" in reason.lower() or "unknown" in reason.lower()


class TestHoldImpactItemUpdate:
    def test_item_update_keys(self):
        update = hold_impact.hold_impact_item_update(CloudflareRankBucket.TOP_5K)
        assert update["hold_impact_level"] == HoldImpactLevel.HIGH
        assert update["hold_impact_reason"]


class TestJobProcessorHoldImpact:
    def test_apply_hold_impact_guidance_disabled_cloudflare(self):
        job = job_store.InMemoryJob(
            job_id="j-hi-off",
            status="running",
            submitted_at=0.0,
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
        job_processor._apply_hold_impact_guidance(job)
        item = job.results["example.com"]
        assert item.hold_impact_level == HoldImpactLevel.UNKNOWN
        assert item.hold_impact_reason

    def test_apply_hold_impact_from_stored_bucket(self):
        job = job_store.InMemoryJob(
            job_id="j-hi",
            status="running",
            submitted_at=0.0,
            cloudflare_rank_lookup_enabled=True,
            item_order=["example.com"],
            results={
                "example.com": MdiResultItem(
                    input_original="example.com",
                    input_normalized="example.com",
                    input_type=InputType.DOMAIN,
                    position=1,
                    processing_status=MdiProcessingStatus.DONE,
                    cloudflare_rank_bucket=CloudflareRankBucket.TOP_1K,
                ),
            },
        )
        before_triage = job.results["example.com"].triage_bucket
        job_processor._apply_hold_impact_guidance(job)
        item = job.results["example.com"]
        assert item.hold_impact_level == HoldImpactLevel.CRITICAL
        assert item.triage_bucket == before_triage


class TestSerializationAndPersistence:
    def test_model_dump_includes_hold_impact_fields(self):
        item = MdiResultItem(
            input_original="example.com",
            input_normalized="example.com",
            input_type=InputType.DOMAIN,
            position=1,
            hold_impact_level=HoldImpactLevel.HIGH,
            hold_impact_reason="test reason",
        )
        dumped = json.dumps(item.model_dump(mode="json"))
        assert "hold_impact_level" in dumped
        assert "hold_impact_reason" in dumped
        assert "test reason" in dumped

    def test_older_job_without_hold_impact_fields_deserializes(self):
        raw = {
            "input_original": "example.com",
            "input_normalized": "example.com",
            "input_type": "domain",
            "position": 1,
            "cloudflare_rank_bucket": "TOP_1K",
        }
        item = MdiResultItem.model_validate(raw)
        assert item.hold_impact_level is None
        assert item.hold_impact_reason is None
