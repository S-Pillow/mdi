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

## Fields explicitly NOT included

| Data | Reason omitted |
|---|---|
| Registrant name / email / phone | Personal data; not needed for triage |
| Raw WHOIS text | Too large; noisy; extract structured fields instead |
| Full VT engine list (default) | `vt_engine_results` is present but excluded from exports by default |
| IP address of URL target | Not collected; SSRF safety layer blocks IP-targeted requests |
| User agent sent during live check | Not logged; privacy |
