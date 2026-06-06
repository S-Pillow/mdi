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
from pydantic import BaseModel, Field, field_validator


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
    UPLOADED_FILE = "uploaded_file"  # Status extracted from operator-provided CSV/XLSX
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
    CLEAN = "clean"      # All checks passed cleanly — special case for confirmed-clean items
    UNKNOWN = "unknown"


class RecommendedAction(str, Enum):
    """
    Workflow recommendation based on triage result.
    Used for operator decision support, not auto-execution.

    MDI-10 additions (new PRD-aligned values):
      REVIEW_FOR_ACTION    — flagged but requires operator review before actioning
      VERIFY_INVESTIGATE   — ambiguous signals; verify then investigate
      REFRESH_REPORT       — VT report is stale; refresh before actioning
      REQUEST_NEW_SCAN     — VT report is very stale; request a new VT scan
      RETRY_LOOKUP         — processing error or quota block; retry when resources allow
      NO_ACTION_BASED_ON_VT — VT clean or domain appears down; no action warranted by VT alone

    Legacy values (preserved for backward compatibility with persisted jobs):
      INVESTIGATE, TAKEDOWN, MONITOR, CLEAR, ACTION_ALREADY_TAKEN, SKIP, MANUAL_REVIEW, NONE
    """
    INVESTIGATE = "investigate"
    TAKEDOWN = "takedown"
    MONITOR = "monitor"
    CLEAR = "clear"
    ACTION_ALREADY_TAKEN = "action_already_taken"
    SKIP = "skip"
    MANUAL_REVIEW = "manual_review"
    NONE = "none"
    # MDI-10 additions
    REVIEW_FOR_ACTION = "review_for_action"
    VERIFY_INVESTIGATE = "verify_investigate"
    REFRESH_REPORT = "refresh_report"
    REQUEST_NEW_SCAN = "request_new_scan"
    RETRY_LOOKUP = "retry_lookup"
    NO_ACTION_BASED_ON_VT = "no_action_based_on_vt"


class EvidenceStatus(str, Enum):
    """Whether evidence collection for this item is complete."""
    COMPLETE = "complete"
    PARTIAL = "partial"          # Some checks ran but not all
    SKIPPED_HOLD = "skipped_hold"  # Intentionally skipped — clientHold or serverHold detected
    NONE = "none"                # No checks ran; not yet processed or pre-check error


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
    triage_reason: List[str] = Field(
        default_factory=list,
        description="[display] Ordered bullet strings explaining why this triage bucket was assigned. "
                    "Empty list for items not yet processed. "
                    "Legacy recovered jobs may deserialize null as an empty list via validator."
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

    @field_validator("triage_reason", mode="before")
    @classmethod
    def _coerce_triage_reason(cls, v: object) -> List[str]:
        """Coerce legacy null / plain string values from persisted jobs."""
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v else []
        return v  # type: ignore[return-value]


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
        7,
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


# ─── Parse-preview API models ─────────────────────────────────────────────────


class ParsePreviewRequest(BaseModel):
    """Request body for POST /api/mdi/jobs/parse-preview."""
    raw_input: str = Field(
        ...,
        description="[audit] Raw pasted text containing domains and/or URLs."
    )
    default_scheme: str = Field(
        "http",
        description="[workflow] Scheme prepended to domain/path tokens that lack one.",
        pattern=r"^https?$",
    )
    max_items: int = Field(
        500,
        ge=1,
        le=500,
        description="[workflow] Maximum items to accept. Excess items are rejected.",
    )


class RejectedItemResponse(BaseModel):
    """A single item that failed normalization or exceeded limits."""
    input_original: str = Field(..., description="[display] Raw token as submitted.")
    position: int = Field(..., description="[display] 1-based position in the raw token list.")
    error: MdiError = Field(..., description="[display] Structured parse error.")


class DuplicateItemResponse(BaseModel):
    """A token whose normalized form was already accepted."""
    input_original: str = Field(..., description="[display] Raw token as submitted.")
    position: int = Field(..., description="[display] 1-based position in the raw token list.")
    duplicate_of: str = Field(..., description="[display] Normalized form it duplicates.")


class ParsePreviewResponse(BaseModel):
    """Response body for POST /api/mdi/jobs/parse-preview."""
    accepted_count: int = Field(..., description="[display] Items accepted for lookup.")
    rejected_count: int = Field(..., description="[display] Items that failed parsing.")
    duplicate_count: int = Field(..., description="[display] Items deduplicated.")
    items: List[MdiInputItem] = Field(
        ...,
        description="[display] Accepted, normalized items in first-seen order."
    )
    rejected: List[RejectedItemResponse] = Field(
        ...,
        description="[display] Rejected items with error details."
    )
    duplicates: List[DuplicateItemResponse] = Field(
        ...,
        description="[display] Duplicate tokens."
    )
    external_calls_made: bool = Field(
        False,
        description="[audit] Always false — parse-preview never contacts external services."
    )
    quota_consumed: bool = Field(
        False,
        description="[audit] Always false — parse-preview does not consume VT quota."
    )


# ─── Upload-preview API models ────────────────────────────────────────────────


class UploadedInputItem(BaseModel):
    """
    A single row extracted from a CSV or XLSX upload.

    Extends the core input-item fields with upload-derived metadata.
    Hold detection is performed offline against the uploaded EPP status column;
    no external lookups are made to confirm hold status.
    """
    # Core input identity (mirrors MdiInputItem)
    input_original: str = Field(
        ..., description="[audit] Raw domain/URL value from the uploaded cell."
    )
    input_normalized: str = Field(
        ..., description="[display, audit] Normalized form (via input_parser rules)."
    )
    input_type: InputType = Field(
        ..., description="[workflow, filtering] domain or url."
    )
    position: int = Field(
        ..., description="[display] 1-based row index in the file (after deduplication)."
    )

    # Upload-extracted fields (populated when column present)
    created_at: Optional[str] = Field(
        None, description="[display, filtering] Raw create-date string from upload."
    )
    registrar: Optional[str] = Field(
        None, description="[display, reporting] Registrar from upload."
    )
    epp_status: List[str] = Field(
        default_factory=list,
        description="[display, reporting] EPP status values extracted from upload."
    )
    assigned_nameservers: List[str] = Field(
        default_factory=list,
        description="[display, future] Nameservers extracted from upload."
    )

    # Hold detection (offline, from uploaded EPP status)
    domain_hold: DomainHold = Field(
        default_factory=DomainHold,
        description="[workflow, display] Hold status derived from uploaded EPP status."
    )
    domain_status_source: DomainStatusSource = Field(
        DomainStatusSource.UPLOADED_FILE,
        description="[audit] Always UPLOADED_FILE for upload-preview items."
    )

    # Derived from create date
    age_bucket: AgeBucket = Field(
        AgeBucket.UNKNOWN,
        description="[display, filtering] Age band derived from uploaded create date."
    )

    # Preview triage fields — populated only for held items during upload-preview
    triage_bucket: TriageBucket = Field(
        TriageBucket.PENDING,
        description="[display] Triage bucket; HELD for items with a detected hold."
    )
    recommended_action: RecommendedAction = Field(
        RecommendedAction.NONE,
        description="[display, workflow] SKIP for held items at upload-preview time."
    )
    triage_confidence: TriageConfidence = Field(
        TriageConfidence.UNKNOWN,
        description="[display] HIGH when hold status came from uploaded file."
    )
    evidence_status: EvidenceStatus = Field(
        EvidenceStatus.NONE,
        description="[audit] NONE for all upload-preview items (no checks run)."
    )
    vt_mode_used: VtModeUsed = Field(
        VtModeUsed.NOT_CHECKED,
        description="[audit] Always NOT_CHECKED or SKIPPED_HOLD at upload-preview time."
    )
    live_status: LiveStatus = Field(
        LiveStatus.NOT_CHECKED,
        description="[audit] Always NOT_CHECKED at upload-preview time."
    )

    # Row-level parse errors
    errors: List[MdiError] = Field(
        default_factory=list,
        description="[display, audit] Errors encountered parsing this row."
    )


class ColumnsDetected(BaseModel):
    """Which raw column header was matched for each canonical field."""
    domain: Optional[str] = Field(
        None, description="[display] Header matched as the domain/URL column."
    )
    created_at: Optional[str] = Field(
        None, description="[display] Header matched as the create-date column."
    )
    epp_status: Optional[str] = Field(
        None, description="[display] Header matched as the EPP/domain-status column."
    )
    registrar: Optional[str] = Field(
        None, description="[display] Header matched as the registrar column."
    )
    nameservers: Optional[str] = Field(
        None, description="[display] Header matched as the nameservers column."
    )


class UploadPreviewResponse(BaseModel):
    """Response body for POST /api/mdi/jobs/upload-preview."""
    accepted_count: int = Field(
        ..., description="[display] Rows accepted as valid, non-duplicate input items."
    )
    rejected_count: int = Field(
        ..., description="[display] Rows that could not be parsed."
    )
    duplicate_count: int = Field(
        ..., description="[display] Rows whose normalized domain was already accepted."
    )
    held_count: int = Field(
        ..., description="[display] Accepted rows with clientHold or serverHold detected."
    )
    items: List[UploadedInputItem] = Field(
        ..., description="[display] Accepted items in first-seen order."
    )
    rejected: List[RejectedItemResponse] = Field(
        ..., description="[display] Rejected rows with structured error details."
    )
    duplicates: List[DuplicateItemResponse] = Field(
        ..., description="[display] Duplicate rows."
    )
    held_items: List[UploadedInputItem] = Field(
        ..., description="[display] Subset of accepted items where domain_hold.has_hold is True."
    )
    columns_detected: ColumnsDetected = Field(
        default_factory=ColumnsDetected,
        description="[display] Column mapping used during parsing."
    )
    missing_optional_columns: List[str] = Field(
        default_factory=list,
        description="[display] Optional canonical fields with no matching column in the file."
    )
    external_calls_made: bool = Field(
        False,
        description="[audit] Always false — upload-preview never contacts external services."
    )
    quota_consumed: bool = Field(
        False,
        description="[audit] Always false — upload-preview does not consume VT quota."
    )


# ─── Job-submit API models ────────────────────────────────────────────────────


class JobSubmitRequest(BaseModel):
    """Request body for POST /api/mdi/jobs/submit."""
    raw_input: Optional[str] = Field(
        None,
        description="[audit] Raw pasted text. Mutually exclusive with 'items'."
    )
    default_scheme: str = Field(
        "http",
        description="[workflow] Scheme for tokens without a scheme.",
        pattern=r"^https?$",
    )
    max_items: int = Field(
        500, ge=1, le=500,
        description="[workflow] Max items accepted from raw_input.",
    )
    use_domain_reports: bool = Field(
        False,
        description="[workflow] Use VT domain reports for bare domains.",
    )
    stale_threshold_days: int = Field(
        7, ge=1, le=90,
        description="[workflow] Reports older than this many days are STALE.",
    )


class JobSubmitResponse(BaseModel):
    """Response body for POST /api/mdi/jobs/submit."""
    job_id: str = Field(..., description="[display] UUID of the created job.")
    status: str = Field(..., description="[display] Initial job status.")
    total: int = Field(..., description="[display] Eligible items queued for VT check.")
    queued_count: int = Field(..., description="[display] Items in VT queue.")
    held_skipped_count: int = Field(..., description="[display] Items skipped due to hold.")
    rejected_count: int = Field(..., description="[display] Items rejected at parse time.")
    estimated_requests: int = Field(..., description="[display] Conservative VT API call estimate.")
    quota_remaining_before: int = Field(..., description="[display] Quota available before job starts.")


class JobStatusResponse(BaseModel):
    """Response body for GET /api/mdi/jobs/{job_id}."""
    job_id: str
    status: str
    submitted_at: float
    completed_at: Optional[float] = None
    total: int
    processed: int
    held_skipped: int
    rejected_count: int
    queued: int
    estimated_requests: int
    lookups_used: int
    quota_blocked_count: int
    error_message: Optional[str] = None
    use_domain_reports: bool
    stale_threshold_days: int
    results: List[MdiResultItem] = Field(default_factory=list)


# ─── Estimate API models ──────────────────────────────────────────────────────


class EstimateRequest(BaseModel):
    """Request body for POST /api/mdi/jobs/estimate."""
    raw_input: str = Field(
        ...,
        description="[audit] Raw pasted text containing domains and/or URLs.",
    )
    default_scheme: str = Field(
        "http",
        description="[workflow] Scheme prepended to tokens that lack one.",
        pattern=r"^https?$",
    )
    max_items: int = Field(
        500,
        ge=1,
        le=500,
        description="[workflow] Maximum items accepted. Excess items are rejected.",
    )
    use_domain_reports: bool = Field(
        False,
        description=(
            "[workflow] When True, bare domains use the VT domain-report endpoint "
            "(1 call max). When False, bare domains use the URL-report path (up to 3 calls)."
        ),
    )
    stale_threshold_days: int = Field(
        7,
        ge=1,
        le=90,
        description="[workflow] Informational only for estimate; affects VT freshness at job time.",
    )


class EstimateResponse(BaseModel):
    """
    Response body for POST /api/mdi/jobs/estimate.

    This endpoint performs no external calls, creates no jobs, and mutates
    no runtime files.  All three audit flags below are always False.
    """
    # ── Parse counts ──────────────────────────────────────────────────────────
    accepted_count: int = Field(
        ...,
        description="[display] Items accepted by the input parser.",
    )
    rejected_count: int = Field(
        ...,
        description="[display] Items that failed normalization or exceeded limits.",
    )
    duplicate_count: int = Field(
        ...,
        description="[display] Tokens whose normalized form was already accepted.",
    )

    # ── Eligibility breakdown ─────────────────────────────────────────────────
    eligible_vt_count: int = Field(
        ...,
        description=(
            "[display] Items eligible for VT checks. For paste input this equals "
            "accepted_count because hold status is not known until WHOIS/RDAP runs."
        ),
    )
    held_skipped_count: int = Field(
        0,
        description=(
            "[display] Items that would be skipped due to a confirmed hold. "
            "Always 0 for paste input — hold status is NOT_CHECKED at estimate time."
        ),
    )

    # ── Input type breakdown ──────────────────────────────────────────────────
    domain_count: int = Field(
        ...,
        description="[display] Eligible items classified as bare domains.",
    )
    url_count: int = Field(
        ...,
        description="[display] Eligible items classified as full URLs.",
    )
    domain_report_mode_count: int = Field(
        ...,
        description=(
            "[display] Bare domains that will use the VT domain-report endpoint "
            "(1 call max). Only > 0 when use_domain_reports=True."
        ),
    )
    url_report_mode_count: int = Field(
        ...,
        description=(
            "[display] Items that will use the VT URL-report path (up to 3 calls each). "
            "Includes full URLs and bare domains when use_domain_reports=False."
        ),
    )

    # ── VT call estimate ──────────────────────────────────────────────────────
    estimated_vt_calls_min: int = Field(
        ...,
        description=(
            "[display] Optimistic estimate: all VT reports already exist. "
            "1 call per item regardless of type or mode."
        ),
    )
    estimated_vt_calls_max: int = Field(
        ...,
        description=(
            "[display] Conservative estimate: no cached reports. "
            "Domain-mode items = 1 call; URL-mode items = 3 calls (GET + POST submit + GET)."
        ),
    )

    # ── MDI-11 enrichment estimate ────────────────────────────────────────────
    estimated_enrichment_lookups: int = Field(
        0,
        description=(
            "[display] MDI-11: conservative RDAP/WHOIS lookups expected before VT. "
            "1 per accepted item (paste input has no confirmed holds at estimate time). "
            "Actual jobs deduplicate shared registered domains."
        ),
    )

    # ── Quota ─────────────────────────────────────────────────────────────────
    quota_remaining_now: int = Field(
        ...,
        description="[display] Shared VT quota remaining as of this request (read-only).",
    )
    will_exceed_quota: bool = Field(
        ...,
        description=(
            "[display] True when estimated_vt_calls_max > quota_remaining_now. "
            "The submit endpoint will hard-stop if this condition is met."
        ),
    )
    quota_headroom: int = Field(
        ...,
        description=(
            "[display] quota_remaining_now minus estimated_vt_calls_max. "
            "Negative values indicate over-quota. Zero means exactly at limit."
        ),
    )

    # ── Runtime estimate ──────────────────────────────────────────────────────
    estimated_duration_seconds_min: float = Field(
        ...,
        description=(
            "[display] Optimistic runtime in seconds. "
            "Formula: max(0, (calls_min - 1) × 15.0)"
        ),
    )
    estimated_duration_seconds_max: float = Field(
        ...,
        description=(
            "[display] Conservative runtime in seconds. "
            "Formula: max(0, (calls_max - 1) × 15.0)"
        ),
    )

    # ── Informational notes ───────────────────────────────────────────────────
    rate_limit_note: str = Field(
        ...,
        description="[display] Human-readable rate-limit explanation.",
    )
    job_state_note: str = Field(
        ...,
        description="[display] Warning that jobs are in-memory only (MDI-06/08 limitation).",
    )
    enrichment_note: str = Field(
        "",
        description="[display] MDI-11: informational note about RDAP/WHOIS enrichment overhead.",
    )

    # ── Audit / safety flags ──────────────────────────────────────────────────
    external_calls_made: bool = Field(
        False,
        description="[audit] Always False — estimate never contacts external services.",
    )
    quota_consumed: bool = Field(
        False,
        description="[audit] Always False — estimate does not consume VT quota.",
    )
    mutated: bool = Field(
        False,
        description="[audit] Always False — estimate does not write any runtime file.",
    )

    # ── Rejected / duplicate detail ───────────────────────────────────────────
    rejected: List["RejectedItemResponse"] = Field(
        default_factory=list,
        description="[display] Rejected items with error details.",
    )
    duplicates: List["DuplicateItemResponse"] = Field(
        default_factory=list,
        description="[display] Duplicate tokens.",
    )


# ─── Job state ─────────────────────────────────────────────────────────────────


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
