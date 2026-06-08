"""Tests for VT GUI report URL derivation (MDI-34)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from models import (
    EvidenceStatus,
    InputType,
    MdiProcessingStatus,
    MdiResultItem,
    TriageBucket,
    VtModeUsed,
)
from services.vt_gui_url import vt_gui_report_url_for_item


def _item(**kwargs) -> MdiResultItem:
    base = dict(
        input_original="example.com",
        input_normalized="example.com",
        input_type=InputType.DOMAIN,
        position=1,
    )
    base.update(kwargs)
    return MdiResultItem(**base)


def test_domain_report_produces_gui_link():
    item = _item(
        vt_mode_used=VtModeUsed.DOMAIN_REPORT,
        vt_scan_date=datetime.now(timezone.utc),
        vt_total_engines=72,
    )
    assert item.vt_report_url == "https://www.virustotal.com/gui/domain/example.com"


def test_url_report_bare_domain_uses_http_wrapper():
    item = _item(
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_scan_date=datetime.now(timezone.utc),
        vt_hits=0,
    )
    url = item.vt_report_url
    assert url is not None
    assert url.startswith("https://www.virustotal.com/gui/url/")


def test_full_url_report_uses_normalized_url():
    item = _item(
        input_original="https://evil.example/phish",
        input_normalized="https://evil.example/phish",
        input_type=InputType.URL,
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_scan_date=datetime.now(timezone.utc),
        vt_total_engines=70,
    )
    url = item.vt_report_url
    assert url is not None
    assert "/gui/url/" in url


def test_held_skipped_no_link():
    item = _item(
        vt_mode_used=VtModeUsed.SKIPPED_HOLD,
        triage_bucket=TriageBucket.HELD,
        processing_status=MdiProcessingStatus.HOLD_SKIPPED,
    )
    assert item.vt_report_url is None


def test_not_checked_no_link():
    item = _item(vt_mode_used=VtModeUsed.NOT_CHECKED)
    assert item.vt_report_url is None


def test_quota_skipped_no_link():
    item = _item(vt_mode_used=VtModeUsed.SKIPPED_QUOTA)
    assert item.vt_report_url is None


def test_url_mode_without_vt_data_no_link():
    item = _item(
        vt_mode_used=VtModeUsed.URL_REPORT,
        vt_scan_date=None,
        vt_total_engines=None,
        vt_hits=None,
        vt_suspicious=None,
    )
    assert item.vt_report_url is None


def test_model_dump_includes_vt_report_url():
    item = _item(
        vt_mode_used=VtModeUsed.DOMAIN_REPORT,
        vt_scan_date=datetime.now(timezone.utc),
        vt_total_engines=10,
    )
    dumped = item.model_dump(mode="json")
    assert dumped["vt_report_url"] == "https://www.virustotal.com/gui/domain/example.com"


def test_malformed_domain_no_link():
    item = _item(
        input_normalized="not a domain",
        vt_mode_used=VtModeUsed.DOMAIN_REPORT,
        vt_scan_date=datetime.now(timezone.utc),
        vt_total_engines=1,
    )
    assert item.vt_report_url is None
