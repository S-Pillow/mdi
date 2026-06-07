"""
Tests for deploy-time build_info marker and /api/mdi/health + /api/mdi/version.

No network, no git, no runtime file writes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.build_info import clear_build_info_cache, load_build_info


@pytest.fixture(autouse=True)
def reset_build_info_cache():
    clear_build_info_cache()
    yield
    clear_build_info_cache()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def _write_marker(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "build_info.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestLoadBuildInfo:
    def test_marker_present(self, tmp_path, monkeypatch):
        marker = _write_marker(tmp_path, {
            "app": "mdi",
            "commit": "a" * 40,
            "branch": "main",
            "built_at_utc": "2026-06-07T12:00:00Z",
            "source": "deploy_marker",
        })
        monkeypatch.setenv("MDI_BUILD_INFO_FILE", str(marker))
        info = load_build_info()
        assert info.app == "mdi"
        assert info.commit == "a" * 40
        assert info.branch == "main"
        assert info.built_at_utc == "2026-06-07T12:00:00Z"
        assert info.source == "deploy_marker"

    def test_missing_marker(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MDI_BUILD_INFO_FILE", str(tmp_path / "missing.json"))
        info = load_build_info()
        assert info.source == "missing"
        assert info.commit is None
        assert info.branch is None
        assert info.built_at_utc is None
        assert info.app == "mdi"

    def test_malformed_marker(self, tmp_path, monkeypatch):
        path = tmp_path / "build_info.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("MDI_BUILD_INFO_FILE", str(path))
        info = load_build_info()
        assert info.source == "invalid"
        assert info.commit is None

    def test_partial_marker_defaults(self, tmp_path, monkeypatch):
        marker = _write_marker(tmp_path, {"commit": "b" * 40})
        monkeypatch.setenv("MDI_BUILD_INFO_FILE", str(marker))
        info = load_build_info()
        assert info.commit == "b" * 40
        assert info.app == "mdi"
        assert info.branch is None
        assert info.built_at_utc is None
        assert info.source == "deploy_marker"


class TestHealthEndpoint:
    def test_health_with_marker(self, client, tmp_path, monkeypatch):
        marker = _write_marker(tmp_path, {
            "commit": "c" * 40,
            "branch": "feature/test",
            "built_at_utc": "2026-06-07T10:00:00Z",
            "source": "deploy_marker",
        })
        monkeypatch.setenv("MDI_BUILD_INFO_FILE", str(marker))
        clear_build_info_cache()
        r = client.get("/api/mdi/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["service"] == "mdi"
        assert data["version"] == "0.3.0"
        assert data["build_info"]["commit"] == "c" * 40
        assert data["build_info"]["branch"] == "feature/test"
        assert data["build_info"]["source"] == "deploy_marker"

    def test_health_missing_marker_still_ok(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("MDI_BUILD_INFO_FILE", str(tmp_path / "absent.json"))
        clear_build_info_cache()
        r = client.get("/api/mdi/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["service"] == "mdi"
        assert data["build_info"]["source"] == "missing"

    def test_health_invalid_marker_still_ok(self, client, tmp_path, monkeypatch):
        path = tmp_path / "build_info.json"
        path.write_text("[]", encoding="utf-8")
        monkeypatch.setenv("MDI_BUILD_INFO_FILE", str(path))
        clear_build_info_cache()
        r = client.get("/api/mdi/health")
        assert r.status_code == 200
        assert r.json()["build_info"]["source"] == "invalid"


class TestVersionEndpoint:
    def test_version_with_marker(self, client, tmp_path, monkeypatch):
        marker = _write_marker(tmp_path, {
            "commit": "d" * 40,
            "branch": "main",
            "built_at_utc": "2026-06-07T11:00:00Z",
            "source": "deploy_marker",
        })
        monkeypatch.setenv("MDI_BUILD_INFO_FILE", str(marker))
        clear_build_info_cache()
        r = client.get("/api/mdi/version")
        assert r.status_code == 200
        data = r.json()
        assert data["build_info"]["commit"] == "d" * 40
        assert data["build_info"]["source"] == "deploy_marker"

    def test_version_missing_marker(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("MDI_BUILD_INFO_FILE", str(tmp_path / "absent.json"))
        clear_build_info_cache()
        r = client.get("/api/mdi/version")
        assert r.status_code == 200
        assert r.json()["build_info"]["source"] == "missing"


class TestNoExternalCalls:
    def test_health_no_network(self, client, tmp_path, monkeypatch):
        import socket
        marker = _write_marker(tmp_path, {"commit": "e" * 40, "source": "deploy_marker"})
        monkeypatch.setenv("MDI_BUILD_INFO_FILE", str(marker))
        clear_build_info_cache()
        calls = []
        original = socket.getaddrinfo

        def patched(*args, **kwargs):
            calls.append(args)
            return original(*args, **kwargs)

        socket.getaddrinfo = patched
        try:
            r = client.get("/api/mdi/health")
            assert r.status_code == 200
        finally:
            socket.getaddrinfo = original
        assert calls == []
