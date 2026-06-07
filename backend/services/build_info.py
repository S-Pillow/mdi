"""
Deploy-time build identity for MDI.

Reads build_info.json written during deployment. Never calls git or external APIs.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from models import BuildInfo

logger = logging.getLogger("mdi.build_info")

APP_VERSION = "0.3.0"

_build_info_cache: Optional[BuildInfo] = None
_warned_sources: set[str] = set()


def _build_info_path() -> Path:
    raw = os.environ.get("MDI_BUILD_INFO_FILE", "build_info.json")
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _missing_build_info(source: str) -> BuildInfo:
    return BuildInfo(
        app="mdi",
        commit=None,
        branch=None,
        built_at_utc=None,
        source=source,
    )


def _warn_once(source: str, message: str) -> None:
    if source in _warned_sources:
        return
    _warned_sources.add(source)
    logger.warning(message)


def clear_build_info_cache() -> None:
    """Reset cached build info (tests only)."""
    global _build_info_cache
    _build_info_cache = None


def load_build_info() -> BuildInfo:
    """
    Load deploy marker from build_info.json (or MDI_BUILD_INFO_FILE).

    Missing file → source=\"missing\". Invalid JSON → source=\"invalid\".
    No secrets, no git, no external calls.
    """
    global _build_info_cache
    if _build_info_cache is not None:
        return _build_info_cache

    path = _build_info_path()
    if not path.is_file():
        _warn_once("missing", "build_info.json not found; deploy commit unknown")
        _build_info_cache = _missing_build_info("missing")
        return _build_info_cache

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _warn_once("invalid", f"build_info.json unreadable or invalid: {exc}")
        _build_info_cache = _missing_build_info("invalid")
        return _build_info_cache

    if not isinstance(raw, dict):
        _warn_once("invalid", "build_info.json must be a JSON object")
        _build_info_cache = _missing_build_info("invalid")
        return _build_info_cache

    info = BuildInfo(
        app=raw.get("app") or "mdi",
        commit=raw.get("commit"),
        branch=raw.get("branch"),
        built_at_utc=raw.get("built_at_utc"),
        source=raw.get("source") or "deploy_marker",
    )
    _build_info_cache = info
    return info
