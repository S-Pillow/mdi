# MDI Field-Purpose Map

Each field in `MdiResultItem` and related models is classified by its
primary purpose.  A field may serve more than one purpose; the primary
purpose determines where it must be present (display, export, etc.).

Purpose categories:
- **display**       — rendered in the results table or detail drawer
- **workflow**      — used to drive hold-skip, rescan, or routing decisions
- **filtering**     — used for client-side or server-side filter/sort
- **reporting**     — required in CSV export and JSONL usage history
- **audit**         — retained for debugging; not shown in the main UI by default
- **dashboard**     — metadata-only; shown in job history without item-level data
- **future**        — defined for schema stability; not yet populated

---

## Item-level fields (`MdiResultItem`)

### Identity

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `input_original` | `str` | display, reporting | Raw string as submitted. Never logged externally. |
| `input_normalized` | `str` | display, reporting, audit | Normalized form used for all lookups. |
| `input_type` | `InputType` | display, filtering | `domain` or `url`. Determines which VT report type is used by default. |
| `position` | `int` | display | 1-based stable row order matching original input. |
| `processing_status` | `MdiProcessingStatus` | display, workflow | `pending`, `hold_skipped`, `done`, `error`. |

### Domain hold

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `domain_hold.has_hold` | `bool` | workflow | If true, VT and live checks are skipped by default. |
| `domain_hold.hold_types` | `List[DomainHoldType]` | workflow, display | `clientHold`, `serverHold`, or `none`. Multiple may be present. |
| `domain_hold.source` | `DomainStatusSource` | audit | Which data source provided hold status: `rdap`, `whois`, `unknown`. |
| `domain_hold.raw_statuses` | `List[str]` | audit | Raw EPP status strings from the registry. Not shown in main UI. |

### WHOIS / RDAP

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `registrar` | `Optional[str]` | display, reporting | Registrar name from RDAP/WHOIS. |
| `created_at` | `Optional[datetime]` | display, filtering, reporting | Domain registration date (UTC). Basis for `age_bucket`. |
| `age_bucket` | `AgeBucket` | display, filtering | `very_new`, `new`, `established`, `mature`, `unknown`. Derived from `created_at`. |
| `epp_status` | `List[str]` | display, reporting | Full EPP status list (e.g. `clientTransferProhibited`). |
| `nameservers` | `List[str]` | display, future | Nameservers from RDAP/WHOIS. Not used in triage logic yet. |

### VirusTotal

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `vt_mode_used` | `VtModeUsed` | audit | `url_report`, `domain_report`, `not_checked`, `skipped_hold`, `skipped_quota`. |
| `vt_hits` | `Optional[int]` | display, filtering, reporting | Malicious engine count. Primary triage signal. |
| `vt_suspicious` | `Optional[int]` | display, filtering, reporting | Suspicious engine count. Secondary triage signal. |
| `vt_total_engines` | `Optional[int]` | display, reporting | Denominator for `vt_ratio`. |
| `vt_ratio` | `Optional[str]` | display | Human-readable string, e.g. `"3/72"`. Derived from `vt_hits`/`vt_total_engines`. |
| `vt_scan_date` | `Optional[datetime]` | display, filtering, reporting | UTC timestamp of the VT scan used. Basis for `freshness`. |
| `freshness` | `Freshness` | display, filtering, workflow | `fresh` (<5d), `stale` (5–30d), `very_stale` (>30d), `never_scanned`, `unknown`. Drives auto-rescan eligibility. |
| `vt_engine_results` | `Optional[Dict]` | future | Raw per-engine VT results. Excluded from exports by default. Added for schema stability only. |

### URL live activity

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `live_status` | `LiveStatus` | display, filtering, reporting | HEAD-request result: `active`, `redirect`, `not_found`, `timeout`, `dns_failure`, `blocked`, etc. |
| `live_checked_at` | `Optional[datetime]` | display, audit | UTC timestamp when the live check ran. |

### Triage

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `triage_bucket` | `TriageBucket` | display, filtering, reporting | `malicious`, `suspicious`, `held`, `clean`, `unresolvable`, `error`, `pending`. Top-level classification. |
| `triage_reason` | `Optional[str]` | display | Short plain-language explanation, e.g. `"VT: 5 engines flagged malicious"`. |
| `triage_confidence` | `TriageConfidence` | display, filtering | `high`, `medium`, `low`, `unknown`. |
| `recommended_action` | `RecommendedAction` | display, workflow | `investigate`, `takedown`, `monitor`, `clear`, `skip`, `manual_review`, `none`. Operator guidance only. |
| `evidence_status` | `EvidenceStatus` | display, audit | `complete`, `partial`, `none`. Whether all expected checks ran. |

### Errors

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `errors` | `List[MdiError]` | display, audit | Structured per-item errors. `code`, `message`, `source`, `retriable`. |
| `errors[].code` | `str` | audit | Machine-readable error code, e.g. `vt_429`, `rdap_timeout`. |
| `errors[].message` | `str` | display | Human-readable message shown in detail drawer. |
| `errors[].source` | `str` | audit | Which service/step errored: `vt`, `rdap`, `url_check`. |
| `errors[].retriable` | `bool` | workflow | Whether a retry may succeed. Drives retry-UI visibility. |

---

## Job-level fields (`MdiJobSummary` — metadata-only dashboard record)

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `ts` | `float` | dashboard, reporting | Unix completion timestamp. |
| `tool_name` | `str` | reporting | Always `"mdi"`. Distinguishes MDI records from vt-bulk-check in shared JSONL. |
| `job_id` | `str` | dashboard, reporting | UUID. |
| `operation` | `str` | reporting | `report_lookup`, `refresh`, `force_scan`, `auto_rescan`. |
| `status` | `MdiJobStatus` | dashboard | `done` or `error`. |
| `submitted_at` | `float` | dashboard | Unix submission timestamp. |
| `completed_at` | `float` | dashboard, reporting | Unix completion timestamp. |
| `accepted_count` | `int` | dashboard, reporting | Items accepted after parse. |
| `rejected_count` | `int` | dashboard, reporting | Items rejected at parse time (invalid input). |
| `processed` | `int` | dashboard, reporting | Items actually processed (may be less than accepted if quota hit). |
| `total` | `int` | dashboard, reporting | Same as `accepted_count`. Kept for consistency with vt-bulk-check. |
| `domain_count` | `int` | reporting | Bare domains in input. |
| `url_count` | `int` | reporting | Full URLs in input. |
| `items_held_skipped` | `int` | reporting | Items skipped due to hold. Not in vt-bulk-check schema — new MDI-specific field. |
| `actual_lookups` | `int` | reporting | VT API calls consumed. |
| `estimated_requests` | `int` | reporting | Quota estimate at submit time. |
| `quota_blocked_count` | `int` | reporting | Items not processed due to quota limit. |
| `errors_count` | `int` | reporting | Non-quota processing errors. |
| `auto_rescan_enabled` | `bool` | reporting | Whether auto-rescan was active. |
| `use_domain_reports` | `bool` | reporting | Whether domain-report mode was active. |
| `processing_options_summary` | `str` | audit | Short key=value string, e.g. `"hold_skip=true,auto_rescan=false"`. |
| `error_summary` | `Optional[str]` | audit | Exception type on job error, else null. |

---

---

## Upload-preview fields (`UploadedInputItem`) — MDI-05

Fields added when input comes from a CSV or XLSX upload rather than pasted text.
The core identity fields (`input_original`, `input_normalized`, `input_type`, `position`)
are identical to `MdiInputItem`.

### Upload-extracted metadata

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `created_at` | `str \| null` | display, filtering | Raw create-date string from the uploaded cell. Not parsed to datetime here to preserve original value. |
| `registrar` | `str \| null` | display, reporting | Registrar name from upload; never looked up externally. |
| `epp_status` | `List[str]` | display, reporting | Individual EPP status tokens extracted from the status column. |
| `assigned_nameservers` | `List[str]` | display, future | Nameservers from upload; lowercase and FQDN-dot-stripped. |

### Hold detection fields (offline)

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `domain_hold` | `DomainHold` | workflow, display | Hold status derived purely from uploaded EPP status column. `has_hold=true` if `clientHold` or `serverHold` present. `source=uploaded_file`. `source=not_checked` if status column absent/blank. |
| `domain_status_source` | `DomainStatusSource` | audit | Always `uploaded_file` for upload-preview items. Distinguishes from future RDAP/WHOIS results. |

### Derived fields

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `age_bucket` | `AgeBucket` | display, filtering | Derived from uploaded `created_at` date. `unknown` when date is absent or unparseable. Bands: `very_new` (<30d), `new` (30–180d), `established` (180d–2yr), `mature` (>2yr). |

### Preview triage fields (populated for held items only at upload-preview time)

| Field | Type | Value for held item | Value for non-held item |
|---|---|---|---|
| `triage_bucket` | `TriageBucket` | `held` ("Domain On Hold") | `pending` |
| `recommended_action` | `RecommendedAction` | `action_already_taken` ("Action Already Taken" — registry hold is the action) | `none` |
| `triage_confidence` | `TriageConfidence` | `high` (status from uploaded file) | `unknown` |
| `evidence_status` | `EvidenceStatus` | `skipped_hold` ("Skipped — On Hold") | `none` |
| `vt_mode_used` | `VtModeUsed` | `skipped_hold` | `not_checked` |
| `live_status` | `LiveStatus` | `not_checked` | `not_checked` |

### Column detection (`ColumnsDetected`)

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `domain` | `str \| null` | display | Which raw column header was matched as the domain/URL column. |
| `created_at` | `str \| null` | display | Which raw column header was matched as the create-date column. |
| `epp_status` | `str \| null` | display | Which raw column header was matched as the EPP/domain-status column. |
| `registrar` | `str \| null` | display | Which raw column header was matched as the registrar column. |
| `nameservers` | `str \| null` | display | Which raw column header was matched as the nameservers column. |

### Enum additions — MDI-05

| Enum | New value | Purpose |
|---|---|---|
| `DomainStatusSource` | `uploaded_file` | Marks hold status as derived from operator-provided CSV/XLSX, not RDAP/WHOIS. |
| `RecommendedAction` | `action_already_taken` | The registry hold IS the action; operator should acknowledge and close, not investigate. Distinct from `skip` (generic non-hold skip). |
| `EvidenceStatus` | `skipped_hold` | Evidence collection was intentionally skipped because clientHold or serverHold was detected. Distinct from `none` (not yet processed / pre-check error). |

---

## MDI-06 VT service fields and behavior

### VT normalization translation (`vt_service._build_vt_target`)

MDI's input_parser stores normalized items in two forms:
- `InputType.DOMAIN` → stored as `"example.com"` (bare domain, no scheme)
- `InputType.URL` → stored as full URL e.g. `"https://example.net/path"`

The VT API lookup target is derived in `vt_service._build_vt_target()`, NOT in the parser:

| `input_type` | `use_domain_reports` | VT target | `vt_mode_used` |
|---|---|---|---|
| `domain` | `false` | `http://{domain}/` | `url_report` |
| `domain` | `true` | `{domain}` (bare) | `domain_report` |
| `url` | any | normalized URL unchanged | `url_report` |

This translation happens in the service layer to avoid mutating the stored normalized form.

### VT quota accounting

| Scenario | VT calls consumed |
|---|---|
| URL or domain (URL mode) — cached in VT | 1 (GET succeeds) |
| URL or domain (URL mode) — not in VT | 3 (GET 404 + POST submit + GET again) |
| Domain (domain-report mode) | 1 (GET domains endpoint; no 404→submit flow) |
| VT 429 | 1 (the failing call is counted; quota still incremented) |
| VT timeout | 0 (exception before response; not counted) |

Quota is incremented per `calls_made` reported by `vt_service.fetch_report()`.
Atomic write: `vt_usage.json.tmp → os.replace() → vt_usage.json`.

### Triage mapping (MDI-06)

| Condition | `triage_bucket` | `recommended_action` | `evidence_status` |
|---|---|---|---|
| `vt_malicious > 0` | `malicious` | `investigate` | `complete` |
| `vt_malicious == 0, vt_suspicious > 0` | `suspicious` | `manual_review` | `complete` |
| Both 0, engines > 0 | `clean` | `clear` | `complete` |
| Both 0, engines == 0 (never scanned) | `pending` | `none` | `partial` |
| VT error (429, 5xx, timeout) | `error` | `manual_review` | `partial` |
| Confirmed hold (held item) | `held` | `action_already_taken` | `skipped_hold` |
| Quota exhausted mid-run | `error` | `manual_review` | `partial` |

### Freshness classification (`vt_service.classify_freshness`)

| `last_analysis_date` age | `freshness` | `triage_confidence` |
|---|---|---|
| < stale_threshold_days (default 5) | `fresh` | `high` |
| 5–30 days | `stale` | `medium` |
| > 30 days | `very_stale` | `medium` |
| None / null | `never_scanned` | `low` |

### In-memory job state fields (`InMemoryJob` in `job_store.py`)

| Field | Type | Notes |
|---|---|---|
| `job_id` | `str` | UUID assigned at submission |
| `status` | `str` | `queued`, `running`, `done`, `error` |
| `submitted_at` | `float` | Unix timestamp |
| `completed_at` | `Optional[float]` | Set on completion or error |
| `total` | `int` | Eligible VT-queue items (not counting held) |
| `processed` | `int` | Items where VT attempt completed |
| `held_skipped` | `int` | Items skipped because of hold |
| `rejected_count` | `int` | Items rejected at parse time |
| `quota_blocked_count` | `int` | Items blocked mid-run by quota exhaustion |
| `estimated_requests` | `int` | Conservative VT API call estimate |
| `lookups_used` | `int` | Actual VT API calls consumed |
| `use_domain_reports` | `bool` | Options snapshot from submit request |
| `stale_threshold_days` | `int` | Options snapshot |
| `item_order` | `List[str]` | Stable display order (input_normalized keys) |
| `results` | `Dict[str, MdiResultItem]` | Per-item results, key = input_normalized |
| `usage_history_written` | `bool` | Dedup guard for JSONL append |

**Known MDI-06 limitation:** Jobs are in-memory only. Service restart loses all job state.
Job persistence and recovery are out of scope for MDI-06.

### New API models (MDI-06)

| Model | Fields | Purpose |
|---|---|---|
| `JobSubmitRequest` | `raw_input`, `default_scheme`, `max_items`, `use_domain_reports`, `stale_threshold_days` | POST /api/mdi/jobs/submit request body |
| `JobSubmitResponse` | `job_id`, `status`, `total`, `queued_count`, `held_skipped_count`, `rejected_count`, `estimated_requests`, `quota_remaining_before` | Immediate response after job creation |
| `JobStatusResponse` | `job_id`, `status`, `processed`, `total`, `results`, … | GET /api/mdi/jobs/{job_id} response |

---

## EstimateResponse fields (MDI-07)

`EstimateResponse` is the response body for `POST /api/mdi/jobs/estimate`.
This endpoint performs no external calls, creates no jobs, and mutates no runtime files.

### Parse-count fields

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `accepted_count` | `int` | display | Items accepted by the input parser. |
| `rejected_count` | `int` | display | Items that failed normalization or exceeded `max_items`. |
| `duplicate_count` | `int` | display | Tokens whose normalized form was already accepted. |

### Eligibility fields

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `eligible_vt_count` | `int` | display | Items eligible for VT checks. Equals `accepted_count` for paste input (hold status is NOT_CHECKED). |
| `held_skipped_count` | `int` | display | Items confirmed-held that contribute 0 VT calls. Always `0` for paste input. Reserved for future upload-items path. |

### Input-type breakdown fields

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `domain_count` | `int` | display | Eligible items classified as bare domains. |
| `url_count` | `int` | display | Eligible items classified as full URLs. |
| `domain_report_mode_count` | `int` | display | Bare domains using the VT domain-report endpoint (1 call max, only when `use_domain_reports=True`). |
| `url_report_mode_count` | `int` | display | Items using the VT URL-report path (up to 3 calls each). Includes full URLs and bare domains when `use_domain_reports=False`. |

### VT call estimate fields

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `estimated_vt_calls_min` | `int` | display | Optimistic estimate: all VT reports already cached. 1 call per item regardless of type or mode. |
| `estimated_vt_calls_max` | `int` | display | Conservative estimate: no cached reports. Domain-mode items = 1; URL-mode items = 3 (GET + POST submit + GET). This value is also used by the submit endpoint's quota hard-stop. |

### Quota fields

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `quota_remaining_now` | `int` | display | Shared VT quota remaining as of this request. Read from `vt_usage.json` (read-only, no increment). |
| `will_exceed_quota` | `bool` | display, workflow | `True` when `estimated_vt_calls_max > quota_remaining_now`. The submit endpoint will hard-stop if this is `True`. |
| `quota_headroom` | `int` | display | `quota_remaining_now - estimated_vt_calls_max`. Negative = over-quota. Zero = at limit. |

### Runtime estimate fields

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `estimated_duration_seconds_min` | `float` | display | Optimistic runtime. Formula: `max(0, (calls_min - 1) × 15.0)`. |
| `estimated_duration_seconds_max` | `float` | display | Conservative runtime. Formula: `max(0, (calls_max - 1) × 15.0)`. |

### Informational note fields

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `rate_limit_note` | `str` | display | Human-readable explanation of the VT free-tier rate limit (4 req/min, 15s intervals). |
| `job_state_note` | `str` | display | Warning that jobs are in-memory only and lost on service restart (MDI-06/08 limitation). |

### Audit/safety flags

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `external_calls_made` | `bool` | audit | Always `False`. Estimate never contacts external services. |
| `quota_consumed` | `bool` | audit | Always `False`. Estimate does not consume VT quota. |
| `mutated` | `bool` | audit | Always `False`. Estimate does not write any runtime file. |

### Detail lists

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `rejected` | `List[RejectedItemResponse]` | display | Rejected items with parse error details. Same structure as parse-preview. |
| `duplicates` | `List[DuplicateItemResponse]` | display | Duplicate tokens. Same structure as parse-preview. |

### Estimate formula summary

The estimate formula in `services/estimate.py` is the single authoritative source
shared between `POST /api/mdi/jobs/estimate` and `POST /api/mdi/jobs/submit`.
Both endpoints call `estimate_job()` to guarantee frontend/backend parity.

| Item type | `use_domain_reports` | calls_min | calls_max |
|---|---|---|---|
| Bare domain | `True` (domain-report mode) | 1 | 1 |
| Bare domain | `False` (URL-report mode) | 1 | 3 |
| Full URL | any | 1 | 3 |
| Confirmed hold | any | 0 | 0 |

Runtime formula: `max(0, (calls - 1) × 15.0)` seconds per bound.

---

## Job persistence and recovery fields (MDI-08)

### `mdi_latest_job.json` — persisted field inventory

The recovery file is a JSON serialization of `InMemoryJob`.  All fields are
preserved for exact round-trip fidelity.

| Field | Type | Persisted? | Purpose |
|---|---|---|---|
| `job_id` | `str` | Yes | UUID — preserved exactly; never regenerated on recovery |
| `status` | `str` | Yes | `done` or `error` — only these values are persisted |
| `submitted_at` | `float` | Yes | Unix timestamp; preserved for age display |
| `completed_at` | `float` | Yes | Unix timestamp; preserved for display |
| `total` | `int` | Yes | Total eligible VT-queue items |
| `processed` | `int` | Yes | Items where VT attempt completed |
| `held_skipped` | `int` | Yes | Items skipped due to hold |
| `rejected_count` | `int` | Yes | Parse-time rejections |
| `quota_blocked_count` | `int` | Yes | Items blocked by mid-run quota |
| `estimated_requests` | `int` | Yes | Conservative pre-submit estimate |
| `lookups_used` | `int` | Yes | Actual VT API calls consumed |
| `use_domain_reports` | `bool` | Yes | Options snapshot |
| `stale_threshold_days` | `int` | Yes | Options snapshot |
| `error_message` | `str\|null` | Yes | Top-level job error if status=error |
| `item_order` | `List[str]` | Yes | Stable display order (normalized keys) — **contains raw domains/URLs** |
| `results` | `Dict[str, MdiResultItem]` | Yes | Per-item VT results — **keys and some fields contain raw domains/URLs** |
| `usage_history_written` | `bool` | Yes | Dedup guard; prevents double-append if somehow called again |

**Data sensitivity note:** `item_order` and `results` keys contain normalized
domains/URLs (e.g., `"example.com"`, `"http://malicious.test/"`).  This is
intentional and justified — see `runtime-data.md` §MDI-08 for the full rationale.
This data never appears in `vt_usage_history.jsonl`.

### Recovery endpoint fields

`GET /api/mdi/jobs/latest` returns `JobStatusResponse` — the same model as
`GET /api/mdi/jobs/{job_id}`.  No new response model is needed.

### Frontend recovery state

| State variable | Type | Purpose |
|---|---|---|
| `restoredFromSession` | `bool` | Set to `true` when `/api/mdi/jobs/latest` returns a job on mount. Controls "↩ Restored from last session" notice. |

The notice is dismissible (user can click ✕).  It is automatically cleared when
the user submits a new job via "Run MDI Check".

### Recovery behavior matrix

| Scenario | `GET /api/mdi/jobs/latest` | Frontend |
|---|---|---|
| Completed job in memory | Returns live in-memory job | Shows results, restored notice |
| Backend restarted, file present | Reads disk, registers, returns job | Shows results, restored notice |
| Backend restarted, file missing | HTTP 404 | Silent — no notice |
| Backend restarted, file corrupt | HTTP 404 | Silent — no notice |
| Job in-progress during restart | 404 or prior completed job | Shows prior job or nothing |

---

## MDI-09 Settings state and defaults

### `stale_threshold_days` default correction

| Location | Old default | New default (MDI-09) |
|---|---|---|
| `models.py` `MdiJobOptions` | 5 | **7** |
| `models.py` `JobSubmitRequest` | 5 | **7** |
| `models.py` `EstimateRequest` | 5 | **7** |
| `services/job_store.py` `InMemoryJob` | 5 | **7** |

The PRD/backlog specifies 7 days as the stale threshold. All code now matches.

### Frontend settings state (MDI-09)

| State variable | Type | Default | Purpose |
|---|---|---|---|
| `useDomainReports` | `bool` | `false` | Controls `use_domain_reports` in estimate/submit payloads. `true` = domain-report mode (1 call/domain); `false` = URL-report mode (up to 3 calls/domain, better coverage). |
| `staleThresholdDays` | `int` | `7` | Controls `stale_threshold_days` in estimate/submit payloads. Range 1–90 days. |
| `settingsLocked` | `bool` (derived) | `false` | `true` when a job is queued/running or `restoredFromSession` is true. Disables settings controls. Unlocks when user dismisses the job or starts a new run. |

### `settingsPayload` — single source of truth

Both `handleEstimate()` and `handleRunJob()` spread `settingsPayload` into their request bodies:

```javascript
const settingsPayload = {
  default_scheme: 'http',   // hardcoded — not user-configurable in MDI-09
  max_items: 500,           // hardcoded — not user-configurable in MDI-09
  use_domain_reports: useDomainReports,
  stale_threshold_days: staleThresholdDays,
}
```

This guarantees estimate/submit parity — both calls always send the same settings.

### SettingsSection UI groups (MDI-09)

**Group 1 — Functional (wired):**

| Control | Maps to | Default |
|---|---|---|
| VT Report Mode toggle | `useDomainReports` | URL report (false) |
| Stale Threshold input | `staleThresholdDays` | 7 days |

**Group 2 — Disabled placeholders:**

| Row | Status | Note |
|---|---|---|
| Auto-Rescan Stale Results | Disabled/OFF | Not implemented; will consume additional VT quota when live |
| URL Activity Check | Disabled/OFF | Deferred until URL Activity Scanner integration |
| Export Results | Disabled | Deferred until export feature |

**Group 3 — Read-only info:**

- VT hit definition (MALICIOUS ≥ 1 engine / SUSPICIOUS ≥ 1 engine) — no control yet
- Max items: 500
- Default scheme: HTTP

### Saved job settings display (MDI-09)

`JobSection` shows a one-line summary from `JobStatusResponse` fields when job is done/error:

> "This job used: URL report mode · Stale after 7 days (recovered)"

Fields used: `job.use_domain_reports`, `job.stale_threshold_days`, `restoredFromSession`.
These reflect the settings saved to the job at creation time — not current UI state.

### `settingsLocked` behavior

| Condition | `settingsLocked` |
|---|---|
| No active/recovered job | `false` — controls enabled |
| Job is queued or running | `true` — controls disabled |
| `restoredFromSession = true` | `true` — controls disabled |
| User clicks ✕ on "Restored" notice (dismiss) | `false` — job cleared, controls re-enabled |
| User submits new job | `false` — immediately on new submit |

### MDI-09 runtime file impact

MDI-09 adds no new runtime files. `mdi_latest_job.json` written by new jobs after MDI-09 will contain `stale_threshold_days: 7` by default (was 5 in earlier runs). Existing artifacts on disk are unaffected.

---

---

## MDI-10 — Centralized Triage Rules Engine

### Authoritative engine

`backend/services/triage_rules.py` is the **single authoritative source** for all per-item triage decisions. All callers — held-domain path, quota-blocked path, VT error path, VT success path — route through `decide(TriageInput) -> TriageDecision`.

No triage logic exists outside `triage_rules.py`. `vt_service.classify_triage()` is kept as a compatibility shim that delegates to `decide()`.

### Key dimension definitions

| Term | Field | Meaning |
|---|---|---|
| **Recent** | `age_bucket in (VERY_NEW, NEW)` | Domain registered within ~180 days |
| **Stale** | `freshness in (STALE, VERY_STALE)` | VT report is older than `stale_threshold_days` |
| **Live** | `live_status in (ACTIVE, REDIRECT, FORBIDDEN)` | Live check confirms domain is responding |
| **No-Live** | `live_status in (NOT_FOUND, GONE, DNS_FAILURE, ...)` | Live check confirmed domain is down |

These dimensions are **independent**. A domain can be recently registered AND have a stale VT report simultaneously. In that case, Recent wins in priority order, but `triage_reason` must mention the stale evidence.

### `triage_reason` field (MDI-10 change)

- **Type changed:** `Optional[str]` → `List[str]` with `default_factory=list`.
- **Validator:** `MdiResultItem` has a `field_validator` that coerces legacy `null` → `[]` and plain `str` → `[str]` for backward compatibility with persisted jobs.
- **Content:** 2–4 short declarative bullet strings. Always at least one bullet for any processed item. Empty list only for items in PENDING state before processing.

### New enum values (MDI-10 additions)

**`TriageConfidence`:**
- `CLEAN = "clean"` — all checks passed cleanly; used for confirmed-clean FRESH items.

**`RecommendedAction` (new PRD-aligned values):**

| Value | When used |
|---|---|
| `review_for_action` | Flagged + recently-registered domain; review before actioning |
| `verify_investigate` | Ambiguous signals (unknown age/live/freshness); verify then investigate |
| `refresh_report` | VT report is STALE; refresh evidence before actioning |
| `request_new_scan` | VT report is VERY_STALE; request a new VT scan |
| `retry_lookup` | Processing error or quota block; retry when resources allow |
| `no_action_based_on_vt` | VT clean (FRESH), or flagged but domain appears down |

Legacy values (`investigate`, `clear`, `manual_review`, `none`, etc.) are **preserved** for backward compatibility with persisted jobs.

### Triage priority order

| Priority | Condition | `triage_bucket` | `recommended_action` |
|---|---|---|---|
| 1 | `domain_hold.has_hold == True` | HELD | ACTION_ALREADY_TAKEN |
| 2 | `processing_status == ERROR` or errors non-empty | ERROR | RETRY_LOOKUP |
| 3 | Flagged + ACTIVE + Recent | MALICIOUS | INVESTIGATE |
| 4 | Flagged + ACTIVE | MALICIOUS | INVESTIGATE |
| 5 | Flagged + Recent | MALICIOUS | REVIEW_FOR_ACTION |
| 6 | Flagged + STALE | MALICIOUS | REFRESH_REPORT |
| 7 | Flagged + VERY_STALE | MALICIOUS | REQUEST_NEW_SCAN |
| 8 | Flagged + No-Live | MALICIOUS | NO_ACTION_BASED_ON_VT |
| 9 | Flagged (catch-all) | MALICIOUS | VERIFY_INVESTIGATE |
| 10 | Suspicious (same sub-rules 3–9) | SUSPICIOUS | *(mirrors malicious)* |
| 11 | Clean + FRESH | CLEAN | NO_ACTION_BASED_ON_VT |
| 12 | Clean + STALE | CLEAN | REFRESH_REPORT |
| 13 | Clean + VERY_STALE | CLEAN | REQUEST_NEW_SCAN |
| 14 | Clean + UNKNOWN freshness | CLEAN | VERIFY_INVESTIGATE |
| 15 | No engines, or PENDING | PENDING | RETRY_LOOKUP |

### Roadmap readiness

| Field | State now (MDI-10) | Activates fully |
|---|---|---|
| `age_bucket` | UNKNOWN for raw-text; set from CSV/XLSX `created_at` | MDI-11 (WHOIS/RDAP) |
| `live_status` | NOT_CHECKED always | MDI-12 (URL Activity Scanner) |
| `freshness` | Set correctly from VT scan date | Already active ✓ |
| `domain_hold` | Set from upload offline detection | MDI-11 supplements with RDAP |

### MDI-10 runtime file impact

MDI-10 adds no new runtime files. No quota logic was changed. Only in-memory triage outputs differ.

---

## Fields explicitly NOT included

| Data | Reason omitted |
|---|---|
| Registrant name / email / phone | Personal data; not needed for triage |
| Raw WHOIS text | Too large; noisy; extract structured fields instead |
| Full VT engine list (default) | `vt_engine_results` is present but excluded from exports by default |
| IP address of URL target | Not collected; SSRF safety layer blocks IP-targeted requests |
| User agent sent during live check | Not logged; privacy |

---

## MDI-11 — WHOIS/RDAP Domain Enrichment

### Overview

MDI-11 adds a live RDAP/WHOIS enrichment pass that runs **before** VT processing
for every accepted item. Enrichment populates fields that were previously only
available from uploaded CSV/XLSX files. When live RDAP/WHOIS confirms a domain
hold, VT is skipped entirely — preventing wasted quota on already-actioned domains.

### New service: `backend/services/domain_enrichment.py`

| Symbol | Role |
|---|---|
| `EnrichmentResult` | Dataclass with all enriched fields + `error` + `source` + `whois_fallback_used` |
| `_rdap_request(url, client)` | Single mockable RDAP HTTP entry point |
| `_whois_query_sync(domain)` | Single mockable blocking WHOIS entry point (run in executor) |
| `extract_registered_domain(normalized, input_type)` | Extracts eTLD+1 from domain or URL input; returns None for IPs |
| `enrich_domain(registered_domain)` | RDAP primary → WHOIS fallback; returns EnrichmentResult |
| `_parse_rdap_response(data, domain)` | Extracts fields from RDAP JSON; feeds epp_status to hold_detection |
| `_parse_whois_result(result_dict, domain)` | Extracts fields from normalized whois dict |

### Shared utility: `backend/services/age_bucket.py`

Moved from `upload_parser.py` to a shared module so both the upload path
(offline, from CSV/XLSX) and the enrichment path (live, from RDAP/WHOIS) use
identical age bucket rules.

| Function | Description |
|---|---|
| `compute_age_bucket(d: date) → AgeBucket` | Maps registration date to VERY_NEW/NEW/ESTABLISHED/MATURE/UNKNOWN |
| `parse_date_string(s: str) → Optional[date]` | Tries multiple date formats; returns None on failure |

**Age bucket thresholds:**
- `0–29 days` → `VERY_NEW`
- `30–179 days` → `NEW`
- `180–729 days` → `ESTABLISHED`
- `≥ 730 days` → `MATURE`
- future date or unparseable → `UNKNOWN`

### RDAP/WHOIS lookup strategy

1. **RDAP primary** — `GET https://rdap.org/domain/{registered_domain}`, timeout 10 s
   - 200: parse → return
   - 404: WHOIS fallback
   - 429: retry once after 5 s → WHOIS fallback
   - 5xx / timeout / network error: WHOIS fallback
2. **WHOIS fallback** — blocking call in thread executor via `whois.query()`
   - Failure: return `EnrichmentResult(error=MdiError(...))` with `source=UNKNOWN`
3. Both fail: non-fatal error; item proceeds to VT with UNKNOWN fields

### Field mapping

| RDAP source | MDI field |
|---|---|
| `events[action=registration].eventDate` | `created_at` |
| `entities[role=registrar].vcardArray.fn` | `registrar` |
| `status[]` (stripped of ICANN URLs) | `epp_status` |
| `nameservers[].ldhName` | `nameservers` |
| epp_status → `hold_detection.detect_hold()` | `domain_hold` |
| derived from `created_at.date()` | `age_bucket` |

| WHOIS source | MDI field |
|---|---|
| `w.creation_date` | `created_at` |
| `w.registrar` | `registrar` |
| `w.status` (list) | `epp_status` |
| `w.name_servers` | `nameservers` |

### Uploaded-vs-live data reconciliation

| Condition | Behavior |
|---|---|
| `domain_hold.source == UPLOADED_FILE` and `has_hold == True` | Skip RDAP/WHOIS entirely; preserve upload values |
| `domain_hold.source == UPLOADED_FILE` and `has_hold == False` | RDAP/WHOIS fills missing fields; uploaded hold decision preserved |
| `result.created_at` already set (from upload) | Not overwritten by RDAP |
| `result.registrar` already set (from upload) | Not overwritten |
| `result.age_bucket != UNKNOWN` (from upload) | Not overwritten |
| `result.created_at is None` (raw-text input) | Populated from RDAP/WHOIS |
| Enrichment both-fail error | Only error appended; data fields unchanged (item stays UNKNOWN) |

### Hold detection and VT-skip rules (MDI-11 extension)

Previous hold detection was upload-only (offline).
MDI-11 adds live hold detection via RDAP/WHOIS:

```
Pre-enrichment pass (before _run_items):
  if result.processing_status == HOLD_SKIPPED: skip enrichment (upload-confirmed)
  if domain_hold.source == UPLOADED_FILE and has_hold: skip enrichment
  else:
    extract registered domain from normalized input
    check per-job domain cache (enrich once per unique registered domain)
    call enrich_domain(registered_domain)
    merge enrichment fields into result
    if enrichment.domain_hold.has_hold:
      processing_status = HOLD_SKIPPED
      call triage_rules.decide(domain_hold_has_hold=True)
      increment held_skipped + hold_detected_by_enrichment_count
      → VT is skipped for this item
```

### Age bucket activation for raw/pasted input

Before MDI-11: `age_bucket = UNKNOWN` for all paste/text input.
After MDI-11: `age_bucket` is populated from RDAP `created_at` for all
paste/text inputs that successfully resolve via RDAP or WHOIS.

This activates the "Flagged + Recent" triage rule in `triage_rules.py`:
a freshly registered domain flagged by VT now routes to `REVIEW_FOR_ACTION`
instead of the catch-all `VERIFY_INVESTIGATE`.

### Estimate / runtime update (MDI-11)

`EstimateResponse` now includes:
- `estimated_enrichment_lookups: int` — 1 per accepted item (conservative; live jobs de-duplicate)
- `enrichment_note: str` — informational note about RDAP overhead
- `estimated_duration_seconds_min/max` — now includes `N × 0.5 s` enrichment overhead

### Usage history metadata rule (strict)

Enrichment adds **counts only** to `vt_usage_history.jsonl`. No raw domain names,
registrar names, nameservers, or EPP status values are ever written.

New count fields in history records:
- `rdap_enriched_count` — items successfully enriched via RDAP or WHOIS
- `rdap_failed_count` — items where both RDAP and WHOIS failed
- `whois_fallback_count` — items where RDAP failed but WHOIS succeeded
- `hold_detected_by_enrichment_count` — items where live RDAP/WHOIS found a hold
- `enrichment_skipped_uploaded_hold_count` — items skipped because upload already confirmed hold

### `mdi_latest_job.json` impact

Jobs now include enriched fields (`created_at`, `age_bucket`, `registrar`,
`epp_status`, `nameservers`, `domain_hold`) from RDAP/WHOIS. Recovery via
`GET /api/mdi/jobs/latest` preserves and restores all enriched fields correctly.
These are publicly available RDAP fields — no PII.

### New dependencies

- `tldextract==5.3.1` — registered domain extraction from URLs
- `whois==1.20240129.2` — WHOIS fallback lookups
