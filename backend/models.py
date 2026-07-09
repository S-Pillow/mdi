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
from typing import Any, Dict, List, Optional, Self
from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


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
      INVESTIGATE_HOLD     — flagged active/recent; analyst should investigate and review hold options
      REVIEW_FOR_ACTION    — flagged but requires operator review before actioning (legacy)
      VERIFY_INVESTIGATE   — ambiguous signals; verify then investigate
      REFRESH_REPORT       — VT report is stale; refresh before actioning (legacy)
      REQUEST_NEW_SCAN     — VT report is stale/very stale; request a new VT scan
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
    INVESTIGATE_HOLD = "investigate_hold"
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
    category: Optional[str] = Field(
        None,
        description="[audit] Error subsystem category, e.g. 'vt_lookup', 'rdap_whois'."
    )
    severity: Optional[str] = Field(
        None,
        description="[workflow] error | warning | skip | info — warnings/skips do not force ERROR triage."
    )
    blocks_triage: Optional[bool] = Field(
        None,
        description="[workflow] When set, overrides severity-based triage blocking. "
        "When unset, inferred from severity (only 'error' blocks by default)."
    )

    @model_validator(mode="after")
    def _infer_taxonomy_fields(self) -> Self:
        """Infer category/severity/blocks_triage for persisted errors missing MDI-22 fields."""
        from services.error_taxonomy import (
            error_blocks_triage,
            infer_error_category,
            infer_error_severity,
        )

        if self.category is None:
            self.category = infer_error_category(self.code, self.source)
        if self.severity is None:
            self.severity = infer_error_severity(self.code, self.category)
        if self.blocks_triage is None:
            self.blocks_triage = error_blocks_triage(self)
        return self


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
    vt_engine_results: Optional[List[Dict[str, Any]]] = Field(
        None,
        description=(
            "[display] Non-clean VT engine detections, malicious/suspicious only. "
            "Empty list means no malicious/suspicious engine detections. "
            "None means unavailable, pre-MDI-14 job, or VT not checked."
        ),
    )

    # ── VT URL evidence (MDI-49) — analyst context only ───────────────────────
    vt_targeted_brand: Optional[str] = Field(
        None,
        description="[display] Targeted brand from VT URL report phishing engines.",
    )
    vt_targeted_brand_sources: List[str] = Field(
        default_factory=list,
        description="[display] VT engine names that reported targeted brand evidence.",
    )
    vt_redirection_chain: List[str] = Field(
        default_factory=list,
        description="[display] VT URL redirection chain (excludes last final URL).",
    )
    vt_last_final_url: Optional[str] = Field(
        None,
        description="[display] VT last final URL after redirects.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def vt_report_url(self) -> Optional[str]:
        """[display] Public VT GUI link derived from saved row data; no API call."""
        from services.vt_gui_url import vt_gui_report_url_for_item
        return vt_gui_report_url_for_item(self)

    # ── URL live activity ─────────────────────────────────────────────────────
    live_status: LiveStatus = Field(
        LiveStatus.NOT_CHECKED,
        description="[display, filtering, reporting] Result of SSRF-safe HEAD-request probe."
    )
    live_checked_at: Optional[datetime] = Field(
        None,
        description="[display, audit] UTC timestamp when live check ran."
    )
    http_status_code: Optional[int] = Field(
        None,
        description="[display] Final HTTP status code from live check. None if not checked.",
    )
    redirect_count: int = Field(
        0,
        description="[display] Number of redirects followed during live check.",
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

    # ── Cloudflare Radar rank (MDI-50B) — popularity context only ─────────────
    cloudflare_rank_available: bool = Field(
        False,
        description="[display] True when Cloudflare returned rank or bucket data.",
    )
    cloudflare_rank: Optional[int] = Field(
        None,
        description="[display] Exact Cloudflare rank when in global top 100.",
    )
    cloudflare_rank_bucket: Optional[str] = Field(
        None,
        description="[display, filtering] Normalized popularity bucket (TOP_100 … UNRANKED).",
    )
    cloudflare_rank_raw_bucket: Optional[str] = Field(
        None,
        description="[audit] Raw bucket string from Cloudflare Radar API.",
    )
    cloudflare_rank_source: Optional[str] = Field(
        None,
        description="[audit] Rank data source identifier.",
    )
    cloudflare_rank_checked_at: Optional[datetime] = Field(
        None,
        description="[display, audit] UTC timestamp of Cloudflare rank lookup.",
    )
    cloudflare_rank_error: Optional[str] = Field(
        None,
        description="[display, audit] Sanitized Cloudflare lookup error code, if any.",
    )

    # ── Hold-impact guidance (MDI-50C) — analyst context only ─────────────────
    hold_impact_level: Optional[str] = Field(
        None,
        description="[display] Derived hold-impact level from Cloudflare rank bucket.",
    )
    hold_impact_reason: Optional[str] = Field(
        None,
        description="[display] Operator-facing hold-impact guidance text.",
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
        30,
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
        3,
        ge=0,
        le=100,
        description="[workflow] Maximum stale items to auto-rescan per job run."
    )
    cloudflare_rank_lookup_enabled: bool = Field(
        False,
        description=(
            "[workflow] When enabled, fetch Cloudflare Radar popularity rank per domain. "
            "Popularity context only; does not affect VT triage."
        ),
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


# ─── Health / version API models ──────────────────────────────────────────────


class BuildInfo(BaseModel):
    """Deploy-time build identity from build_info.json (written at deploy, not in git)."""
    app: str = Field("mdi", description="[audit] Application identifier.")
    commit: Optional[str] = Field(
        None,
        description="[audit] Git commit SHA deployed to this backend instance.",
    )
    branch: Optional[str] = Field(
        None,
        description="[audit] Git branch name at deploy time.",
    )
    built_at_utc: Optional[str] = Field(
        None,
        description="[audit] ISO-8601 UTC timestamp when the deploy marker was written.",
    )
    source: str = Field(
        ...,
        description=(
            "[audit] Marker provenance: deploy_marker, missing, or invalid."
        ),
    )


class HealthResponse(BaseModel):
    """Response body for GET /api/mdi/health."""
    status: str = Field("ok", description="[audit] Liveness status.")
    service: str = Field("mdi", description="[audit] Service name.")
    version: str = Field(
        ...,
        description="[audit] Semantic application version (not deploy commit).",
    )
    build_info: BuildInfo = Field(
        ...,
        description="[audit] Deploy-time build identity when marker file is present.",
    )


class VersionResponse(BaseModel):
    """Response body for GET /api/mdi/version."""
    build_info: BuildInfo = Field(
        ...,
        description="[audit] Deploy-time build identity.",
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
    source_row: Optional[int] = Field(
        None,
        description="[audit] 1-based row number in the source file (before deduplication).",
    )
    source_sheet: Optional[str] = Field(
        None,
        description="[audit] Worksheet name for XLSX uploads.",
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
    domain_state: Optional[str] = Field(
        None, description="[display] Header matched as the Domain State column."
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
    held_skipped_count: int = Field(
        ...,
        description="[display] Same as held_count; naming aligned with estimate endpoint.",
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
    header_row: Optional[int] = Field(
        None,
        description="[display] 1-based row number where the header row was detected.",
    )
    source_sheet: Optional[str] = Field(
        None,
        description="[display] Active worksheet name for XLSX uploads.",
    )
    external_calls_made: bool = Field(
        False,
        description="[audit] Always false — upload-preview never contacts external services."
    )
    quota_consumed: bool = Field(
        False,
        description="[audit] Always false — upload-preview does not consume VT quota."
    )


# ─── Job action API models (MDI-15) ───────────────────────────────────────────


class RefreshScanScope(str, Enum):
    """Scope for refresh/rescan actions on an existing job."""
    SELECTED = "selected"
    STALE = "stale"
    PENDING = "pending"  # MDI-57B: all pending-analysis URL rows


class JobActionRequest(BaseModel):
    """Request body for POST /api/mdi/jobs/{job_id}/refresh and /scan."""
    scope: RefreshScanScope = Field(
        ...,
        description=(
            "[workflow] selected rows by position, all stale eligible rows, "
            "or all pending-analysis URL rows (refresh only)."
        ),
    )
    positions: Optional[List[int]] = Field(
        None,
        description="[workflow] 1-based row positions; required when scope=selected.",
    )
    confirm: bool = Field(
        True,
        description="[workflow] Operator confirmed quota impact (scan actions).",
    )
    estimate_only: bool = Field(
        False,
        description="[workflow] Return quota estimate only; do not start action.",
    )


class JobActionEstimateResponse(BaseModel):
    """Quota estimate for a refresh or scan action batch."""
    job_id: str
    action: str
    scope: str
    eligible_count: int
    skipped_count: int
    skipped_reasons_summary: Dict[str, int] = Field(default_factory=dict)
    estimated_quota_min: int
    estimated_quota_max: int
    quota_remaining: int
    will_exceed_quota: bool
    message: str
    url_scan_eligible_count: int = Field(
        0,
        description="[display] Scan-eligible URL-report rows (URL scan path).",
    )
    domain_rescan_eligible_count: int = Field(
        0,
        description="[display] Scan-eligible domain-report rows (domain rescan path).",
    )
    pending_eligible_count: int = Field(
        0,
        description="[display] Pending-analysis URL rows eligible for Bulk Refresh Pending (MDI-57B).",
    )


class JobActionAcceptedResponse(BaseModel):
    """Response when a refresh/scan action is accepted and running in background."""
    job_id: str
    action: str
    status: str = "accepted"
    items_queued: int
    items_skipped: int
    estimated_quota_min: int
    estimated_quota_max: int
    quota_remaining: int


# ─── Export API models (MDI-16) ───────────────────────────────────────────────


class ExportFormat(str, Enum):
    """Output format for job export downloads."""
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"


class ExportScope(str, Enum):
    """Row selection scope for job export downloads."""
    ALL = "all"
    FLAGGED = "flagged"
    SELECTED = "selected"


class ExportRequest(BaseModel):
    """Request body for POST /api/mdi/jobs/{job_id}/export."""
    format: ExportFormat = Field(
        ...,
        description="[workflow] csv or xlsx for 10-column analyst export; json for evidence bundle.",
    )
    scope: ExportScope = Field(
        ...,
        description="[workflow] all rows, flagged rows only, or selected positions.",
    )
    positions: Optional[List[int]] = Field(
        None,
        description=(
            "[workflow] 1-based row positions; required when scope=selected. "
            "Ignored for all/flagged scopes."
        ),
    )

    @model_validator(mode="after")
    def _validate_selected_positions(self) -> "ExportRequest":
        if self.scope == ExportScope.SELECTED and not self.positions:
            raise ValueError("positions is required when scope is 'selected'.")
        return self


# ─── Dashboard API models (MDI-17) ─────────────────────────────────────────────


class DashboardDataQuality(BaseModel):
    """Metadata about dashboard history read quality."""
    history_file_present: bool = False
    source_filter: str = "mdi"
    records_read: int = 0
    records_skipped: int = 0
    records_non_mdi_skipped: int = 0
    records_filtered_out: int = 0
    records_by_source: Dict[str, int] = Field(default_factory=lambda: {
        "mdi": 0,
        "vt_bulk_check": 0,
        "legacy": 0,
    })
    records_missing_triage_fields: int = 0
    records_missing_duration_fields: int = 0
    notes: List[str] = Field(default_factory=list)


class DashboardQuotaTrend(BaseModel):
    """Read-only daily quota trend from vt_daily_history.json."""
    available: bool = False
    source: str = "vt_daily_history.json"
    last_7_days: List[Dict[str, Any]] = Field(default_factory=list)


class DashboardLiveQuota(BaseModel):
    """Read-only shared live VT counter snapshot for dashboard display."""
    available: bool = False
    date_utc: Optional[str] = None
    daily_lookups_used: Optional[int] = None
    daily_limit: int = 500
    remaining: Optional[int] = None
    error: Optional[str] = None


class DashboardResponse(BaseModel):
    """Operational dashboard summary — aggregate metadata only."""
    generated_at: str
    source_filter: str = "mdi"
    windows: Dict[str, Any]
    quota_trend: DashboardQuotaTrend
    live_quota: DashboardLiveQuota = Field(default_factory=DashboardLiveQuota)
    data_quality: DashboardDataQuality


# ─── Job-submit API models ────────────────────────────────────────────────────


class JobSubmitRequest(BaseModel):
    """Request body for POST /api/mdi/jobs/submit."""
    raw_input: Optional[str] = Field(
        None,
        description="[audit] Raw pasted text. Mutually exclusive with items (paste mode).",
    )
    items: Optional[List[UploadedInputItem]] = Field(
        None,
        description="[workflow] Upload-validated items from upload-preview (upload mode).",
    )
    input_mode: str = Field(
        "paste",
        description="[audit] paste or upload — indicates which input path was used.",
        pattern=r"^(paste|upload)$",
    )
    default_scheme: str = Field(
        "http",
        description="[workflow] Scheme for tokens without a scheme.",
        pattern=r"^https?$",
    )
    max_items: int = Field(
        500, ge=1, le=500,
        description="[workflow] Max items accepted from raw_input or items.",
    )
    use_domain_reports: bool = Field(
        False,
        description="[workflow] Use VT domain reports for bare domains.",
    )
    stale_threshold_days: int = Field(
        30, ge=1, le=90,
        description="[workflow] Reports older than this many days are STALE.",
    )
    auto_rescan_stale: bool = Field(
        False,
        description="[workflow] Auto-request VT scan for stale flagged URL-mode items.",
    )
    max_auto_rescans: int = Field(
        3, ge=0, le=25,
        description="[workflow] Max auto-rescans per job when auto_rescan_stale is enabled.",
    )
    cloudflare_rank_lookup_enabled: bool = Field(
        False,
        description="[workflow] Fetch Cloudflare Radar rank (popularity context only).",
    )

    @model_validator(mode="after")
    def _validate_input_source(self) -> "JobSubmitRequest":
        if self.items:
            if self.raw_input and self.raw_input.strip():
                raise ValueError("Provide raw_input or items, not both.")
            object.__setattr__(self, "input_mode", "upload")
        elif self.raw_input is not None:
            object.__setattr__(self, "input_mode", "paste")
        else:
            raise ValueError("Provide raw_input (paste mode) or items (upload mode).")
        return self


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
    quota_lock_timeout_count: int = Field(
        0,
        description="[display] Items skipped due to shared VT quota lock timeout.",
    )
    error_message: Optional[str] = None
    use_domain_reports: bool
    stale_threshold_days: int
    cloudflare_rank_lookup_enabled: bool = Field(
        False,
        description="[display] Whether Cloudflare Radar rank lookup was enabled for this job.",
    )
    results: List[MdiResultItem] = Field(default_factory=list)
    # ── MDI-11 enrichment counters ─────────────────────────────────────────────
    rdap_enriched_count: int = Field(
        0, description="[display] Items enriched via RDAP/WHOIS before VT."
    )
    rdap_failed_count: int = Field(
        0, description="[display] Items where RDAP/WHOIS enrichment failed (non-fatal)."
    )
    whois_fallback_count: int = Field(
        0, description="[display] Items where WHOIS fallback was used instead of RDAP."
    )
    hold_detected_by_enrichment_count: int = Field(
        0, description="[display] Items where live RDAP/WHOIS detected a domain hold."
    )
    # ── MDI-12 live-check counters ─────────────────────────────────────────────
    live_check_count: int = Field(
        0, description="[display] Items that received a live HTTP check."
    )
    live_check_skipped_count: int = Field(
        0, description="[display] Items skipped by live-check eligibility rules (clean, held, error)."
    )
    live_check_error_count: int = Field(
        0, description="[display] Items where the live check returned a structured error."
    )
    # ── MDI-15 job action state ──────────────────────────────────────────────────
    action_in_progress: bool = Field(
        False, description="[display, workflow] True while refresh/scan action is running."
    )
    last_action_type: Optional[str] = Field(
        None, description="[audit] Last action: refresh or scan."
    )
    last_action_at: Optional[float] = Field(
        None, description="[audit] Unix timestamp of last refresh/scan completion."
    )
    # ── MDI-59 progress phase ───────────────────────────────────────────────────
    current_phase: Optional[str] = Field(
        None,
        description=(
            "[display] Stable progress-phase token while a job or manual action runs "
            "(e.g. enriching, checking_virustotal, refresh_pending). Null when idle/terminal."
        ),
    )
    current_phase_detail: Optional[str] = Field(
        None,
        description="[display] Optional short human detail for the current phase; usually null.",
    )
    vt_refresh_count: int = Field(
        0, description="[display] Cumulative manual refresh operations on this job."
    )
    vt_scan_requested_count: int = Field(
        0, description="[display] Cumulative manual scan requests on this job."
    )
    vt_scan_failed_count: int = Field(
        0, description="[display] Cumulative scan failures on this job."
    )
    # ── MDI-15A auto-rescan options and counters ───────────────────────────────
    auto_rescan_stale: bool = Field(
        False, description="[display] Saved job option: auto-rescan enabled at submit."
    )
    max_auto_rescans: int = Field(
        3, description="[display] Saved job option: max auto-rescans per job."
    )
    input_mode: str = Field(
        "paste",
        description="[display] Input path used at submit: paste or upload.",
    )
    auto_rescan_attempted_count: int = Field(
        0, description="[display] Auto-rescan VT scan attempts during initial processing."
    )
    auto_rescan_completed_count: int = Field(
        0, description="[display] Auto-rescans that returned an updated VT report."
    )
    auto_rescan_failed_count: int = Field(
        0, description="[display] Auto-rescans that failed or returned scan pending."
    )
    auto_rescan_skipped_count: int = Field(
        0, description="[display] Items evaluated but skipped for auto-rescan."
    )
    auto_rescan_quota_blocked_count: int = Field(
        0, description="[display] Auto-rescans skipped due to insufficient quota."
    )


# ─── Estimate API models ──────────────────────────────────────────────────────


class EstimateRequest(BaseModel):
    """Request body for POST /api/mdi/jobs/estimate."""
    raw_input: Optional[str] = Field(
        None,
        description="[audit] Raw pasted text (paste mode). Mutually exclusive with items.",
    )
    items: Optional[List[UploadedInputItem]] = Field(
        None,
        description="[workflow] Upload-validated items from upload-preview (upload mode).",
    )
    input_mode: str = Field(
        "paste",
        description="[audit] paste or upload.",
        pattern=r"^(paste|upload)$",
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
            "(1 call max). When False, bare domains use the URL-report path (up to 2 calls: "
            "GET, then POST submit-only if VT has no report)."
        ),
    )
    stale_threshold_days: int = Field(
        30,
        ge=1,
        le=90,
        description="[workflow] Informational only for estimate; affects VT freshness at job time.",
    )
    auto_rescan_stale: bool = Field(
        False,
        description="[workflow] Include conservative auto-rescan quota in estimate.",
    )
    max_auto_rescans: int = Field(
        3, ge=0, le=25,
        description="[workflow] Max auto-rescans per job for estimate upper bound.",
    )

    @model_validator(mode="after")
    def _validate_input_source(self) -> "EstimateRequest":
        if self.items:
            if self.raw_input and self.raw_input.strip():
                raise ValueError("Provide raw_input or items, not both.")
            object.__setattr__(self, "input_mode", "upload")
        elif self.raw_input is not None:
            object.__setattr__(self, "input_mode", "paste")
        else:
            raise ValueError("Provide raw_input (paste mode) or items (upload mode).")
        return self


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
            "[display] Items that will use the VT URL-report path (up to 2 calls each). "
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
            "Domain-mode items = 1 call; URL-mode items = 2 calls (GET + POST submit-only). "
            "Submitted URLs become pending-analysis rows; a later operator Refresh Report "
            "costs 1 call per pending row and is not included in this estimate."
        ),
    )
    auto_rescan_estimated_quota_min: int = Field(
        0,
        description="[display] MDI-15A: minimum additional VT calls from auto-rescan (always 0).",
    )
    auto_rescan_estimated_quota_max: int = Field(
        0,
        description="[display] MDI-15A: worst-case additional VT calls from auto-rescan.",
    )
    auto_rescan_domain_eligible_max: int = Field(
        0,
        description="[display] MDI-28C: worst-case domain-report auto-rescan slots.",
    )
    auto_rescan_url_eligible_max: int = Field(
        0,
        description="[display] MDI-28C: worst-case URL-mode auto-rescan slots.",
    )
    total_estimated_vt_calls_max: int = Field(
        ...,
        description=(
            "[display] Base worst-case VT calls plus auto-rescan worst-case. "
            "Submit guard uses this when auto-rescan is enabled."
        ),
    )
    auto_rescan_estimated_duration_seconds_min: float = Field(
        0.0,
        description="[display] MDI-15A: minimum additional runtime from auto-rescan.",
    )
    auto_rescan_estimated_duration_seconds_max: float = Field(
        0.0,
        description="[display] MDI-15A: worst-case additional runtime from auto-rescan.",
    )
    auto_rescan_note: str = Field(
        "",
        description="[display] MDI-15A: informational note about conditional auto-rescan usage.",
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
    estimated_enrichment_duration_seconds_min: float = Field(
        0.0,
        description=(
            "[display] MDI-11A: best-case enrichment time (0 s — all items share one "
            "registered domain; 1 lookup hits per-job cache)."
        ),
    )
    estimated_enrichment_duration_seconds_max: float = Field(
        0.0,
        description=(
            "[display] MDI-11A: worst-case enrichment time: N × 1.1 s "
            "(every item is a unique registered domain; rdap.org rate limit enforced)."
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
            "[display] True when total_estimated_vt_calls_max > quota_remaining_now. "
            "The submit endpoint will hard-stop if this condition is met."
        ),
    )
    quota_headroom: int = Field(
        ...,
        description=(
            "[display] quota_remaining_now minus total_estimated_vt_calls_max. "
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
    url_submit_note: str = Field(
        "",
        description=(
            "[display] MDI-57A: non-empty when URL-report-mode items are present. "
            "Explains that unknown URLs are submitted to VT (submit-only, 2 calls max), "
            "become pending-analysis rows, and need a later 1-call Refresh Report. "
            "No automatic pending refresh occurs."
        ),
    )
    enrichment_warning: str = Field(
        "",
        description=(
            "[display] MDI-11A: non-empty when enrichment_lookups > 100. "
            "Warns that RDAP throttling may add significant runtime "
            "(e.g. ~9+ minutes for 500 unique domains)."
        ),
    )

    # ── MDI-12 live-check estimate ─────────────────────────────────────────────
    estimated_live_check_count: int = Field(
        0,
        description=(
            "[display] MDI-12: always 0 at estimate time because the number of "
            "flagged/suspicious items is not known until VT processing completes. "
            "Live checks run conditionally after VT."
        ),
    )
    live_check_note: str = Field(
        "",
        description=(
            "[display] MDI-12: informational note about live-check behaviour "
            "and conditional timing."
        ),
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
