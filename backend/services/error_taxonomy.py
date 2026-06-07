"""
MDI canonical error taxonomy — codes, categories, severities, and triage blocking rules.

Old persisted error codes remain valid; normalize_error_code() maps aliases to canonical
forms for aggregation while preserving original codes on stored objects.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from models import MdiError


class ErrorSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    SKIP = "skip"
    INFO = "info"


class ErrorCategory(str, Enum):
    INPUT_VALIDATION = "input_validation"
    UPLOAD_PARSE = "upload_parse"
    VT_LOOKUP = "vt_lookup"
    QUOTA = "quota"
    QUOTA_LOCK = "quota_lock"
    RDAP_WHOIS = "rdap_whois"
    LIVE_CHECK = "live_check"
    REFRESH = "refresh"
    SCAN = "scan"
    AUTO_RESCAN = "auto_rescan"
    EXPORT = "export"
    RECOVERY = "recovery"
    PERSISTENCE = "persistence"
    UNKNOWN = "unknown"


# Legacy code → canonical code (for dashboard aggregation; stored codes unchanged)
_CODE_ALIASES: Dict[str, str] = {
    "vt_timeout": "timeout",
    "vt_connection": "connection_error",
    "vt_429": "rate_limited",
    "vt_auth": "auth_error",
    "no_api_key": "auth_error",
    "vt_not_found": "not_found",
    "vt_server_error": "server_error",
    "vt_submit_error": "server_error",
    "scan_not_supported": "vt_scan_not_supported",
    "quota_exhausted": "quota_blocked",
    "auto_rescan_quota_blocked": "quota_blocked",
    "live_check_dns_failure": "dns_failed",
    "live_check_redirect_blocked": "redirect_blocked",
    "live_check_blocked": "blocked",
    "live_check_tls_error": "tls_error",
    "live_check_error": "unknown",
    "unsupported_format": "unsupported_file_type",
    "empty_file": "empty_input",
    "missing_domain": "missing_domain_column",
    "whois_failed": "whois_failed",
    "enrichment_error": "enrichment_error",
    "vt_scan_pending": "vt_scan_pending",
    "quota_lock_timeout": "quota_lock_timeout",
    "quota_blocked": "quota_blocked",
}

# Explicit severity overrides by code (checked before category defaults)
_CODE_SEVERITY: Dict[str, str] = {
    "quota_exhausted": ErrorSeverity.SKIP.value,
    "quota_blocked": ErrorSeverity.SKIP.value,
    "auto_rescan_quota_blocked": ErrorSeverity.WARNING.value,
    "scan_not_supported": ErrorSeverity.SKIP.value,
    "vt_scan_not_supported": ErrorSeverity.SKIP.value,
    "whois_failed": ErrorSeverity.WARNING.value,
    "enrichment_error": ErrorSeverity.WARNING.value,
    "live_check_dns_failure": ErrorSeverity.WARNING.value,
    "dns_failed": ErrorSeverity.WARNING.value,
    "live_check_redirect_blocked": ErrorSeverity.WARNING.value,
    "redirect_blocked": ErrorSeverity.WARNING.value,
    "live_check_blocked": ErrorSeverity.WARNING.value,
    "blocked": ErrorSeverity.WARNING.value,
    "live_check_tls_error": ErrorSeverity.WARNING.value,
    "tls_error": ErrorSeverity.WARNING.value,
    "live_check_error": ErrorSeverity.WARNING.value,
    "quota_lock_timeout": ErrorSeverity.ERROR.value,
    "vt_scan_pending": ErrorSeverity.WARNING.value,
}

# Category by code prefix or exact match
_CODE_CATEGORY: Dict[str, str] = {
    "quota_exhausted": ErrorCategory.QUOTA.value,
    "quota_blocked": ErrorCategory.QUOTA.value,
    "auto_rescan_quota_blocked": ErrorCategory.AUTO_RESCAN.value,
    "quota_lock_timeout": ErrorCategory.QUOTA_LOCK.value,
    "whois_failed": ErrorCategory.RDAP_WHOIS.value,
    "enrichment_error": ErrorCategory.RDAP_WHOIS.value,
    "scan_not_supported": ErrorCategory.SCAN.value,
    "vt_scan_not_supported": ErrorCategory.SCAN.value,
    "vt_scan_pending": ErrorCategory.VT_LOOKUP.value,
    "no_api_key": ErrorCategory.VT_LOOKUP.value,
}

_SOURCE_CATEGORY: Dict[str, str] = {
    "input_parser": ErrorCategory.INPUT_VALIDATION.value,
    "upload_parser": ErrorCategory.UPLOAD_PARSE.value,
    "vt_service": ErrorCategory.VT_LOOKUP.value,
    "vt": ErrorCategory.VT_LOOKUP.value,
    "job_processor": ErrorCategory.QUOTA.value,
    "domain_enrichment": ErrorCategory.RDAP_WHOIS.value,
    "live_check": ErrorCategory.LIVE_CHECK.value,
    "auto_rescan": ErrorCategory.AUTO_RESCAN.value,
    "export_service": ErrorCategory.EXPORT.value,
    "job_persistence": ErrorCategory.PERSISTENCE.value,
}

# Auto-rescan skip reason codes (info/skip, not row failures)
_AUTO_RESCAN_SKIP_CODES = frozenset({
    "auto_rescan_job_limit",
    "auto_rescan_held",
    "auto_rescan_no_vt_data",
    "auto_rescan_not_flagged",
    "auto_rescan_not_stale",
})


def normalize_error_code(code: str) -> str:
    """Map a stored or legacy code to its canonical aggregation key."""
    if not code:
        return code
    return _CODE_ALIASES.get(code, code)


def infer_error_category(code: str, source: Optional[str] = None) -> str:
    """Infer ErrorCategory value from code and optional source."""
    if code in _CODE_CATEGORY:
        return _CODE_CATEGORY[code]
    if code in _AUTO_RESCAN_SKIP_CODES:
        return ErrorCategory.AUTO_RESCAN.value
    if code.startswith("live_check_"):
        return ErrorCategory.LIVE_CHECK.value
    if code.startswith("vt_") or code in ("no_api_key", "timeout", "connection_error", "rate_limited"):
        return ErrorCategory.VT_LOOKUP.value
    if source and source in _SOURCE_CATEGORY:
        return _SOURCE_CATEGORY[source]
    if code in (
        "invalid_input", "unsupported_scheme", "token_too_long", "input_too_large",
        "max_items_exceeded", "ip_address_not_supported",
    ):
        return ErrorCategory.INPUT_VALIDATION.value
    if code in (
        "parse_error", "file_too_large", "unsupported_file_type", "empty_input",
        "missing_domain_column",
    ):
        return ErrorCategory.UPLOAD_PARSE.value
    return ErrorCategory.UNKNOWN.value


def infer_error_severity(code: str, category: Optional[str] = None) -> str:
    """Infer ErrorSeverity from code (and optional category)."""
    if code in _CODE_SEVERITY:
        return _CODE_SEVERITY[code]
    if code in _AUTO_RESCAN_SKIP_CODES:
        return ErrorSeverity.INFO.value
    if category == ErrorCategory.RDAP_WHOIS.value:
        return ErrorSeverity.WARNING.value
    if category == ErrorCategory.LIVE_CHECK.value:
        return ErrorSeverity.WARNING.value
    if category == ErrorCategory.QUOTA.value and code in ("quota_exhausted", "quota_blocked"):
        return ErrorSeverity.SKIP.value
    if category == ErrorCategory.QUOTA_LOCK.value:
        return ErrorSeverity.ERROR.value
    if category == ErrorCategory.AUTO_RESCAN.value:
        return ErrorSeverity.INFO.value
    if code.startswith("live_check_"):
        return ErrorSeverity.WARNING.value
    if code.startswith("vt_") or code in (
        "timeout", "connection_error", "rate_limited", "auth_error",
        "not_found", "server_error", "no_api_key",
    ):
        return ErrorSeverity.ERROR.value
    return ErrorSeverity.ERROR.value


def error_blocks_triage(error: Any) -> bool:
    """
    Return True when an error should force the ERROR triage bucket.

    Blocking: severity == error, unless blocks_triage is explicitly False.
    Non-blocking: warning, skip, info (unless blocks_triage explicitly True).
    """
    if error is None:
        return False
    explicit = getattr(error, "blocks_triage", None)
    if explicit is not None:
        return bool(explicit)
    severity = getattr(error, "severity", None)
    if severity is None:
        code = getattr(error, "code", "") or ""
        category = getattr(error, "category", None)
        if category is None:
            source = getattr(error, "source", None)
            category = infer_error_category(code, source)
        severity = infer_error_severity(code, category)
    return str(severity) == ErrorSeverity.ERROR.value


def has_blocking_errors(errors: list) -> bool:
    """True if any error in the list blocks triage."""
    return any(error_blocks_triage(e) for e in (errors or []))


def make_mdi_error(
    code: str,
    message: str,
    source: str,
    *,
    retriable: bool = False,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    blocks_triage: Optional[bool] = None,
) -> "MdiError":
    """Create an MdiError with taxonomy fields populated."""
    from models import MdiError

    cat = category or infer_error_category(code, source)
    sev = severity or infer_error_severity(code, cat)
    err = MdiError(
        code=code,
        message=message,
        source=source,
        retriable=retriable,
        category=cat,
        severity=sev,
        blocks_triage=blocks_triage,
    )
    if err.blocks_triage is None:
        return err.model_copy(update={"blocks_triage": error_blocks_triage(err)})
    return err
