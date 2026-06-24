"""
Shared pytest configuration and fixtures for the MDI backend test suite.

Module-level autouse isolation
───────────────────────────────
Every test in every file in this directory receives the
``isolate_runtime_files`` autouse fixture below.  It redirects every
``/var/lib/dns-tool/`` write path to a per-test ``tmp_path`` via environment
variables, so no test can ever modify a live runtime file regardless of which
internal code path it exercises.

    MDI_LATEST_JOB_FILE      job_persistence._default_job_file()
    VT_USAGE_FILE            quota_writer._default_usage_file()
    VT_USAGE_HISTORY_FILE    quota_writer._default_history_file()
    VT_DAILY_HISTORY_FILE    quota_writer._default_daily_file()

Individual test modules (test_jobs_submit.py, test_mdi14_detail_evidence.py)
also set these same env vars in their own autouse fixtures for documentation
clarity.  That is harmless: both fixtures receive the same function-scoped
``tmp_path`` and the values are identical.

Why conftest.py instead of per-file fixtures only?
  test_estimate.py contains a ``process_job()`` call without ``history_file``
  or ``daily_file`` kwargs, causing background writes to fall through to the
  live default paths.  Rather than require every future test file to remember
  to add its own fixture, a single conftest guard covers all of them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


@pytest.fixture(autouse=True)
def isolate_runtime_files(tmp_path, monkeypatch):
    """
    Redirect all /var/lib/dns-tool/ runtime file writes to ``tmp_path``.

    Applied to every test in the backend test suite.  Covers both direct
    ``process_job()`` calls that omit explicit file kwargs *and* TestClient
    background tasks that resolve all paths from environment variables.

    ``monkeypatch`` automatically restores each variable after the test.
    """
    monkeypatch.setenv("MDI_LATEST_JOB_FILE",   str(tmp_path / "mdi_latest_job.json"))
    monkeypatch.setenv("VT_USAGE_FILE",         str(tmp_path / "vt_usage.json"))
    monkeypatch.setenv("VT_USAGE_HISTORY_FILE", str(tmp_path / "vt_usage_history.jsonl"))
    monkeypatch.setenv("VT_DAILY_HISTORY_FILE", str(tmp_path / "vt_daily_history.json"))
    monkeypatch.setenv("VT_QUOTA_LOCK_FILE",    str(tmp_path / "vt_usage.lock"))
