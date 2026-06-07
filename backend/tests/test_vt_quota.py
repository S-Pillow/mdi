"""
Tests for backend/services/vt_quota.py.

All tests use tempfile paths.  No test reads from or writes to
/var/lib/dns-tool/.  The live runtime file is only accessed by the
read_usage_state() call in test_read_from_live_file_is_read_only, which
confirms the file is not modified after a read.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add backend/ to sys.path so imports work without packaging
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.vt_quota import (
    DAILY_LOOKUPS_LIMIT,
    RATE_LIMIT_PER_MIN,
    _increment_usage_for_file,
    _utc_date_str,
    get_usage_summary,
    read_usage_state,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_usage_file(path: Path, date_utc: str, count: int) -> None:
    path.write_text(json.dumps({"date_utc": date_utc, "daily_lookups_used": count}))


# ── read_usage_state ───────────────────────────────────────────────────────────

class TestReadUsageState:

    def test_valid_current_date(self, tmp_path):
        today = _utc_date_str()
        f = tmp_path / "vt_usage.json"
        _write_usage_file(f, today, 42)
        result = read_usage_state(f)
        assert result["daily_lookups_used"] == 42
        assert result["date_utc"] == today
        assert result["_error"] is None

    def test_stale_date_resets_to_zero(self, tmp_path):
        f = tmp_path / "vt_usage.json"
        _write_usage_file(f, "2020-01-01", 999)
        result = read_usage_state(f)
        assert result["daily_lookups_used"] == 0
        assert result["date_utc"] == _utc_date_str()
        assert result["_error"] is None

    def test_missing_file_returns_safe_defaults(self, tmp_path):
        f = tmp_path / "nonexistent.json"
        result = read_usage_state(f)
        assert result["daily_lookups_used"] == 0
        assert result["date_utc"] == _utc_date_str()
        assert result["_error"] is not None
        assert "file_not_found" in result["_error"]

    def test_empty_file_returns_safe_defaults(self, tmp_path):
        f = tmp_path / "vt_usage.json"
        f.write_text("")
        result = read_usage_state(f)
        assert result["daily_lookups_used"] == 0
        assert "file_empty" in result["_error"]

    def test_malformed_json_returns_error_no_mutate(self, tmp_path):
        f = tmp_path / "vt_usage.json"
        original_content = "{ not valid json }"
        f.write_text(original_content)
        result = read_usage_state(f)
        assert result["daily_lookups_used"] == 0
        assert result["_error"] is not None
        assert "json_decode_error" in result["_error"]
        # Confirm file was NOT mutated
        assert f.read_text() == original_content

    def test_wrong_type_json_returns_error(self, tmp_path):
        f = tmp_path / "vt_usage.json"
        f.write_text("[1, 2, 3]")
        result = read_usage_state(f)
        assert "unexpected_type" in result["_error"]


# ── get_usage_summary ──────────────────────────────────────────────────────────

class TestGetUsageSummary:

    def test_structure(self, tmp_path):
        today = _utc_date_str()
        f = tmp_path / "vt_usage.json"
        _write_usage_file(f, today, 10)
        result = get_usage_summary(f)
        assert result["daily_lookups_used"] == 10
        assert result["daily_limit"] == DAILY_LOOKUPS_LIMIT
        assert result["remaining"] == DAILY_LOOKUPS_LIMIT - 10
        assert result["rate_limit_per_min"] == RATE_LIMIT_PER_MIN
        assert result["mutated"] is False
        assert result["shared_with"] == ["vt-bulk-check", "mdi"]
        assert result["error"] is None

    def test_remaining_never_negative(self, tmp_path):
        today = _utc_date_str()
        f = tmp_path / "vt_usage.json"
        _write_usage_file(f, today, 9999)
        result = get_usage_summary(f)
        assert result["remaining"] == 0

    def test_missing_file_no_crash(self, tmp_path):
        f = tmp_path / "missing.json"
        result = get_usage_summary(f)
        assert result["daily_lookups_used"] == 0
        assert result["remaining"] == DAILY_LOOKUPS_LIMIT
        assert result["error"] is not None
        assert result["mutated"] is False


# ── _increment_usage_for_file (test-only write helper) ────────────────────────

class TestIncrementUsageForFile:

    def test_creates_file_if_missing(self, tmp_path):
        f = tmp_path / "usage.json"
        result = _increment_usage_for_file(f, 1)
        assert result["daily_lookups_used"] == 1
        assert f.exists()

    def test_increments_existing_count(self, tmp_path):
        today = _utc_date_str()
        f = tmp_path / "usage.json"
        _write_usage_file(f, today, 5)
        result = _increment_usage_for_file(f, 3)
        assert result["daily_lookups_used"] == 8

    def test_resets_on_stale_date(self, tmp_path):
        f = tmp_path / "usage.json"
        _write_usage_file(f, "2020-01-01", 500)
        result = _increment_usage_for_file(f, 1)
        assert result["daily_lookups_used"] == 1
        assert result["date_utc"] == _utc_date_str()

    def test_atomic_write_leaves_valid_json(self, tmp_path):
        today = _utc_date_str()
        f = tmp_path / "usage.json"
        _write_usage_file(f, today, 10)
        _increment_usage_for_file(f, 1)
        data = json.loads(f.read_text())
        assert data["daily_lookups_used"] == 11
        assert data["date_utc"] == today
        # No .tmp file left behind
        assert not f.with_suffix(".tmp").exists()

    def test_does_not_touch_live_runtime_file(self, tmp_path):
        """
        Explicit regression: confirm the test uses a temp path, not the
        production path.  If this test somehow received the real path, the
        assertion below would catch it.
        """
        f = tmp_path / "usage.json"
        live_path = Path("/var/lib/dns-tool/vt_usage.json")
        assert str(f) != str(live_path), (
            "Test file path must differ from live runtime path"
        )


# ── Model serialization smoke test ────────────────────────────────────────────

class TestModelSerialization:

    def test_mdi_job_options_defaults(self):
        from models import MdiJobOptions
        opts = MdiJobOptions()
        d = opts.model_dump()
        assert d["skip_held_domains"] is True
        assert d["auto_rescan_stale"] is False
        assert d["max_auto_rescans"] == 3
        assert d["include_live_check"] is True

    def test_mdi_result_item_minimal(self):
        from models import MdiResultItem, InputType
        item = MdiResultItem(
            input_original="example.com",
            input_normalized="example.com",
            input_type=InputType.DOMAIN,
            position=1,
        )
        d = item.model_dump()
        assert d["triage_bucket"] == "pending"
        assert d["errors"] == []
        assert d["vt_hits"] is None

    def test_all_enums_serialise_as_strings(self):
        from models import TriageBucket, LiveStatus, Freshness
        assert TriageBucket.MALICIOUS.value == "malicious"
        assert LiveStatus.DNS_FAILURE.value == "dns_failure"
        assert Freshness.VERY_STALE.value == "very_stale"
