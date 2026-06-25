# MDI Field-Purpose Map

Each field in `MdiResultItem` and related models is classified by its
primary purpose.  A field may serve more than one purpose; the primary
purpose determines where it must be present (display, export, etc.).

**Operator context:** For how fields appear in the UI, exports, and dashboard,
see [Operator Guide](operator-guide.md) (§7–§9 results table, errors, and detail
drawer, §13 exports, §14 dashboard). For recovery actions and test scenarios, see
[Error Recovery Matrix](error-recovery-matrix.md). This document is a technical
field reference, not a runbook.

Purpose categories:
- **display**       — rendered in the results table or detail drawer
- **workflow**      — used to drive hold-skip, rescan, or routing decisions
- **filtering**     — used for client-side or server-side filter/sort
- **reporting**     — required in CSV export and JSONL usage history
- **audit**         — retained for debugging; not shown in the main UI by default
- **dashboard**     — metadata-only; shown in job history without item-level data
- **future**        — defined for schema stability; not yet populated

UI control / feature status (MDI-32):
- **active** — operator-facing and functional today
- **read-only** — shown for transparency; not editable
- **disabled future** — visible disabled control; backend/data not ready
- **deferred** — backlog; may not appear in UI yet
- **rejected / out of scope** — explicitly not in MVP
- **internal-only** — backend/tests; not operator UI

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
| `nameservers` | `List[str]` | display, reporting | Nameservers from RDAP/WHOIS enrichment. Distinct from upload `assigned_nameservers`. Not used in triage logic yet. |

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
| `vt_engine_results` | `Optional[List[Dict]]` | display, reporting | Non-clean VT engine detections. **Excluded from CSV**; **included in JSON evidence** (`mdi-evidence-v1`). |
| `vt_report_url` | `Optional[str]` | display, action link | Computed public VT GUI URL (MDI-34). Domain report → `/gui/domain/{domain}`; URL report → `/gui/url/{base64url}`. Browser only — no VT API, no quota. UI disabled when absent. |

### URL live activity

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `live_status` | `LiveStatus` | display, filtering, reporting | HEAD-request result: `active`, `redirect`, `not_found`, `timeout`, `dns_failure`, `blocked`, etc. |
| `live_checked_at` | `Optional[datetime]` | display, audit | UTC timestamp when the live check ran. |

### Cloudflare Radar rank (MDI-50B)

Popularity / blast-radius context from Cloudflare Radar 1.1.1.1 DNS data. **Not maliciousness evidence.** Does not change VT flagged logic, `triage_bucket`, or `recommended_action`. Does not consume VT quota. Default off (`cloudflare_rank_lookup_enabled=false`).

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `cloudflare_rank_available` | `bool` | display | `true` when rank or bucket data obtained. |
| `cloudflare_rank` | `Optional[int]` | display | Exact rank when in global top 100. |
| `cloudflare_rank_bucket` | `Optional[str]` | display, filtering | `TOP_100` … `TOP_1M`, `UNRANKED`, `UNKNOWN`. |
| `cloudflare_rank_raw_bucket` | `Optional[str]` | audit | Raw API bucket string (e.g. `200`, `>200000`). |
| `cloudflare_rank_source` | `Optional[str]` | audit | `cloudflare_radar_popular`. |
| `cloudflare_rank_checked_at` | `Optional[datetime]` | display, audit | UTC lookup timestamp. |
| `cloudflare_rank_error` | `Optional[str]` | display, audit | Sanitized error code (`auth_failed`, `rate_limited`, …). |

Job option: `cloudflare_rank_lookup_enabled` (default `false`). Token: `CLOUDFLARE_RADAR_API_TOKEN` in `/etc/dns-tool/secrets.env` (server-side only).

### Hold-impact guidance (MDI-50C)

Analyst guidance derived from `cloudflare_rank_bucket` only. **Not maliciousness evidence.** Does not change VT flagged logic, `triage_bucket`, `recommended_action`, or enforcement. Does not trigger automated holds, registrar actions, or Salesforce workflows. No additional Cloudflare API calls.

| `cloudflare_rank_bucket` | `hold_impact_level` |
|---|---|
| `TOP_100`, `TOP_1K` | `critical` |
| `TOP_5K`, `TOP_10K` | `high` |
| `TOP_100K` | `medium` |
| `TOP_1M` | `low` |
| `UNRANKED` | `none` |
| `UNKNOWN` | `unknown` |
| `null` / unavailable / lookup disabled | `unknown` |

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `hold_impact_level` | `Optional[str]` | display | `critical`, `high`, `medium`, `low`, `none`, `unknown`. |
| `hold_impact_reason` | `Optional[str]` | display | Operator-facing guidance text for the level. |

### Triage

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `triage_bucket` | `TriageBucket` | display, filtering, reporting | `malicious`, `suspicious`, `held`, `clean`, `unresolvable`, `error`, `pending`. Top-level classification. |
| `triage_reason` | `Optional[str]` | display | Short plain-language explanation, e.g. `"VT: 5 engines flagged malicious"`. |
| `triage_confidence` | `TriageConfidence` | display, filtering | `high`, `medium`, `low`, `unknown`. |
| `recommended_action` | `RecommendedAction` | display, workflow | `investigate`, `takedown`, `monitor`, `clear`, `skip`, `manual_review`, `none`. Operator guidance only. |
| `evidence_status` | `EvidenceStatus` | display, audit | `complete`, `partial`, `none`. Whether all expected checks ran. |

### Errors (`MdiError` — MDI-22 / MDI-22B)

Structured per-item errors. Recovery actions and test scenarios:
[Error Recovery Matrix](error-recovery-matrix.md).

| Field | Type | Primary Purpose | Notes |
|---|---|---|---|
| `errors` | `List[MdiError]` | display, audit | List of structured errors for the row. |
| `errors[].code` | `str` | display, audit | Machine-readable code (`timeout`, `whois_failed`, `quota_blocked`, …). Legacy `vt_*` aliases remain valid on stored objects; dashboard may normalize for counts. |
| `errors[].message` | `str` | display | Human-readable text in drawer, table tooltips, and export messages. |
| `errors[].source` | `str` | audit | Producer: `input_parser`, `vt_service`, `domain_enrichment`, `live_check`, `auto_rescan`, `export_service`, `job_persistence`, etc. |
| `errors[].retriable` | `bool` | workflow | Hint that retry/refresh/scan may succeed; operator still follows `recommended_action`. |
| `errors[].category` | `str` | audit, workflow | Subsystem: `input_validation`, `upload_parse`, `vt_lookup`, `quota`, `quota_lock`, `rdap_whois`, `live_check`, `refresh`, `scan`, `auto_rescan`, `export`, `recovery`, `persistence`, `unknown`. |
| `errors[].severity` | `str` | display, workflow | `error` \| `warning` \| `skip` \| `info` — drives UI styling and operator urgency. |
| `errors[].blocks_triage` | `bool` | workflow | When `true`, can force `triage_bucket=error` if VT did not provide usable evidence. When `false`, error is recorded but does not override successful VT triage. |

### Error severity (MDI-22)

| Severity | Meaning | Triage impact |
|---|---|---|
| `error` | Blocking failure; primary evidence incomplete | **Can** force `triage_bucket=error` when `blocks_triage=true` (or inferred) and VT did not succeed |
| `warning` | Non-fatal partial evidence (e.g. RDAP/WHOIS or live-check failed) | Does **not** force ERROR; does **not** override successful VT triage |
| `skip` | Intentional skip (hold, quota exhaustion, unsupported scan) | **Not a failure**; may still recommend `retry_lookup` when no VT ran |
| `info` | Operational notice (e.g. auto-rescan ineligible) | Informational only; no triage impact |

**Important:** Warnings and skips must not be displayed or triaged as failures.
`blocks_triage` (or `severity=error` when `blocks_triage` is unset) controls
whether an error can force the ERROR bucket — not merely the presence of any
`errors[]` entry. A row with VT success plus `whois_failed` (warning) keeps its
VT-derived triage bucket. When preserved metadata exists (e.g. from upload),
the UI may show clearer copy that live RDAP/WHOIS lookup failed while existing
metadata remains visible — backend `errors[].code` and message are unchanged.

### Frontend display severity (MDI-22B)

| Severity | UI meaning |
|---|---|
| `error` | Blocking failure — red styling, critical indicator |
| `warning` | Partial evidence — amber styling, softer indicator |
| `skip` | Intentional/non-failure — muted styling |
| `info` | Operational note — muted informational styling |

The frontend prefers API-provided `severity` when present; legacy string errors and objects without severity use a client-side fallback map aligned with the backend taxonomy.

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
| `assigned_nameservers` | `List[str]` | display, reporting | Nameserver values from the upload row. Lowercase, FQDN-dot-stripped. Distinct from RDAP/WHOIS `nameservers` on enriched results. |
| `source_row` | `int \| null` | audit | 1-based row number in the source file. |
| `source_sheet` | `str \| null` | audit | Worksheet name for XLSX uploads. |

### Upload job workflow (MDI-30A)

- `POST /api/mdi/jobs/upload-preview` — quota-free parse; returns `columns_detected`, `missing_optional_columns`, `header_row`, `source_sheet`.
- `POST /api/mdi/jobs/estimate` with `items` + `input_mode=upload` — excludes held upload domains from VT estimate.
- `POST /api/mdi/jobs/submit` with `items` + `input_mode=upload` — preserves upload metadata into `MdiResultItem`; held domains skip VT/live checks.

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
| `nameservers` | `str \| null` | display | Which raw column header was matched as the nameservers column (typically **Assigned Nameservers**). Values land in `assigned_nameservers` on each item. |

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
- `InputType.DOMAIN` → stored as `"example.com"` (bare **dotted** domain, no scheme; single-label hostnames rejected)
- `InputType.URL` → stored as full URL e.g. `"https://example.net/path"`

Bare-domain tokens must contain at least one dot with valid labels and a
TLD-like final label. Domain/path tokens require a valid dotted host before the
first `/`. `localhost` and internal single-label names are not accepted. IP
literals (IPv4/IPv6), CIDR notation, IP ranges, and IP-hostname URLs are
rejected with `ip_address_not_supported` (`input_validation`, source
`input_parser`); numeric domain labels (`123.example.com`) remain valid.

### Manual scan/rescan routing (MDI-28)

| Row type | `use_domain_reports` | Request New Scan path | Typical quota |
|---|---|---|---|
| `url` | any | URL scan (`POST /urls` + poll) | 2–4 |
| `domain` | `false` | URL scan on `http://{domain}/` | 2–4 |
| `domain` | `true` | Domain rescan (`POST /domains/{domain}/analyse` + analysis poll + domain GET) | 2–5 |

Refresh Report always uses GET-only (1 unit). Auto-rescan domain rescan is deferred.

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
| VT blocking error (429, 5xx, timeout) | `error` | `retry_lookup` | `partial` |
| VT success + RDAP/WHOIS warning | follows VT | follows VT | `complete` or `partial` |
| VT success + live-check warning | follows VT | follows VT | `complete` or `partial` |
| Confirmed hold (held item) | `held` | `action_already_taken` | `skipped_hold` |
| Quota exhausted mid-run (skip) | `error` | `retry_lookup` | `partial` |
| Quota lock timeout | `error` | `retry_lookup` | `partial` |

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
| `JobSubmitRequest` | `raw_input` **or** `items` (upload mode), `input_mode`, `default_scheme`, `max_items`, `use_domain_reports`, `stale_threshold_days`, `auto_rescan_stale`, `max_auto_rescans` | POST /api/mdi/jobs/submit request body |
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
| `eligible_vt_count` | `int` | display | Items eligible for VT checks. Paste: equals accepted count when hold is NOT_CHECKED. Upload: excludes confirmed-held items. |
| `held_skipped_count` | `int` | display | Items confirmed-held that contribute 0 VT calls. Always `0` for paste input. Populated for upload mode (MDI-30A). |

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
| `restoredFromSession` | `bool` | Set to `true` when `/api/mdi/jobs/latest` returns a job on mount. Controls "↩ Restored previous job input" notice in the input panel. |

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
| `useDomainReports` | `bool` | `false` | Controls `use_domain_reports` in estimate/submit payloads. |
| `staleThresholdDays` | `int` | `7` | Controls `stale_threshold_days` in estimate/submit payloads. Range 1–90 days. |
| `autoRescanStale` | `bool` | `false` | Controls `auto_rescan_stale` in estimate/submit payloads. **OFF by default.** |
| `maxAutoRescans` | `int` | `3` | Controls `max_auto_rescans` in estimate/submit payloads. |
| `settingsLocked` | `bool` (derived) | `false` | `true` when a job is queued/running or `restoredFromSession` is true. Disables Run Options and Advanced Settings. Unlocks on dismiss/clear or new submit. |

### `settingsPayload` — single source of truth

Both `handleEstimate()` and `handleRunJob()` spread `settingsPayload` into their request bodies:

```javascript
const settingsPayload = {
  default_scheme: 'http',   // hardcoded — not user-configurable in MDI-09
  max_items: 500,           // hardcoded — not user-configurable in MDI-09
  use_domain_reports: useDomainReports,
  stale_threshold_days: staleThresholdDays,
  auto_rescan_stale: autoRescanStale,
  max_auto_rescans: maxAutoRescans,
}
```

This guarantees estimate/submit parity — both calls always send the same settings.

### SettingsSection UI groups (MDI-09, updated MDI-30B)

Settings are split between **Run Options** (sidebar) and **Advanced Settings** (nav gear menu).
Both feed `settingsPayload` for estimate/submit. Values are saved with the job at submit time.

**Run Options (sidebar — active):**

| Control | Maps to | Default | Quota |
|---|---|---|---|
| Domain reports for bare domains | `use_domain_reports` | URL report (false) | Affects VT calls on run |
| Live checks: flagged items only | *(read-only)* | Always on | Live checks on run (flagged only) |

**Advanced Settings (gear menu — active):**

| Control | Maps to | Default | Quota |
|---|---|---|---|
| Stale threshold | `stale_threshold_days` | 7 days | None (classification only) |
| Auto-rescan stale flagged | `auto_rescan_stale` | **OFF** | Additional VT on initial job only |
| Max auto-rescans per job | `max_auto_rescans` | 3 | Caps auto-rescan VT use |

**Advanced Settings (informational — read-only, MDI-30B):**

| Topic | Status | Note |
|---|---|---|
| Exports | Active (elsewhere) | Bulk actions, row More Actions menu, detail drawer — implemented (MDI-16); no Settings config |
| Live-check scope | Deferred | Fixed to flagged items today; future backlog |

**Removed misleading placeholders (MDI-30B):** “Export options (MDI-16) coming soon” and vague
“URL activity check settings” stubs replaced with accurate informational copy.

**Not shown in Settings:** Watchlist, Create Block Rule, Salesforce, enforcement actions.

**Read-only reference (unchanged):**

- VT hit definition (MALICIOUS ≥ 1 / SUSPICIOUS ≥ 1 engine)
- Max items: 500 (hardcoded in payload)
- Default scheme: HTTP (hardcoded in payload)

### Saved job settings display (MDI-09, UI as of MDI-30B)

When a job is active or recovered, the triage workspace shows a read-only
**"Job ran with:"** summary (domain reports, auto-rescan, max auto-rescans,
stale threshold) from `JobStatusResponse` fields. **Job ID** and **current-run
progress** appear in **VT Usage & Status** (sidebar). These reflect settings
**saved at submit time** — not current editable Run Options / Advanced Settings.

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
| `investigate_hold` | Flagged + active/recent; investigate and review hold options (analyst guidance only) |
| `review_for_action` | Legacy; flagged + recently-registered domain |
| `verify_investigate` | Ambiguous signals (unknown age/live/freshness); verify then investigate |
| `refresh_report` | Legacy; VT report is STALE |
| `request_new_scan` | VT report is STALE or VERY_STALE; request a new VT scan |
| `retry_lookup` | Processing error or quota block; retry when resources allow |
| `no_action_based_on_vt` | VT clean (FRESH), or flagged but domain appears down |

Legacy values (`investigate`, `clear`, `manual_review`, `none`, etc.) are **preserved** for backward compatibility with persisted jobs.

### Triage priority order

| Priority | Condition | `triage_bucket` | `recommended_action` |
|---|---|---|---|
| 1 | `domain_hold.has_hold == True` | HELD | ACTION_ALREADY_TAKEN |
| 2 | `processing_status == ERROR` or errors non-empty | ERROR | RETRY_LOOKUP |
| 3 | Flagged + ACTIVE + Recent | MALICIOUS | INVESTIGATE_HOLD |
| 4 | Flagged + ACTIVE | MALICIOUS | INVESTIGATE_HOLD |
| 5 | Flagged + Recent | MALICIOUS | INVESTIGATE_HOLD |
| 6 | Flagged + STALE | MALICIOUS | REQUEST_NEW_SCAN |
| 7 | Flagged + VERY_STALE | MALICIOUS | REQUEST_NEW_SCAN |
| 8 | Flagged + No-Live | MALICIOUS | VERIFY_INVESTIGATE |
| 9 | Flagged (catch-all) | MALICIOUS | VERIFY_INVESTIGATE |
| 10 | Suspicious (same sub-rules 3–9) | SUSPICIOUS | *(mirrors malicious)* |
| 11 | Clean + FRESH | CLEAN | NO_ACTION_BASED_ON_VT |
| 12 | Clean + STALE | CLEAN | REQUEST_NEW_SCAN |
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
a freshly registered domain flagged by VT now routes to `INVESTIGATE_HOLD`
instead of the catch-all `VERIFY_INVESTIGATE`.

### Estimate / runtime update (MDI-11 / MDI-11A)

`EstimateResponse` now includes:

| Field | Description |
|---|---|
| `estimated_enrichment_lookups` | 1 per accepted item (conservative; live jobs de-duplicate) |
| `estimated_enrichment_duration_seconds_min` | 0 s (best case: all items share 1 registered domain) |
| `estimated_enrichment_duration_seconds_max` | N × 1.1 s (worst case: all unique domains) |
| `enrichment_note` | Informational text about RDAP/WHOIS overhead |
| `enrichment_warning` | Non-empty for N > 100; warns about extended runtime (e.g. 9+ min for 500 domains) |

**MDI-11A correction:** Timing was updated from 0.5 s/item (MDI-11 gate) to 1.1 s/item
to match rdap.org's actual throttle budget (~10 req/10 s). `estimated_duration_seconds_min`
now equals VT-min only (enrichment best-case = 0); `estimated_duration_seconds_max`
includes the full N × 1.1 s enrichment overhead.

**RDAP rate limiter (`_rdap_acquire_slot`):** A single mockable function enforces the
1.1-second minimum gap before each RDAP request (both initial and retry). On HTTP 429,
the `Retry-After` header is honoured if present and numeric (capped at 60 s); otherwise
a 5-second default wait is applied before a single retry. If the retry still fails or
returns 429, enrichment falls through to WHOIS or returns a structured error.

> **Future improvement:** IANA bootstrap routing (`https://data.iana.org/rdap/`)
> would direct queries to TLD-specific RDAP servers rather than rdap.org, avoiding
> the shared rate limit for large batches. Deferred pending evidence that large-batch
> enrichment is a recurring need.

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

---

## MDI-12 — SSRF-safe Live Status Checks

### Overview

MDI-12 adds `backend/services/live_check.py`, a self-contained SSRF-safe
HTTP probe service.  It ports the URL Activity Scanner's safety chain to Python,
running live HTTP checks **after VT processing** for flagged or suspicious items.

### `live_check.py` — core service

Implements a four-gate pipeline before any network call reaches the internet:

1. **URL validation (pure)** — scheme, hostname blocklist, IP-literal CIDR check.
2. **DNS resolution + re-check** — resolves A/AAAA via `socket.getaddrinfo`
   through `asyncio.run_in_executor`; all resolved IPs are checked against the
   SSRF blocklist before continuing.
3. **HEAD request chain** — manual redirect following (max 3 hops); every
   redirect `Location` header is re-validated through all four gates before
   following.
4. **GET fallback** — only on 405/501; body immediately closed without reading.

All external-facing functions (`_resolve_dns`, `_head_request`,
`_get_fallback_request`) are module-level async functions — mockable in tests
via `patch.object` without any live network calls.

### SSRF protection summary

| Protection | Method |
|---|---|
| Scheme restriction | Only `http` and `https` allowed |
| Hostname exact blocklist | `localhost`, `localhost.localdomain`, `metadata.google.internal` |
| Hostname suffix blocklist | `.localhost`, `.localdomain`, `.local`, `.internal` |
| IPv4 CIDR blocklist | Loopback, RFC 1918 private, link-local, CGNAT, multicast, reserved test nets, broadcast |
| IPv6 CIDR blocklist | Loopback, ULA, link-local, multicast, documentation, IPv4-mapped equivalents |
| DNS rebinding mitigation | All resolved IPs checked against SSRF blocklist before HTTP call |
| Redirect revalidation | Every Location header treated as untrusted; re-runs all four gates |
| TLS verification | Always enabled (`verify=True`); TLS errors → `UNKNOWN` |
| Body policy | HEAD: no body by spec; GET fallback: `aclose()` immediately |

### `live_status` activation

`live_status` was defined in `models.py` (MDI-10) and consumed by
`triage_rules.py` (MDI-10), but always remained `NOT_CHECKED`.  MDI-12
populates it for eligible items.

**Eligibility rules (all must be true):**
- `processing_status` is not `HOLD_SKIPPED`
- `processing_status` is not `ERROR` (includes quota-blocked items)
- `vt_total_engines > 0` (VT actually ran)
- `vt_hits > 0` OR `vt_suspicious > 0`

Clean items (zero hits, zero suspicious) are always skipped.
Held domains are always skipped.

### `live_status` → `LiveStatus` mapping

| HTTP outcome | `LiveStatus` |
|---|---|
| 2xx (direct) | `ACTIVE` |
| 3xx (any redirect followed) | `REDIRECT` |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND` |
| 410 | `GONE` |
| 5xx | `SERVER_ERROR` |
| Other 4xx | `UNKNOWN` |
| Timeout | `TIMEOUT` |
| Connection refused | `CONNECTION_REFUSED` |
| DNS failure | `DNS_FAILURE` |
| SSRF block | `BLOCKED` |
| Too many redirects (> 3) | `UNKNOWN` |
| TLS error | `UNKNOWN` |
| Not eligible | `NOT_CHECKED` |

### Triage interaction

After `live_status` is populated, `triage_rules.decide()` is re-run for the
item.  The `_is_live()` and `_is_no_live()` branches (defined in MDI-10 but
previously unreachable) now activate:

| Triage set | `LiveStatus` values |
|---|---|
| Live (active) | `ACTIVE`, `REDIRECT`, `FORBIDDEN` |
| No-live (down) | `NOT_FOUND`, `GONE`, `DNS_FAILURE`, `CONNECTION_REFUSED`, `TIMEOUT` |
| Neutral/unknown | `UNKNOWN`, `BLOCKED`, `SERVER_ERROR`, `NOT_CHECKED` |

### Job-state counters (MDI-12)

Added to `InMemoryJob` and usage-history records:

| Counter | Meaning |
|---|---|
| `live_check_count` | Items that received a live check attempt |
| `live_check_skipped_count` | Items skipped by eligibility rules |
| `live_check_error_count` | Items where live_check returned a structured error |

### Usage-history privacy

Metadata-only records (no raw per-item data):
- `live_check_count` — aggregate count
- `live_check_skipped_count` — aggregate count
- `live_check_error_count` — aggregate count

**Must not appear in history records:**
- Submitted URLs or domains
- Resolved IP addresses
- Redirect chains
- Final resolved URLs
- `live_status` per item
- HTTP status codes per item

### Estimate behavior

`estimated_live_check_count = 0` always — the number of flagged items is not
known until VT processing completes.  A `live_check_note` string is included in
the estimate response explaining the conditional timing overhead.

`live_check` duration is **not** added to `estimated_duration_seconds_min` or
`estimated_duration_seconds_max` because the count is unknown at estimate time.

---

## MDI-12A — Quota refresh and live-check counter exposure

### Frontend quota state

The `App` component maintains a `quotaState` object:

| Field | Type | Description |
|---|---|---|
| `daily_lookups_used` | int | Calls consumed today across all MDI + VT Bulk Check tools |
| `remaining` | int | Calls remaining today before the 500/day cap is hit |
| `daily_limit` | int | Total daily cap (typically 500) |
| `checkedAt` | timestamp (ms) | Local epoch-ms when the quota was last fetched |

`quotaLoading` / `quotaError` track fetch state.

### QuotaWidget display

A compact row above the main page header shows:

- **VT quota: X / 500** — current usage out of daily cap  
- **(Y remaining)** — coloured green/amber/red by threshold  
- A thin progress bar  
- **Last checked: HH:MM:SS** — local time of the last fetch

If the quota fetch fails, a non-blocking warning replaces the display. Input
and parse-preview are never blocked by quota fetch failures.

### Quota refresh triggers

| Trigger | Action |
|---|---|
| App mount (component load) | `GET /api/mdi/usage` called immediately |
| `handleEstimate` | Refresh if `quotaState.checkedAt` is missing or > 60 s old (stale threshold) |
| `handleRunJob` (before submit) | Always refresh; block submit if `remaining <= 0` |
| Poll detects `done` or `error` | Refresh to reflect quota consumed by the completed job |

The 60-second staleness constant (`QUOTA_STALE_MS`) is defined at module level
in `App.jsx` and applies only to the pre-estimate refresh. Submit always
performs a fresh fetch.

### Submit quota guard

If `GET /api/mdi/usage` returns `remaining <= 0` immediately before a job
submission, the submit is blocked client-side with a clear error message. The
backend also enforces this as a hard stop, so this is defense-in-depth.

### live-check counters in `JobStatusResponse`

Three counter fields were added to `backend/models.py → JobStatusResponse` and
populated by both `GET /api/mdi/jobs/{job_id}` and `GET /api/mdi/jobs/latest`:

| Field | Default | Description |
|---|---|---|
| `live_check_count` | 0 | Items that received a live HTTP check |
| `live_check_skipped_count` | 0 | Items skipped by eligibility rules |
| `live_check_error_count` | 0 | Items where the live check returned an error |

These counters were already tracked in `InMemoryJob` (MDI-12); MDI-12A exposes
them in the API response.

### Job persistence (round-trip)

`backend/services/job_persistence.py` `serialize_job` / `deserialize_job` now
include the MDI-11 enrichment counters and MDI-12 live-check counters.  Jobs
persisted before MDI-12A will deserialize the missing keys as `0` (backward
compatible).

### Frontend live-check counter display

After job processing completes (or during `running` state), the `JobSection`
renders a compact summary row if any enrichment or live-check counters are
non-zero:

- RDAP enriched: N  
- Live checks run: N  
- Live checks skipped: N  
- Live-check errors: N (only shown if > 0)

This is rendered via an IIFE in JSX and is suppressed entirely when all counters
are zero.

---

## MDI-13 — Triage UI (summary cards, priority table, filters, settings gear)

### Overview

MDI-13 is a frontend-only enhancement. No backend APIs, endpoints, or runtime
files were changed. All sorting, filtering, and card-counting logic runs
client-side on the already-received `job.results` array.

### Settings placement

The standalone bottom `SettingsSection` card and the `DashboardSection`
placeholder are removed. Configuration is split between **Run Options** (sidebar)
and **Advanced Settings** (nav gear menu, labeled **Advanced** in the UI).

- `settingsOpen: boolean` state in `App` controls the Advanced Settings panel.
- The gear button sets `aria-expanded` and `aria-controls` (pointing to the
  panel element ID) for accessibility.
- The `CollapsibleSettingsPanel` renders inline below the nav (via CSS
  `settings-panel` class), collapsed by default (zero vertical space).
- Panel title: **Advanced Settings** — stale threshold, auto-rescan controls, and
  read-only export/live-check reference notes (MDI-30B).
- Sidebar panel title: **Run Options** — domain report mode and read-only live-check rule.
- `settingsLocked` behavior is preserved: controls are greyed out while a job
  is active or a recovered job is shown.

### Header / nav widgets

The nav bar includes:
1. Left: back link + breadcrumb
2. Center-right: `QuotaNavWidget` — compact inline quota display (used/limit + bar)
3. Right: **Dashboard** button (`DashboardPanel`) and **Advanced** gear button (`CollapsibleSettingsPanel`)

`QuotaNavWidget` renders the shared VT quota as `used/limit` with a thin bar.
All four refresh triggers from MDI-12A are preserved (mount, pre-estimate,
pre-submit, post-completion).

### Pure helper functions

All triage logic is implemented as pure functions at the top of `App.jsx`. They
accept only result/job data and make no network calls.

| Function | Purpose |
|---|---|
| `isFlagged(r)` | `triage_bucket` in malicious/suspicious |
| `isLive(r)` | `live_status` in active/redirect/forbidden |
| `isNoLive(r)` | `live_status` in not_found/gone/dns_failure/connection_refused/timeout |
| `isRecentAge(r)` | `age_bucket` in very_new/new |
| `isStaleFreshness(r)` | `freshness` in stale/very_stale |
| `getVirtualBucketKey(r)` | Returns mutually-exclusive virtual bucket key |
| `getItemPriority(r)` | Numeric priority rank (1 = highest) |
| `comparePriority(a, b)` | Comparator for `Array.sort` — mirrors triage_rules.py |
| `getFilteredResults(results, key)` | Returns items matching the named filter |
| `getFilterCount(results, key)` | Count of items matching a filter |
| `getTriageCardCounts(results)` | Returns `{ flr, fl, fr, fs, fnl, flagged, unknown, clean, held }` counts |
| `formatPercent(count, total)` | `"X.X%"` string |
| `formatDate(val)` | `"YYYY-MM-DD"` or `"—"` |
| `formatAgeBucket(val)` | Human label for age_bucket enum |
| `formatVtRatio(r)` | VT ratio string from vt_ratio or vt_hits/vt_total_engines |
| `formatLiveStatus(val)` | Display string for live_status enum value |

### Virtual bucket keys (mutually exclusive, priority order)

| Key | Condition | Priority |
|---|---|---|
| `held` | `triage_bucket === 'held'` | 1 |
| `unknown` | bucket in error/unresolvable/pending | 2 |
| `flr` | flagged AND live AND recent | 3 |
| `fl` | flagged AND live | 4 |
| `fr` | flagged AND recent | 5 |
| `fs` | flagged AND stale freshness | 6 |
| `fnl` | flagged AND no-live | 7 |
| `flagged` | flagged catch-all | 8 |
| `clean` | `triage_bucket === 'clean'` | 9 |

Cards use these mutually-exclusive keys so totals add up to total items without
double-counting. Filter predicates are **inclusive** (a row may match multiple
filters), consistent with how operators would expect `Flagged + Live` to include
items that are also `Flagged + Live + Recent`.

### Priority sort

`comparePriority(a, b)` mirrors the 11-level priority in
`backend/services/triage_rules.py`. Secondary sort: confidence (high→medium→low
→clean→unknown). Tertiary: submission position.

> **Important:** If `triage_rules.py` priority changes, `PRIORITY_RANK` in
> `App.jsx` must be updated to match.

### Triage filter cards (`TriageSummaryCards`)

Compact clickable cards are the **only** result filter UI, rendered above the
results table. Cards (in order): All / Domain On Hold / Flagged + Live + Recent /
Flagged + Live / Flagged + Recent / Flagged + Stale / Flagged + No-Live /
Unknown·Errors / Clean. Each shows label, count, and percentage. A colored
left-border accent identifies the bucket. Cards are real `<button>` elements with
`aria-pressed` and `aria-current` when active.

Clicking a card sets `activeFilter` to that bucket's filter key. Clicking an
active card resets to `'all'`. No API calls, no quota use. The legacy pill-style
`FilterBar` was removed in MDI-35.

### Results table (`ResultsTable`)

Polished operations-console table replacing the flat debug table. Columns:

1. Checkbox — connected to bulk **Export Selected** and **Rescan Selected**
2. `#` (position)
3. Domain / URL (monospace, truncated, tooltip)
4. Triage Bucket (colored badge + collapsible triage reasons `<details>`)
5. Confidence (colored text)
6. Recommended Action (formatted text)
7. VT Ratio (monospace, colored if flagged)
8. Freshness (badge)
9. Live (badge)
10. Created (YYYY-MM-DD)
11. Age (calculated from `created_at`; `age_bucket` shown as secondary context)
12. Evidence Status (badge)
13. Actions (detail eye + More Actions menu — MDI-30C)

Row **More actions** (⋮) opens a compact menu with explicit controls: Export
evidence (JSON), Open in VirusTotal, Refresh report, Request new scan. The detail
drawer section **8. Actions** uses the same control set. See **Row action controls**
below.

### Row action controls (MDI-30C)

Shared by the results-row More Actions menu and detail drawer section 8.

| Action | Active when | Backend | External call | Quota | Runtime | Owning ticket if disabled |
|---|---|---|---|---|---|---|
| **Export evidence (JSON)** | Row present; no action in progress | `POST /api/mdi/jobs/{job_id}/export` (`format=json`, `scope=selected`) | No | None | Reads saved job only | — |
| **Open in VirusTotal** | Row has `vt_report_url` | None | Browser tab to public VT GUI | None | None | MDI-34 |
| **Refresh report** | Row not held; normalized input; job loaded; not action-in-progress | `POST /api/mdi/jobs/{job_id}/refresh` | Yes (VT GET) when confirmed | ~1 unit per row | Updates job in memory + `mdi_latest_job.json` via existing path | — |
| **Request new scan** | Row scannable (URL/domain, not held); job loaded; not action-in-progress | `POST /api/mdi/jobs/{job_id}/scan` | Yes (VT POST/poll) when confirmed | 2–4+ units per row | Updates job in memory + `mdi_latest_job.json` via existing path | — |

**Menu open:** no backend calls, no quota, no external calls.

**Not in MVP:** Watchlist, Create Block Rule, Salesforce, monitoring, enforcement.

**Accessibility:** More Actions is a `<button>` with `aria-expanded`,
`aria-controls`, and `aria-haspopup="menu"`. Disabled actions use `disabled` and
`aria-disabled="true"` with explanatory `title`.

### Settings control contract (MDI-30B)

| Control | Location | Status | Payload field | Quota | Runtime | Notes |
|---|---|---|---|---|---|---|
| Domain reports for bare domains | Run Options (sidebar) | Active | `use_domain_reports` | On run | Job options saved at submit | — |
| Live checks: flagged only | Run Options (sidebar) | Read-only info | *(fixed backend rule)* | On run (flagged) | — | Future backlog for scope toggle |
| Stale threshold | Advanced Settings (gear) | Active | `stale_threshold_days` | None | Job options saved at submit | Default 7 |
| Auto-rescan stale flagged | Advanced Settings (gear) | Active (default OFF) | `auto_rescan_stale` | Additional VT on initial job | Job counters/history | Use cautiously |
| Max auto-rescans | Advanced Settings (gear) | Active | `max_auto_rescans` | Caps auto-rescan | — | Disabled when auto-rescan off |
| Exports reference | Advanced Settings (gear) | Read-only info | — | None | — | Points to active bulk/row/drawer exports (MDI-16) |
| Live-check reference | Advanced Settings (gear) | Read-only deferred | — | None | — | Future backlog |

**Removed:** vague “Coming soon” export/URL activity placeholders.

Row left-border accents identify priority tier (critical/high/medium/low/info/
clean). Row hover state. Scrollable with `max-height: 520px`.

### Checkbox selection

Row checkboxes and a header select-all are tracked in `selectedIds` state.
Selection drives **Export Selected** (CSV) and **Rescan Selected** (MDI-15).

### Bulk controls (`BulkControls`)

Five explicit buttons above the table (vague Actions dropdown removed in MDI-30C):
- **Export Flagged** (MDI-16 — CSV; flagged rows only; no quota)
- **Export All** (MDI-16 — CSV; all rows when job done/error)
- **Export Selected** (MDI-16 — CSV; selected positions)
- **Rescan Selected** (MDI-15 — enabled when job complete, rows selected, scannable)
- **Rescan Stale** (MDI-15 — enabled when eligible stale rows exist)

### MDI-16 / MDI-54A export API and fields

`POST /api/mdi/jobs/{job_id}/export` — body: `format` (`csv` | `xlsx` | `json`),
`scope` (`all` | `flagged` | `selected`), optional `positions` (required when
`scope=selected`; ignored for `all`/`flagged`).

Export Flagged, Export All, and Export Selected all use the same backend analyst
export builders (`export_service.build_csv_export` or `build_xlsx_export`). Scope
only changes which saved result rows are included. CSV remains the default UI
format; XLSX uses the same 10-column contract with result-based row coloring.

**Read-only guarantee:** default CSV exports use **saved job/result data only**.
They do **not** trigger VirusTotal, Cloudflare, WHOIS/RDAP, DNS, live-check,
quota usage, runtime file writes, or usage-history append.

#### Default CSV columns (MDI-54A — stable order)

`input`, `checked_as`, `result`, `registrar`, `hold_status`, `domain_created`,
`cloudflare_rank`, `detection_ratio`, `last_scanned`, `error`

| Column | Source / meaning |
|---|---|
| `input` | `input_original` — operator-facing input string |
| `checked_as` | Actual saved VT lookup method/target from `vt_mode_used` plus saved input fields (same target derivation as VT GUI URL behavior). **Not** parsed `input_type` alone. Examples: `url_report:http://example.com/`, `url_report:https://example.com/path`, `domain_report:example.com`, `skipped_on_hold`, `not_checked_quota_blocked`, `not_checked_error` |
| `result` | Analyst summary: `flagged`, `clean`, `on_hold`, `unknown`, or `error` |
| `registrar` | Saved registrar; blank when unavailable |
| `hold_status` | `clientHold`, `serverHold`, `clientHold + serverHold`, `unknown`, or blank when confirmed no hold (never `none`) |
| `domain_created` | Saved domain creation date as `YYYY-MM-DD`; blank when unavailable |
| `cloudflare_rank` | Cloudflare Radar **Popularity bucket** display value only (drawer-style), e.g. `>200000 / UNRANKED`. Not source, checked date, raw API object, or internal field names |
| `detection_ratio` | Saved VT ratio in slash form (e.g. `1/91`, `0/92`). Raw CSV cell is **tab-prefixed** so spreadsheet apps treat it as text and do not convert `1/91` to a date. Blank when VT skipped or unavailable; no misleading `0/0` |
| `last_scanned` | Saved VT scan timestamp (`YYYY-MM-DD HH:MM:SS UTC`); blank when VT skipped or unavailable |
| `error` | Concise error codes/messages from saved `errors[]`; blank when none |

**`result` values:**

- `on_hold` — clientHold/serverHold caused VT/live skip
- `flagged` — VT succeeded and malicious + suspicious hits ≥ 1
- `clean` — VT succeeded and malicious + suspicious hits = 0
- `unknown` — no reliable VT clean/flagged decision and not clearly a technical failure
- `error` — lookup, quota, processing, or export error prevents a reliable result

**CSV exclusions (default export):** wide forensic fields such as
`vt_engine_results`, full `epp_status`, `nameservers`, `domain_hold.raw_statuses`,
Cloudflare source/checked-at/raw-bucket columns, hold-impact fields, MDI-49 URL
evidence fields, stack traces, internal paths, and secrets. Use JSON evidence
export for the fuller field set.

#### JSON evidence export (unchanged by MDI-54A)

**JSON evidence schema:** `mdi-evidence-v1` — includes job metadata block,
scope, optional positions, and per-result objects with the full evidence field
set (including triage fields, sanitized `errors`, `vt_engine_results`,
`epp_status`, `nameservers`, `domain_hold`, `vt_mode_used`, Cloudflare rank
fields, hold-impact fields, MDI-49 VT URL evidence fields, etc.).

JSON evidence remains the **fuller export path** for forensic review. MDI-54A
changed the **default CSV contract only**. MDI-54B adds optional **XLSX** with
the same 10 columns, text-safe ratio/date cells, and full-row coloring by
`result` (`flagged`, `clean`, `on_hold`, `unknown`, `error`).

#### XLSX analyst export (MDI-54B)

Same 10-column order as CSV. Row fill colors are supplemental; `result` text is
always present. UI default remains CSV; bulk actions include a Format selector
(CSV / XLSX). JSON evidence export unchanged.

**Flagged export rule:** `triage_bucket` malicious/suspicious OR `vt_hits > 0`
OR `vt_suspicious > 0`; held rows excluded from flagged scope (included in
all/selected when explicitly chosen).

**No usage-history write:** exports do not append to `vt_usage_history.jsonl`.

### MDI-26 health / version API

`GET /api/mdi/health` — liveness plus deploy identity.

| Field | Type | Purpose | Notes |
|---|---|---|---|
| `status` | `str` | audit | Always `"ok"` when service is running. |
| `service` | `str` | audit | `"mdi"`. |
| `version` | `str` | audit | Semantic app version (e.g. `0.3.0`); not git commit. |
| `build_info` | `BuildInfo` | audit | Deploy marker; see below. |

`GET /api/mdi/version` — deploy audit endpoint returning `{ "build_info": … }`.

| Field | Type | Purpose | Notes |
|---|---|---|---|
| `build_info.app` | `str` | audit | `"mdi"`. |
| `build_info.commit` | `str?` | audit | Git SHA from deploy marker; `null` if missing. |
| `build_info.branch` | `str?` | audit | Branch at deploy; `null` if missing. |
| `build_info.built_at_utc` | `str?` | audit | ISO-8601 UTC deploy timestamp. |
| `build_info.source` | `str` | audit | `deploy_marker`, `missing`, or `invalid`. |

Marker file: `/opt/mdi/backend/build_info.json` (written at deploy; not in git).
Backend does **not** call git at runtime. Missing marker does not fail health.

### MDI-17 operational dashboard

`GET /api/mdi/dashboard` — read-only aggregate summary for windows:
Current Job, Last 7 Days, Last 30 Days, All Time.

**Data sources:** `vt_usage_history.jsonl` (filter `tool_name == "mdi"`), optional
`vt_daily_history.json` quota trend, current/recovered job for Current window.

**Historical aggregate fields (forward-only on new job completion):**
`job_duration_seconds`, `triage_bucket_counts`, `flagged_count`, `clean_count`,
`unknown_count`, `error_item_count`, `held_count`, `error_code_counts`.

**Dashboard privacy exclusions:** raw domains, URLs, `item_order`, result rows,
`vt_engine_results`, registrar, nameservers, EPP status, per-item HTTP/live status,
VT engine names.

**Data quality:** `records_skipped`, `records_non_mdi_skipped`,
`records_missing_triage_fields`, `records_missing_duration_fields`, `notes[]`.

Exports and dashboard GET do not append usage history.

Rescan actions show a confirmation modal with quota estimate before submitting.

### MDI-15 job action fields

| Field | Level | Purpose |
|---|---|---|
| `action_in_progress` | job | True while refresh/scan batch running |
| `last_action_type` | job | `refresh` or `scan` |
| `last_action_at` | job | Unix timestamp of last action completion |
| `vt_refresh_count` | job | Cumulative manual refreshes |
| `vt_scan_requested_count` | job | Cumulative scan requests |
| `vt_scan_failed_count` | job | Cumulative scan failures |

Usage history action aggregates: `refresh_count`, `scan_requested_count`,
`scan_completed_count`, `scan_failed_count`, `rescan_selected_count`,
`rescan_stale_count`, `operation` (`refresh` | `force_scan`).

### MDI-29 recovered job settings vs editable UI state

| Concept | Source | Purpose |
|---|---|---|
| **Saved job options** | `JobStatusResponse` fields on recovered/displayed job | Read-only **"Job ran with…"** metadata; what that job used at submit |
| **Editable next-run Settings** | Frontend React state (`DEFAULT_SETTINGS` on dismiss/clear) | Estimate/Submit payload for the **next** job; not overwritten by recovery |

Recovery (`GET /jobs/latest`) loads job results and saved options into the job
object only. It does **not** copy saved options into editable Settings.
Dismiss/Clear resets editable Settings to defaults (`auto_rescan_stale=false`,
`use_domain_reports=false`, `stale_threshold_days=7`, `max_auto_rescans=3`).

### MDI-15A auto-rescan fields

| Field | Level | Purpose |
|---|---|---|
| `auto_rescan_stale` | job option | Operator toggle at submit; default `false`; saved on job record |
| `max_auto_rescans` | job option | Per-job cap; default `3`; saved on job record |
| `auto_rescan_attempted_count` | job / history | VT scan attempts during initial processing |
| `auto_rescan_completed_count` | job / history | Scans that returned updated VT data |
| `auto_rescan_failed_count` | job / history | Pending or hard-failed scans |
| `auto_rescan_skipped_count` | job / history | Items evaluated but not rescanned |
| `auto_rescan_quota_blocked_count` | job / history | Skipped due to insufficient quota |
| `auto_rescan_enabled` | history | Mirror of `auto_rescan_stale` on job record |

Estimate fields: `auto_rescan_estimated_quota_min/max`,
`auto_rescan_domain_eligible_max`, `auto_rescan_url_eligible_max`,
`total_estimated_vt_calls_max`, `auto_rescan_estimated_duration_seconds_min/max`,
`auto_rescan_note`.

Auto-rescan estimate formula (worst case):
`slots = min(max_auto_rescans, domain_report_mode_count + url_report_mode_count)`;
`domain_slots = min(domain_report_mode_count, slots)`;
`url_slots = min(url_report_mode_count, slots - domain_slots)`;
`auto_rescan_estimated_quota_max = domain_slots × 5 + url_slots × 4`.

Auto-rescan eligibility: stale or very_stale flagged/suspicious items; not held,
not clean/fresh/error. Domain-report bare domains use MDI-28 domain reanalysis path.
One attempt per row per job. Runs only during initial `process_job` — not on
recovery or manual actions. IP inputs rejected before job creation (MDI-27).

### Disabled / deferred / rejected UI actions

| Feature | Classification | Status |
|---|---|---|
| **Open in VirusTotal** | active | Enabled when `vt_report_url` is present; opens public VT GUI (MDI-34) |
| **Watchlist** | rejected / out of scope | Not implemented |
| **Create Block Rule** | rejected / out of scope | Not implemented |
| **Salesforce / ticketing** | rejected / out of scope | Not shown |
| **Monitoring / enforcement** | rejected / out of scope | Not shown |
| Export XLSX/PDF/ZIP | deferred | XLSX analyst export active (MDI-54B); PDF/ZIP not implemented |
| Custom live-check scope toggle | deferred | Fixed flagged-only rule today (read-only in Run Options) |
| Extra export scopes (clean-only, stale-only) | deferred | CSV/JSON scopes above are active |
| Post-results UI layout cleanup (MDI-35) | done | Unified filter cards, Job ID in VT Usage & Status, compact estimate |
| Row click-target refinement | deferred | Eye icon vs full-row click |
| Dashboard quota trend chart | deferred | Nav quota widget shows current counter |
| Auto-rescan on recovered jobs | deferred / by design | Initial job submission only |
| Auto-rescan after manual refresh/scan | deferred / by design | Not chained to row actions |

Detail drawer, CSV/JSON export, dashboard, upload workflow, and row More Actions
menu are **active** — see [Operator Guide](operator-guide.md).
