# MDI Error Recovery Matrix

**Audience:** analysts, admins, future developers/testers  
**Related docs:** [Operator Guide](operator-guide.md) · [Production Runbook](runbooks/mdi-production-runbook.md) · [Field Purpose Map](field-purpose-map.md) · [Runtime Data](runtime-data.md)

MDI-22A normalized backend error taxonomy; MDI-22B aligned the UI to display structured
`MdiError` objects. This document is the operator-facing recovery guide and future
validation test matrix. It does **not** change backend or frontend behavior.

---

## A. Purpose

Structured errors replace opaque strings and `[object Object]` display. Each error carries:

| Field | Operator meaning |
|---|---|
| `code` | Machine-readable identifier (stable for dashboard aggregation) |
| `message` | Human-readable explanation shown in UI |
| `source` | Which step produced the error (`vt_service`, `domain_enrichment`, etc.) |
| `retriable` | Whether retry may succeed when conditions improve |
| `category` | Subsystem grouping (see §C) |
| `severity` | How urgently the operator should respond (see §B) |
| `blocks_triage` | Whether this error can force the ERROR triage bucket |

**Severity drives operator response**, not just the presence of any `errors[]` entry:

- **error** — investigate, retry later, refresh/scan if appropriate, or escalate to admin
- **warning** — note partial evidence; VT triage may still be valid; do not treat as proof of safety
- **skip** — intentional non-processing; not a failure; usually no retry needed
- **info** — operational notice; no remediation required

**Skips are not failures.** A held domain, quota-blocked mid-run item, or domain-report
scan unsupported case is expected behavior — not evidence that MDI is broken.

**Retry/recovery choice:**

1. Read severity and category first
2. Check `recommended_action` on the row (operator guidance, not enforcement)
3. Use **Refresh Report** when existing VT data may suffice (lower cost)
4. Use **Request New Scan** only for URL-mode stale/high-priority items (higher cost; not supported in domain-report mode)
5. Use **Run MDI Check** (new job) for **Retry Lookup** scenarios — not export or dashboard refresh
6. Escalate **auth_error** / **no_api_key** to admin — not analyst retry loops

---

## B. Severity definitions

### `error` — blocking or primary evidence failure

- Primary evidence path failed (typically VT lookup, quota lock, or unrecoverable processing)
- May affect triage when `blocks_triage=true` (or severity is `error` and VT did not succeed)
- **Operator response:** retry later, refresh/scan if eligible, investigate, or contact admin
- **UI styling (MDI-22B):** red ERROR badge, critical table indicator

### `warning` — partial evidence problem

- Non-fatal subsystem failure (RDAP/WHOIS, live check, scan pending)
- VT decision may still be valid; **does not automatically force ERROR triage**
- **Operator response:** review context; consider refresh if stale; do not assume item is safe
- **UI styling:** amber WARNING badge, softer table indicator

### `skip` — intentional non-processing

- Expected skip: hold, quota exhausted mid-run, unsupported scan mode, empty export scope
- **Not a failure** — do not open incident tickets for normal skips
- **Operator response:** usually none; adjust input, quota, or scope
- **UI styling:** muted SKIPPED badge

### `info` — operational notice

- Auto-rescan ineligible, job limit reached, informational auto-rescan skip
- **Operator response:** read and continue; no remediation
- **UI styling:** muted INFO badge

---

## C. Category definitions

| Category | Subsystem | Typical sources |
|---|---|---|
| `input_validation` | Paste/parse normalization | `input_parser` |
| `upload_parse` | CSV/XLSX upload parsing | `upload_parser` |
| `vt_lookup` | VirusTotal report fetch/submit | `vt_service`, `vt` |
| `quota` | Daily quota exhaustion mid-run | `job_processor` |
| `quota_lock` | Cross-process quota lock contention | `job_processor`, `quota_lock` |
| `rdap_whois` | RDAP/WHOIS domain enrichment | `domain_enrichment` |
| `live_check` | SSRF-safe HTTP live probe | `live_check` |
| `refresh` | Manual VT report refresh action | refresh action handler |
| `scan` | Manual VT new-scan action | scan action handler |
| `auto_rescan` | Inline stale-flagged rescan during initial job | `auto_rescan` |
| `export` | CSV/JSON export generation | `export_service` |
| `recovery` | Job recovery read/register path | recovery endpoint |
| `persistence` | Latest-job snapshot write/read | `job_persistence` |
| `unknown` | Unclassified legacy or generic errors | various |

---

## D. Retry / recovery matrix

Columns: **Category · Example codes · Severity · Meaning · User-visible result · Recommended action · Retry allowed? · Quota impact · Notes**

### Input / upload

| Category | Codes | Sev | Meaning | User-visible | Action | Retry? | Quota | Notes |
|---|---|---|---|---|---|---|---|---|
| `input_validation` | `invalid_input` | error | Token failed normalization | Parse preview rejected row; code + message | Fix input; re-validate | Yes (parse only) | None | Shown in paste validation; no job submit |
| `input_validation` | `parse_error` | error | Parser internal failure | Rejected row or HTTP error | Fix input; retry parse | Yes | None | Rare in normal ops |
| `upload_parse` | `unsupported_file_type` | error | Not CSV/XLSX | Upload validation error | Use supported format | Yes | None | Preview only |
| `upload_parse` | `missing_domain_column` | error | No domain/URL column detected | Upload rejected summary | Fix spreadsheet headers | Yes | None | |
| `upload_parse` | `empty_input` | error | Empty file or no rows | Upload rejected | Provide data | Yes | None | Alias: `empty_file` |
| `input_validation` | `no_accepted_items` | error | All items rejected at parse | Submit blocked / estimate shows 0 accepted | Fix input batch | Yes | None | Job cannot start |

### VT lookup

| Category | Codes | Sev | Meaning | User-visible | Action | Retry? | Quota | Notes |
|---|---|---|---|---|---|---|---|---|
| `vt_lookup` | `timeout` | error | VT HTTP timeout | Row error bucket; drawer ERROR notice | Retry Lookup later | Yes | 0* | *Timeout may not increment quota |
| `vt_lookup` | `rate_limited` | error | VT HTTP 429 | Row error; dashboard `(error)` hint | Wait; retry later | Yes | 1 | May count the failing call |
| `vt_lookup` | `not_found` | error | No VT report yet | Row pending/error context | Request New Scan or retry job | Yes | 1–3 | URL mode may submit scan |
| `vt_lookup` | `auth_error` | error | VT auth failure / `no_api_key` | Job or row failure | **Admin fix** secrets/config | No (analyst) | 0 | Not analyst retry |
| `vt_lookup` | `server_error` | error | VT 5xx | Row error | Retry later | Yes | 1 | |
| `vt_lookup` | `vt_scan_pending` | warning | Scan submitted; report not ready | Amber warning in drawer/table | Wait; Refresh later | Yes | 2–4 | Not immediate failure |
| `scan` | `vt_scan_not_supported` | skip | Domain-report mode or ineligible | SKIP indicator; muted styling | Use URL mode or Refresh only | No scan | 0 | `scan_not_supported` alias |

### Quota

| Category | Codes | Sev | Meaning | User-visible | Action | Retry? | Quota | Notes |
|---|---|---|---|---|---|---|---|---|
| `quota` | `quota_blocked` | skip | Daily quota exhausted mid-run | Row skip; partial job | Wait for UTC midnight; Retry Lookup | Yes (next day) | 0 | `quota_exhausted` alias |
| `quota_lock` | `quota_lock_timeout` | error | Could not acquire quota lock in 5s | Row/job error | **Retry later**; check both services | Yes | 0 | **Not** daily exhaustion |

### RDAP/WHOIS

| Category | Codes | Sev | Meaning | User-visible | Action | Retry? | Quota | Notes |
|---|---|---|---|---|---|---|---|---|
| `rdap_whois` | `whois_failed` | warning | RDAP and WHOIS both failed | Amber warning; age may be unknown | Proceed with VT; note missing age | Optional | 0 | Does not force ERROR if VT OK |
| `rdap_whois` | `enrichment_error` | warning | Enrichment subsystem error | Amber warning | Same as whois_failed | Optional | 0 | |
| `rdap_whois` | `not_found` | warning | Domain not in RDAP/WHOIS | Partial age context | Verify domain validity | Optional | 0 | TLD/registry dependent |

### Live check

| Category | Codes | Sev | Meaning | User-visible | Action | Retry? | Quota | Notes |
|---|---|---|---|---|---|---|---|---|
| `live_check` | `dns_failed` | warning | DNS resolution failed | Amber warning | Note no-live signal | No live retry in UI | 0 | Triage may use no-live path |
| `live_check` | `blocked` | warning | SSRF policy blocked target | Amber warning | Expected for internal targets | No | 0 | |
| `live_check` | `redirect_blocked` | warning | Redirect violated SSRF rules | Amber warning | Review URL chain offline | No | 0 | |
| `live_check` | `timeout` | warning | Live HEAD timeout | Amber warning | Informational | No | 0 | |
| `live_check` | `server_error` | warning | Live check 5xx | Amber warning | Informational | No | 0 | |

### Refresh / scan (manual actions)

| Category | Codes | Sev | Meaning | User-visible | Action | Retry? | Quota | Notes |
|---|---|---|---|---|---|---|---|---|
| `refresh` | refresh errors | error | Refresh batch failed for item | Action status message `[code] message` | Retry Refresh | Yes | ~1/item | Updates job in-place |
| `scan` | scan errors | error | Scan request failed | Action modal / status message | Retry Scan | Yes | 2–4/item | Confirm modal first |
| `vt_lookup` | `vt_scan_pending` | warning | Scan queued at VT | Row warning | Refresh later | Yes | 0 additional | |
| `scan` | `vt_scan_not_supported` | skip | Domain-report or ineligible row | Disabled scan button | Use Refresh | No | 0 | |

### Auto-rescan

| Category | Codes | Sev | Meaning | User-visible | Action | Retry? | Quota | Notes |
|---|---|---|---|---|---|---|---|---|
| `auto_rescan` | `auto_rescan_quota_blocked` | warning/info | Auto-rescan skipped for quota | Info/warning in errors[] | Disable auto-rescan; retry job tomorrow | N/A | 0 | During initial job only |
| `auto_rescan` | `auto_rescan_job_limit` | info | Per-job max rescans reached | INFO notice | Expected cap | No | 0 | |
| `auto_rescan` | `auto_rescan_held` | info | Held item | INFO/skip | Expected | No | 0 | |
| `auto_rescan` | `auto_rescan_domain_report_mode` | info | Domain-report mode | INFO | Use URL mode for auto-rescan | No | 0 | |
| `auto_rescan` | `auto_rescan_not_stale` | info | Item not stale | INFO | Expected | No | 0 | |
| `auto_rescan` | `auto_rescan_not_flagged` | info | Item not flagged | INFO | Expected | No | 0 | |

### Export

| Category | Codes | Sev | Meaning | User-visible | Action | Retry? | Quota | Notes |
|---|---|---|---|---|---|---|---|---|
| `export` | `no_rows` | skip | Job has no results | `Export failed: [no_rows] …` | Adjust scope | Yes | 0 | No new lookups |
| `export` | `no_flagged_rows` | skip | No flagged rows in scope | Structured export message | Export All or Selected | Yes | 0 | |
| `export` | `invalid_selection` | error | Bad positions/scope | Export failed message | Re-select rows | Yes | 0 | |
| `export` | `unsupported_format` | error | Unknown format requested | Export failed | Use csv/json | Yes | 0 | API-level |
| `export` | `export_error` | error | Generic export failure | Export failed message | Retry export; reduce scope | Yes | 0 | |

### Recovery / persistence

| Category | Codes | Sev | Meaning | User-visible | Action | Retry? | Quota | Notes |
|---|---|---|---|---|---|---|---|---|
| `recovery` | missing snapshot | n/a | No `mdi_latest_job.json` | No restored job on load | Run new job | Yes | Per job | `GET /jobs/latest` → 404 |
| `recovery` | corrupt snapshot | n/a | JSON/schema invalid | Silent 404; no crash | Run new job | Yes | Per job | Logged server-side |
| `persistence` | write failure | n/a | Snapshot write failed | In-memory job OK; no restore after restart | Complete job; check disk/perms | Admin | 0 | Swallowed; job still usable |
| `recovery` | `schema_mismatch` | n/a | Older snapshot missing new fields | Restored job with defaults | Expected for old jobs | N/A | 0 | Fields default safely |

---

## E. Recommended action mapping

MDI sets `recommended_action` per row. Use it with severity — not instead of it.

| Recommended action | When MDI uses it | Operator interpretation |
|---|---|---|
| **Retry Lookup** | Processing error, quota block, VT failure | Rerun the item in a **new job** when quota/time allows — not the same as Refresh |
| **Refresh Report** | VT report is stale (`freshness` stale/very_stale) | **Refresh Report** in UI (~1 quota unit); lower cost than new scan |
| **Request New Scan** | VT report very stale or pending | **Request New Scan** (~2–4 units); URL-mode only |
| **No Action Based on VT** | Clean fresh VT, or flagged but no-live | No VT follow-up required based on current evidence |
| **Action Already Taken** | Registry hold detected | Acknowledge hold; do not rescan |
| **Review for Action** | Flagged + recent domain age | Human review before external action |
| **Verify / Investigate** | Ambiguous signals (`verify_investigate`, `investigate`) | Confirm with procedures; warnings do not mean safe |
| **Admin / configuration fix** | `auth_error`, `no_api_key`, persistent `quota_lock_timeout` | Contact admin; check `secrets.env` and service health — **do not** loop analyst retries |

**Clarifications:**

- **Retry Lookup** usually means submit a new job (or re-include the item) later — not click Refresh on the same recovered session for a parse-time error.
- **Refresh Report** re-fetches an existing VT report; prefer over Request New Scan when evidence may still be useful.
- **Request New Scan** is **not supported** for bare domains when **domain-report mode** is enabled.
- **`quota_lock_timeout`** means lock contention — retry later; it is **not** daily quota exhaustion (`quota_blocked`).
- **`auth_error` / `no_api_key`** require configuration/admin fix, not repeated analyst retries.
- **Export errors** should not trigger new VT lookups — adjust export scope only.
- **Warnings do not prove safety.** A clean VT result with WHOIS/live-check warnings still requires normal analyst judgment.
- **Clean VT does not guarantee safety** — MDI is triage support, not enforcement.

Legacy `manual_review` may appear on older persisted jobs for suspicious VT hits; current triage engine may emit `review_for_action` or `verify_investigate` instead. Treat as “human review needed,” not a system failure.

---

## F. Recovery behavior matrix

| Scenario | Behavior |
|---|---|
| Page refresh | Frontend calls `GET /api/mdi/jobs/latest`; restores last completed/errored job if available |
| Backend restart | In-memory jobs lost; `mdi_latest_job.json` reloaded into memory if valid |
| Recovered jobs keep saved options | `use_domain_reports`, `stale_threshold_days`, `auto_rescan_stale`, `max_auto_rescans` restored from snapshot |
| Old schema versions | Missing fields default safely (counters → 0; `errors[]` may lack `severity` — UI has fallback) |
| Corrupt/missing snapshot | `GET /jobs/latest` → 404; frontend shows empty state — **no runtime corruption** |
| In-flight job during restart | Lost; previous completed job may restore instead |
| Exports | Use current in-memory or recovered job data only; no server-side export files |
| Dashboard historical records | Metadata-only aggregates from `vt_usage_history.jsonl`; no per-domain history |
| Auto-rescan on recovered job | **Does not run** — only during initial job processing |
| Manual refresh/scan on recovered job | **Supported** — updates same `job_id` and overwrites snapshot |

---

## G. Test matrix

Future validation reference. **Do not run live VT tests without quota approval.**

| Scenario | Input/setup | Expected row state | Expected drawer/table display | Dashboard/export | Quota | Test type |
|---|---|---|---|---|---|---|
| Invalid paste input | `not a valid domain!!!` + `example.com` (×2) | 1 accepted (`example.com`); 4 rejected (`not`, `a`, `valid`, `domain!!!`); 1 duplicate | Rejected: `input_original`, `invalid_input`, ERROR badge | Parse only; no job | 0 | UI parse-preview |
| Duplicate-only input | `example.com` twice | 1 accepted, 1 duplicate | Duplicate shows `example.com` not `[object Object]` | Parse only | 0 | UI parse-preview |
| Missing upload column | XLSX without domain column | Upload rejected | `missing_domain_column` message | Upload preview | 0 | UI upload-preview |
| VT timeout | Mock/simulated timeout | `error` bucket if blocking | ERROR notice; `timeout` code | `error_code_counts` if job completes | 0 mock / 0–1 live | Backend mock |
| VT rate limit | Simulated 429 | `error` bucket | ERROR; `rate_limited` | Dashboard `(error)` hint | 1 if live | Backend mock |
| Quota blocked mid-run | Job exceeds remaining quota | Later rows `quota_blocked` skip | SKIP styling; not critical red | `quota_blocked_count` in history | 0 on skipped rows | Integration |
| Quota lock timeout | Lock held >5s (stress) | Row/job error | ERROR `quota_lock_timeout` | May appear in error counts | 0 | Admin/stress |
| VT success + WHOIS fail | RDAP/WHOIS fail, VT OK | Follows VT triage (not ERROR solely for WHOIS) | WARNING `whois_failed` in drawer | `whois_failed` `(warning)` hint | VT only | Integration |
| VT success + live-check fail | Flagged item; live error | Follows VT; live warning | WARNING live_check code; amber indicator | `live_check_error_count` | VT only | Integration |
| Held domain skip | Upload/domain with hold | `held` bucket; `skipped_hold` evidence | SKIP/info; no VT ratio | `held_count` | 0 | UI/integration |
| Domain-report scan unsupported | Domain row; domain-report mode on | Scan button disabled | `vt_scan_not_supported` if attempted | N/A | 0 | UI |
| Scan pending | Scan submitted; report not ready | May stay pending/warning | WARNING `vt_scan_pending` | N/A | 2–4 prior | Integration |
| Export no flagged rows | Export Flagged on clean job | N/A | `Export failed: [no_flagged_rows] …` | No file | 0 | UI export POST |
| Corrupt latest snapshot | Truncate `mdi_latest_job.json` in test env | No restore | Empty job state | N/A | 0 | Admin test env only |
| Recovered old job missing error fields | Pre-22A snapshot | Row displays | UI fallback severity; no `[object Object]` | Unchanged | 0 | UI regression |

---

## H. Do not do

| Prohibited | Why |
|---|---|
| Manually edit `vt_usage.json` | Breaks shared MDI + VT Bulk accounting |
| Truncate `vt_usage_history.jsonl` | Destroys audit trail and dashboard history |
| `cat /etc/dns-tool/secrets.env` | Exposes API keys |
| `cat` / paste `mdi_latest_job.json` contents | Contains operator-submitted domains/URLs |
| Run live VT tests without quota approval | Consumes shared 500/day quota |
| Treat **warnings** as proof of safety | Partial evidence only |
| Treat **clean VT** as guaranteed safe | Triage support, not verdict |
| Trigger new lookups to “fix” export errors | Exports are scope issues only |
| Open incident for normal **skip** severity | Expected holds/quota/skips |

---

## Document history

| Ticket | Change |
|---|---|
| MDI-22C | Initial error recovery matrix, test matrix, cross-links |
