"""
MDI Pydantic models and enumerations.

Every field carries a `purpose` annotation in its description.
Purpose categories:
  display           — rendered in the results table or detail drawer
  workflow          — used to drive hold-skip, auto-rescan, or routing logic
  filtering         — used for client-side or server-side filtering/sorting
  reporting         — included in CSV export and usage history JSONL
  audit             — retained for debugging, not shown by default
  dashboard         — metadata-only; shown in history panel without item data
  future            — defined for schema stability; not populated yet
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ─── Enumerations ─────────────────────────────────────────────────────────────


class InputType(str, Enum):
    """Whether the normalised input item is a bare domain or a full URL."""
    DOMAIN = "domain"
    URL = "url"


class MdiJobStatus(str, Enum):
    """Lifecycle state of an MDI job."""
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class MdiProcessingStatus(str, Enum):
    """Per-item processing outcome."""
    PENDING = "pending"
    HOLD_SKIPPED = "hold_skipped"    # clientHold / serverHold — skipped entirely
    DONE = "done"
    ERROR = "error"


class DomainHoldType(str, Enum):
    """Which registry hold type caused the skip decision."""
    CLIENT_HOLD = "clientHold"
    SERVER_HOLD = "serverHold"
    NONE = "none"


class DomainStatusSource(str, Enum):
    """Which data source provided the EPP/hold status."""
    RDAP = "rdap"
    WHOIS = "whois"
    UNKNOWN = "unknown"
    NOT_CHECKED = "not_checked"


class VtModeUsed(str, Enum):
    """Which VirusTotal report type was used for this item."""
    URL_REPORT = "url_report"        # default for bare domains and URLs
    DOMAIN_REPORT = "domain_report"  # opt-in: domain-level report
    NOT_CHECKED = "not_checked"
    SKIPPED_HOLD = "skipped_hold"
    SKIPPED_QUOTA = "skipped_quota"


class Freshness(str, Enum):
    """Age classification of the VT report relative to the scan date."""
    FRESH = "fresh"        # < 5 days old
    STALE = "stale"        # 5–30 days old
    VERY_STALE = "very_stale"  # > 30 days old
    NEVER_SCANNED = "never_scanned"
    UNKNOWN = "unknown"


class LiveStatus(str, Enum):
    """Result of the URL Activity Scanner HEAD-request probe."""
    ACTIVE = "active"             # 2xx response
    REDIRECT = "redirect"         # 3xx response
    FORBIDDEN = "forbidden"       # 403
    NOT_FOUND = "not_found"       # 404
    GONE = "gone"                 # 410
    TIMEOUT = "timeout"
    DNS_FAILURE = "dns_failure"
    CONNECTION_REFUSED = "connection_refused"
    BLOCKED = "blocked"           # SSRF-blocked by safety layer
    SERVER_ERROR = "server_error"
    UNKNOWN = "unknown"
    NOT_CHECKED = "not_checked"


class AgeBucket(str, Enum):
    """Human-readable age band for the registered domain."""
    VERY_NEW = "very_new"    # < 30 days
    NEW = "new"              # 30–180 days
    ESTABLISHED = "established"  # 180 days – 2 years
    MATURE = "mature"        # > 2 years
    UNKNOWN = "unknown"


class TriageBucket(str, Enum):
    """
    Top-level triage classification for a single domain/URL result.
    Used for display colouring, filtering, and export grouping.
    """
    MALICIOUS = "malicious"      # VT malicious engines > 0
    SUSPICIOUS = "suspicious"    # VT suspicious > 0 or ambiguous signals
    HELD = "held"                # Skipped due to domain hold
    CLEAN = "clean"              # All checks pass
    UNRESOLVABLE = "unresolvable"  # DNS failure or never registered
    ERROR = "error"              # Processing error, result incomplete
    PENDING = "pending"          # Not yet processed


class TriageConfidence(str, Enum):
    """Confidence level of the triage classification."""
    HIGH = "high"        # Multiple corroborating signals
    MEDIUM = "medium"    # Single signal or partial data
    LOW = "low"          # Insufficient data
    UNKNOWN = "unknown"


class RecommendedAction(str, Enum):
    """
    Workflow recommendation based on triage result.
    Used for operator decision support, not auto-execution.
    """
    INVESTIGATE = "investigate"
    TAKEDOWN = "takedown"
    MONITOR = "monitor"
    CLEAR = "clear"
    SKIP = "skip"          # Hold-skipped; no action recommended
    MANUAL_REVIEW = "manual_review"
    NONE = "none"


class EvidenceStatus(str, Enum):
    """Whether evidence collection for this item is complete."""
    COMPLETE = "complete"
    PARTIAL = "partial"    # Some checks ran but not all
    NONE = "none"          # No checks ran (e.g. hold skip)


# ─── Item-level models ─────────────────────────────────────────────────────────


class DomainHold(BaseModel):
    """Hold status extracted from WHOIS/RDAP for a domain."""
    has_hold: bool = Field(
        False,
        description="[workflow] True if any hold type was detected."
    )
    hold_types: List[DomainHoldType] = Field(
        default_factory=list,
        description="[workflow] All hold types found (may include multiple)."
    )
    source: DomainStatusSource = Field(
        DomainStatusSource.NOT_CHECKED,
        description="[audit] Which data source provided the EPP/hold status."
    )
    raw_statuses: List[str] = Field(
        default_factory=list,
        description="[audit] Raw EPP status strings from the registry response."
    )


class MdiError(BaseModel):
    """A single structured error attached to a result item or job."""
    code: str = Field(
        ...,
        description="[audit] Short machine-readable error code, e.g. 'vt_429', 'rdap_timeout'."
    )
    message: str = Field(
        ...,
        description="[display] Human-readable error message shown in the detail drawer."
    )
    source: str = Field(
        ...,
        description="[audit] Which service/step produced the error, e.g. 'vt', 'rdap', 'url_check'."
    )
    retriable: bool = Field(
        False,
        description="[workflow] Whether this error may resolve if retried."
    )


class MdiInputItem(BaseModel):
    """
    A single validated and normalised input item before any checks run.
    Populated by the input parser (MDI-04).
    """
    input_original: str = Field(
        ...,
        description="[audit] The raw string as submitted by the operator. Never logged externally."
    )
    input_normalized: str = Field(
        ...,
        description="[display, audit] Normalised form used for VT/WHOIS lookups."
    )
    input_type: InputType = Field(
        ...,
        description="[workflow, filtering] Whether the item is a bare domain or URL."
    )
    position: int = Field(
        ...,
        description="[display] 1-based position in the original input list, for stable ordering."
    )


class MdiResultItem(BaseModel):
    """
    Fully resolved result for a single input item.
    Fields are optional until the relevant check runs.
    """
    # ── Identity ──────────────────────────────────────────────────────────────
    input_original: str = Field(
        ...,
        description="[display, reporting] Raw input string, reproduced for traceability."
    )
    input_normalized: str = Field(
        ...,
        description="[display, reporting] Normalised form used for all lookups."
    )
    input_type: InputType = Field(
        ...,
        description="[display, filtering] domain or url."
    )
    position: int = Field(
        ...,
        description="[display] Stable row order."
    )
    processing_status: MdiProcessingStatus = Field(
        MdiProcessingStatus.PENDING,
        description="[display, workflow] Per-item lifecycle state."
    )

    # ── Domain hold ──────────────────────────────────────────────────────────
    domain_hold: Optional[DomainHold] = Field(
        None,
        description="[workflow, display] Hold status. Populated only when WHOIS/RDAP ran."
    )

    # ── WHOIS / RDAP ─────────────────────────────────────────────────────────
    registrar: Optional[str] = Field(
        None,
        description="[display, reporting] Registrar name."
    )
    created_at: Optional[datetime] = Field(
        None,
        description="[display, filtering, reporting] Domain registration date (UTC)."
    )
    age_bucket: AgeBucket = Field(
        AgeBucket.UNKNOWN,
        description="[display, filtering] Age classification derived from created_at."
    )
    epp_status: List[str] = Field(
        default_factory=list,
        description="[display, reporting] Full EPP status list (e.g. clientTransferProhibited)."
    )
    nameservers: List[str] = Field(
        default_factory=list,
        description="[display, future] Nameservers from RDAP/WHOIS."
    )

    # ── VirusTotal ───────────────────────────────────────────────────────────
    vt_mode_used: VtModeUsed = Field(
        VtModeUsed.NOT_CHECKED,
        description="[audit] Which VT report type was used."
    )
    vt_hits: Optional[int] = Field(
        None,
        description="[display, filtering, reporting] Number of VT engines flagging as malicious."
    )
    vt_suspicious: Optional[int] = Field(
        None,
        description="[display, filtering, reporting] Number of VT engines flagging as suspicious."
    )
    vt_total_engines: Optional[int] = Field(
        None,
        description="[display, reporting] Total VT engines that evaluated this item."
    )
    vt_ratio: Optional[str] = Field(
        None,
        description="[display] Human-readable ratio string, e.g. '3/72'."
    )
    vt_scan_date: Optional[datetime] = Field(
        None,
        description="[display, filtering, reporting] UTC timestamp of the VT scan used."
    )
    freshness: Freshness = Field(
        Freshness.UNKNOWN,
        description="[display, filtering, workflow] Age classification of the VT report."
    )
    vt_engine_results: Optional[Dict[str, Any]] = Field(
        None,
        description="[future] Raw per-engine VT results. Not included in exports by default."
    )

    # ── URL live activity ─────────────────────────────────────────────────────
    live_status: LiveStatus = Field(
        LiveStatus.NOT_CHECKED,
        description="[display, filtering, reporting] Result of SSRF-safe HEAD-request probe."
    )
    live_checked_at: Optional[datetime] = Field(
        None,
        description="[display, audit] UTC timestamp when live check ran."
    )

    # ── Triage ───────────────────────────────────────────────────────────────
    triage_bucket: TriageBucket = Field(
        TriageBucket.PENDING,
        description="[display, filtering, reporting] Top-level triage classification."
    )
    triage_reason: Optional[str] = Field(
        None,
        description="[display] Short explanation of why this triage bucket was assigned."
    )
    triage_confidence: TriageConfidence = Field(
        TriageConfidence.UNKNOWN,
        description="[display, filtering] Confidence level of the triage classification."
    )
    recommended_action: RecommendedAction = Field(
        RecommendedAction.NONE,
        description="[display, workflow] Suggested operator action."
    )
    evidence_status: EvidenceStatus = Field(
        EvidenceStatus.NONE,
        description="[display, audit] Whether all expected checks completed."
    )

    # ── Errors ───────────────────────────────────────────────────────────────
    errors: List[MdiError] = Field(
        default_factory=list,
        description="[display, audit] Structured errors encountered during processing."
    )


# ─── Job-level models ─────────────────────────────────────────────────────────


class MdiJobOptions(BaseModel):
    """
    Per-job processing options set at submission time.
    All defaults must be conservative (quota-safe, hold-respecting).
    """
    skip_held_domains: bool = Field(
        True,
        description="[workflow] Skip VT and live checks for domains with clientHold or serverHold."
    )
    auto_rescan_stale: bool = Field(
        False,
        description="[workflow, dashboard] Auto-request fresh VT scan for stale results. Off by default."
    )
    use_domain_reports: bool = Field(
        False,
        description="[workflow] Use VT domain reports instead of URL reports for bare domains."
    )
    include_live_check: bool = Field(
        True,
        description="[workflow] Run SSRF-safe HEAD-request probe for each item."
    )
    include_whois: bool = Field(
        True,
        description="[workflow] Run WHOIS/RDAP lookup for each item."
    )
    stale_threshold_days: int = Field(
        5,
        ge=1,
        le=90,
        description="[workflow] Reports older than this many days are classified as stale."
    )
    auto_rescan_threshold_days: int = Field(
        7,
        ge=1,
        le=90,
        description="[workflow] Only auto-rescan reports older than this threshold."
    )
    max_auto_rescans: int = Field(
        25,
        ge=0,
        le=100,
        description="[workflow] Maximum stale items to auto-rescan per job run."
    )


class MdiJobSummary(BaseModel):
    """
    Metadata-only summary record written to usage history JSONL.
    Must not contain item-level data (no domains, URLs, or IP addresses).
    """
    ts: float = Field(..., description="[dashboard, reporting] Unix timestamp of completion.")
    tool_name: str = Field("mdi", description="[reporting] Always 'mdi' for MDI records.")
    job_id: str = Field(..., description="[dashboard, reporting] UUID of the job.")
    operation: str = Field(
        ...,
        description="[reporting] One of: report_lookup, refresh, force_scan, auto_rescan."
    )
    status: MdiJobStatus = Field(..., description="[dashboard] Job completion status.")
    submitted_at: float = Field(..., description="[dashboard] Unix timestamp of submission.")
    completed_at: float = Field(..., description="[dashboard] Unix timestamp of completion.")
    accepted_count: int = Field(..., description="[dashboard, reporting] Items accepted.")
    rejected_count: int = Field(..., description="[dashboard, reporting] Items rejected at parse time.")
    processed: int = Field(..., description="[dashboard, reporting] Items actually processed.")
    total: int = Field(..., description="[dashboard, reporting] Total items in job.")
    domain_count: int = Field(..., description="[reporting] Bare domains in input.")
    url_count: int = Field(..., description="[reporting] Full URLs in input.")
    items_held_skipped: int = Field(
        0,
        description="[reporting] Items skipped due to clientHold/serverHold."
    )
    actual_lookups: int = Field(..., description="[reporting] VT API calls consumed.")
    estimated_requests: int = Field(..., description="[reporting] Quota estimate at submit time.")
    quota_blocked_count: int = Field(
        0,
        description="[reporting] Items not processed due to quota limit."
    )
    errors_count: int = Field(0, description="[reporting] Non-quota processing errors.")
    auto_rescan_enabled: bool = Field(
        False,
        description="[reporting] Whether auto-rescan was active."
    )
    use_domain_reports: bool = Field(
        False,
        description="[reporting] Whether domain-report mode was active."
    )
    processing_options_summary: str = Field(
        "",
        description=(
            "[audit] Short key=value summary of job options, "
            "e.g. 'hold_skip=true,auto_rescan=false,domain_mode=false'."
        )
    )
    error_summary: Optional[str] = Field(
        None,
        description="[audit] Exception type on job error, else null."
    )


class MdiJobState(BaseModel):
    """
    In-memory and disk-persisted job state for a running or completed MDI job.
    Mirrors the structure of vt_bulk_check JobState for conceptual consistency.
    Results are stored by normalised key to avoid duplicates.
    """
    job_id: str = Field(..., description="[audit] UUID assigned at submission.")
    status: MdiJobStatus = Field(MdiJobStatus.QUEUED, description="[display] Current job status.")
    submitted_at: float = Field(..., description="[dashboard] Submission timestamp.")
    completed_at: Optional[float] = Field(None, description="[dashboard] Completion timestamp.")
    options: MdiJobOptions = Field(
        default_factory=MdiJobOptions,
        description="[audit] Options snapshot captured at submission time."
    )
    total: int = Field(0, description="[display] Total items accepted.")
    processed: int = Field(0, description="[display] Items processed so far.")
    rejected_count: int = Field(0, description="[display] Items rejected at parse time.")
    estimated_requests: int = Field(
        0,
        description="[dashboard, reporting] Conservative VT API call estimate computed at submit time."
    )
    lookups_used: int = Field(0, description="[reporting] VT API calls consumed so far.")
    item_order: List[str] = Field(
        default_factory=list,
        description="[display] Ordered list of normalised keys for stable row display."
    )
    results_by_normalized: Dict[str, MdiResultItem] = Field(
        default_factory=dict,
        description="[display] Map of normalised_key → result."
    )
    error_message: Optional[str] = Field(None, description="[display, audit] Top-level job error.")
    usage_history_written: bool = Field(
        False,
        description="[audit] Dedup guard — prevents double-append to JSONL."
    )
