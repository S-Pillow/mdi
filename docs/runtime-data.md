# MDI Runtime Data Inventory

This document lists every runtime file that MDI reads or writes during
operation.  Runtime files are **never committed to source control**.

---

## Files in `/var/lib/dns-tool/`

This directory is owned by `www-data:www-data` and is shared between the
VirusTotal Bulk Check tool (`dns-tool-backend`) and MDI (`mdi-backend`).

### `vt_usage.json` — Shared daily VT quota counter

| Field | Value |
|---|---|
| **Full path** | `/var/lib/dns-tool/vt_usage.json` |
| **Format** | JSON: `{"date_utc": "YYYY-MM-DD", "daily_lookups_used": N}` |
| **Owner** | `www-data` (written by dns-tool-backend uvicorn process) |
| **Permissions** | `644` (world-readable; safe for mdi-backend to read) |
| **MDI reads** | Yes — `vt_quota.read_usage_state()` and `GET /api/mdi/usage` |
| **MDI writes** | Not yet. Will write in quota-increment ticket (after MDI-03). |
| **Contains item data** | No — counts only |
| **Source-control** | Excluded by `.gitignore` (`/var/lib/dns-tool/`) |
| **Cleanup rule** | Resets automatically at UTC midnight (date rollover); never manually delete |
| **MDI-03 touches** | READ ONLY — `vt_quota.get_usage_summary()` |

### `vt_usage_history.jsonl` — Per-job JSONL usage history

| Field | Value |
|---|---|
| **Full path** | `/var/lib/dns-tool/vt_usage_history.jsonl` |
| **Format** | JSONL: one JSON object per line, one record per completed job |
| **Owner** | `www-data` |
| **Permissions** | `640` |
| **MDI reads** | Future — when usage-history export is implemented |
| **MDI writes** | Future — MDI will append one record per completed job with `tool_name: "mdi"` |
| **Contains item data** | No — metadata-only counts; no domain names or URLs |
| **Source-control** | Excluded by `.gitignore` |
| **Cleanup rule** | Append-only; never truncate manually. A future maintenance ticket may archive old records. |
| **MDI-03 touches** | NOT touched |

Existing records from vt-bulk-check do not have a `tool_name` field; MDI
records will always include `"tool_name": "mdi"`.  The CSV exporter in
vt-bulk-check will encounter this field as an unknown key and silently ignore it
until a future column-addition ticket updates that exporter.

### `vt_daily_history.json` — Rolling 90-day daily usage

| Field | Value |
|---|---|
| **Full path** | `/var/lib/dns-tool/vt_daily_history.json` |
| **Format** | JSON: `{"YYYY-MM-DD": N, ...}` — up to 90 day entries |
| **Owner** | `www-data` |
| **Permissions** | `644` |
| **MDI reads** | Future — when dashboard usage chart is implemented |
| **MDI writes** | Future — will update alongside `vt_usage.json` during quota increment |
| **Contains item data** | No — daily totals only |
| **Source-control** | Excluded by `.gitignore` |
| **Cleanup rule** | Pruned automatically to last 90 days on each write |
| **MDI-03 touches** | NOT touched |

### `vt_latest_job.json` — VT Bulk Check job recovery snapshot

| Field | Value |
|---|---|
| **Full path** | `/var/lib/dns-tool/vt_latest_job.json` |
| **Format** | JSON: full job snapshot including normalised results |
| **Owner** | `www-data` |
| **Permissions** | `600` (restricted) |
| **MDI reads** | **NEVER** |
| **MDI writes** | **NEVER** — exclusively owned by vt-bulk-check |
| **Contains item data** | Yes — normalised item keys and VT results |
| **Source-control** | Excluded by `.gitignore` |
| **Cleanup rule** | Automatically expired after 7 days by vt-bulk-check; never manually delete |
| **MDI-03 touches** | NOT touched |

> **Hard rule:** MDI must never read or write `vt_latest_job.json`.
> MDI uses a separate `mdi_latest_job.json` for its own job recovery.

---

## Planned future files in `/var/lib/dns-tool/`

### `mdi_latest_job.json` — MDI job recovery snapshot *(future)*

| Field | Value |
|---|---|
| **Full path** | `/var/lib/dns-tool/mdi_latest_job.json` |
| **Format** | JSON: full MDI job snapshot |
| **MDI reads** | Yes — job recovery endpoint |
| **MDI writes** | Yes — after job completion, atomic write |
| **Contains item data** | Yes — normalised item keys and per-check results |
| **Source-control** | Excluded by `.gitignore` (`/var/lib/dns-tool/`) |
| **Created in** | Future job-persistence ticket |

### `mdi_daily_history.json` — MDI rolling daily history *(future)*

| Field | Value |
|---|---|
| **Full path** | `/var/lib/dns-tool/mdi_daily_history.json` |
| **Format** | JSON: `{"YYYY-MM-DD": N, ...}` |
| **MDI reads** | Yes — dashboard chart |
| **MDI writes** | Yes — alongside quota increment |
| **Contains item data** | No — daily totals only |
| **Source-control** | Excluded by `.gitignore` |
| **Created in** | Future quota-increment ticket |

---

## MDI-08 runtime file access summary

### MDI-08 runtime behavior

MDI-08 introduces disk persistence for the latest completed MDI job.

| File | MDI-08 Access | Notes |
|---|---|---|
| `mdi_latest_job.json` | **NEW — READ + WRITE (atomic)** | Written after each job reaches `done` or `error` status. Read by `GET /api/mdi/jobs/latest` for recovery. |
| `vt_usage.json` | **READ ONLY** (estimate/submit checks, unchanged) | Not touched by persistence layer. |
| `vt_usage_history.jsonl` | **APPEND** (at job completion, MDI-06 behavior unchanged) | Not changed. Recovery does not add new records. |
| `vt_daily_history.json` | **READ + WRITE** (at job completion, MDI-06 unchanged) | Not changed. |
| `vt_latest_job.json` | **NEVER** | MDI hard rule, unchanged. |

### `mdi_latest_job.json` — MDI latest job recovery file *(created in MDI-08)*

| Field | Value |
|---|---|
| **Full path** | `/var/lib/dns-tool/mdi_latest_job.json` |
| **Env var override** | `MDI_LATEST_JOB_FILE` |
| **Format** | JSON: full MDI job snapshot (see below) |
| **MDI reads** | Yes — `job_persistence.read_latest_job()` → `GET /api/mdi/jobs/latest` |
| **MDI writes** | Yes — `job_persistence.write_latest_job()` after job completion. Atomic: `tmp → os.replace()` |
| **Permissions** | `0o600` applied via `os.chmod()` after write |
| **Owner** | root (since `mdi-backend` runs as root — deferred ops hardening) |
| **Contains item data** | **Yes** — normalized domains/URLs and per-item VT results |
| **Data sensitivity** | Operational threat-intel data, not PII. Private to MDI operator. |
| **Retention** | Overwritten by each subsequent completed/error job. No TTL. |
| **Source-control** | Excluded by `.gitignore` (`/var/lib/dns-tool/`) |
| **Cleanup** | Manual only, with operator approval |
| **Corrupt behavior** | `read_latest_job()` returns `None` → `GET /api/mdi/jobs/latest` returns 404. Backend never crashes. |
| **Missing behavior** | Same as corrupt: `None` → 404. |
| **Shared with** | Not shared. Private to MDI (`vt_latest_job.json` belongs exclusively to VT Bulk Check). |

**Why full item-level data is allowed in this file:**

This file is **not** the shared metadata-only history log (`vt_usage_history.jsonl`).
It is a private, single-slot, operator-owned recovery file. The operator submitted the
data; the operator is the only consumer of this recovery. The file is:
- git-excluded
- overwritten (not appended) on each completed job
- not queryable as a historical domain database
- not accessible to other tools

### MDI-08 write sequence in `job_processor.py`

1. Set `job.status = "done"` or `"error"`
2. Set `job.completed_at`
3. `_write_history()` — appends metadata-only record to `vt_usage_history.jsonl`
4. `_write_persistence()` — atomically writes full job to `mdi_latest_job.json`

Step 4 failure is logged and swallowed — the in-memory job remains valid for the
current session even if disk persistence fails.

### MDI-15 refresh/rescan actions

Manual refresh/scan updates the **existing job in-place** (same `job_id`).
After each action batch completes:

1. Result rows updated in memory
2. `mdi_latest_job.json` overwritten with full updated job snapshot
3. One **aggregate-only** record appended to `vt_usage_history.jsonl` with
   `operation: "refresh"` or `operation: "force_scan"`

Action batches do not create a new job. Saved `use_domain_reports` and
`stale_threshold_days` from the original job are preserved.

**Test isolation (MDI-14A + MDI-15):** All backend tests redirect runtime paths
via `backend/tests/conftest.py` autouse fixture — live files are never touched.

### MDI-15A auto-rescan (initial job processing only)

Auto-rescan runs **only during initial job submission processing**, inline after
the first VT report and triage for each item. It does **not** run on recovered
jobs, after manual refresh/scan, or on a background schedule.

**`mdi_latest_job.json` stores:**
- Saved options: `auto_rescan_stale`, `max_auto_rescans`
- Aggregate counters: `auto_rescan_attempted_count`, `auto_rescan_completed_count`,
  `auto_rescan_failed_count`, `auto_rescan_skipped_count`,
  `auto_rescan_quota_blocked_count`
- Updated result rows and item-level `errors` (e.g. `auto_rescan_quota_blocked`,
  `vt_scan_pending`)

**`vt_usage_history.jsonl` stores (aggregate-only, on `operation: report_lookup`):**
- `auto_rescan_enabled`
- Same five auto-rescan counter fields

**Must not appear in usage history:** raw domains, URLs, engine names, VT engine
results, EPP status, registrar, nameservers, per-item live/HTTP status, full
result rows, or `item_order`.

**Test isolation:** `backend/tests/conftest.py` redirects all runtime paths to
`tmp_path`; no live quota consumed during tests.

### MDI-08 recovery flow

On `mdi-backend` restart the in-memory store is empty.  The frontend calls
`GET /api/mdi/jobs/latest` on mount:
1. Backend checks in-memory store (empty after restart).
2. Backend reads `mdi_latest_job.json`.
3. Deserializes → registers job back into in-memory store.
4. Returns `JobStatusResponse` to frontend.
5. Frontend shows results with "↩ Restored from last session" notice.

If `mdi_latest_job.json` is missing or corrupt: endpoint returns 404, frontend
shows nothing on mount (silent).

### MDI-08 known limitation

If `mdi-backend` restarts while a job is still **running**, that in-flight job is
lost.  `mdi_latest_job.json` retains the **previous** completed job (the in-progress
job was never written to disk).  The previous completed job will be restored instead.
This is a documented MDI-08 limitation; mid-job checkpoint writes are deferred.

### MDI-08 test isolation

All MDI-08 tests inject `tmp_path`-based paths via `MDI_LATEST_JOB_FILE` env var
and the `job_file=tmp_path/...` parameter.  The live
`/var/lib/dns-tool/mdi_latest_job.json` is **never created or modified** by any
MDI-08 test.

---

## MDI-07 runtime file access summary

### MDI-07 runtime behavior

MDI-07 adds `POST /api/mdi/jobs/estimate`.  This endpoint is **strictly read-only
and produces no side effects**.

| File | MDI-07 Access | Notes |
|---|---|---|
| `vt_usage.json` | **READ ONLY** | `read_remaining_quota()` reads the current daily counter to populate `quota_remaining_now`. No write. No increment. mtime is unchanged after any estimate call. |
| `vt_usage_history.jsonl` | **None** | No job is created; no history record is appended. |
| `vt_daily_history.json` | **None** | Not touched. |
| `vt_latest_job.json` | **NEVER** | MDI hard rule — unchanged. |
| `mdi_latest_job.json` | **None** | Does not exist. Job persistence deferred to MDI-08. |

### MDI-07 estimate endpoint guarantees

- `external_calls_made: false` — no VT, WHOIS, DNS, or URL Activity Scanner calls.
- `quota_consumed: false` — no quota is incremented.
- `mutated: false` — no runtime file is written.
- Uploaded file bytes: none — the estimate endpoint accepts only `raw_input` (JSON string).

### MDI-07 test isolation

All MDI-07 estimate tests that assert `quota_remaining_now` inject a `tmp_path`-based
usage file via the `VT_USAGE_FILE` environment variable.  The live
`/var/lib/dns-tool/vt_usage.json` file is **never written** by any MDI-07 test.
`test_live_quota_file_not_modified` in `test_estimate.py` asserts that the mtime
of the live file is unchanged after each estimate endpoint call.

---

## MDI-06 runtime file access summary

### MDI-06 runtime behavior

MDI-06 introduces actual runtime file **writes** for the first time.

| File | MDI-06 Access | Notes |
|---|---|---|
| `vt_usage.json` | **READ + WRITE (atomic)** | Incremented after each VT API call via `quota_writer.increment_quota()`. Atomic: `tmp → os.replace()`. |
| `vt_usage_history.jsonl` | **APPEND** | One metadata-only record appended per completed job via `quota_writer.append_usage_history()`. |
| `vt_daily_history.json` | **READ + WRITE (atomic)** | Updated per-job on completion via `quota_writer.update_daily_history()`. Failure is logged and swallowed. |
| `vt_latest_job.json` | **NEVER** | Exclusively owned by VT Bulk Check. MDI must not read or write this file. |
| `mdi_latest_job.json` | **Not yet** | Deferred. Job recovery is out of scope for MDI-06. |

### In-memory job state

- MDI-06 stores all job state in process memory only (`services/job_store.py`).
- Jobs are **not persisted to disk**. Service restart loses all in-flight and completed jobs.
- This is a **documented MDI-06 limitation**. Job recovery is out of scope.
- No dashboard history (beyond the metadata-only JSONL append).
- No `mdi_latest_job.json` is written.

### Quota write safety

- `quota_writer.increment_quota()` uses `asyncio.Lock` for in-process serialization.
- Write is atomic: content written to `{file}.tmp` then renamed with `os.replace()`.
- **Accepted MVP risk:** both `mdi-backend` and `dns-tool-backend` may write `vt_usage.json`
  simultaneously in separate processes. The race window is a single `os.replace()` call.
  This is documented and carried forward to a future atomic-locking ticket.

### Usage history contract

Records appended to `vt_usage_history.jsonl` by MDI-06 are **metadata-only**:
- `tool_name = "mdi"`
- `operation = "report_lookup"`
- Counts: `items_attempted`, `items_completed`, `quota_units_consumed`, `quota_blocked_count`,
  `errors_count`, `held_skipped_count`
- `processing_options_summary` (dict with `use_domain_reports`, `stale_threshold_days`)
- `status` (`done` or `error`)
- **No raw domains, URLs, or item-level result data.**

### MDI-06 test isolation

All MDI-06 tests use `tmp_path` for quota/history files:
- `job_processor.process_job(job_id, usage_file=tmp_path/..., history_file=tmp_path/...)`
- Live `/var/lib/dns-tool/vt_usage.json` is **never modified** by any MDI-06 test.
- Test `test_live_vt_usage_file_not_modified` asserts mtime unchanged after each test run.

---

## MDI-05 runtime file access summary

| File | MDI-05 Access | Notes |
|---|---|---|
| `vt_usage.json` | **READ** | Via `GET /api/mdi/usage` only. `POST /api/mdi/jobs/upload-preview` does NOT read this file. |
| `vt_usage_history.jsonl` | None | Not touched |
| `vt_daily_history.json` | None | Not touched |
| `vt_latest_job.json` | **NEVER** | MDI must never access this file |
| `mdi_latest_job.json` | None | Does not exist yet |
| `mdi_daily_history.json` | None | Does not exist yet |

### MDI-05 upload-preview file guarantees

- **No runtime files created** by `POST /api/mdi/jobs/upload-preview`.
- **No runtime files modified** — `/var/lib/dns-tool/vt_usage.json` mtime is unchanged after any upload-preview call.
- **Uploaded file bytes are not persisted** — file content is read from the HTTP request body, parsed, and discarded. No temporary files are written.
- **No external calls made** — hold detection is purely offline string matching against the uploaded status column.
- **No quota consumed** — `quota_consumed: false` in every upload-preview response.

---

## MDI-03 runtime file access summary

| File | MDI-03 Access | Notes |
|---|---|---|
| `vt_usage.json` | **READ** | Via `GET /api/mdi/usage` → `vt_quota.get_usage_summary()` |
| `vt_usage_history.jsonl` | None | Not touched this ticket |
| `vt_daily_history.json` | None | Not touched this ticket |
| `vt_latest_job.json` | **NEVER** | MDI must never access this file |
| `mdi_latest_job.json` | None | Does not exist yet |
| `mdi_daily_history.json` | None | Does not exist yet |

---

## MDI-11 — WHOIS/RDAP Enrichment Runtime Notes

### New runtime files

MDI-11 adds **no new runtime files**. RDAP and WHOIS results are held in memory
only (per-job domain cache) and are never written to disk directly.

### `mdi_latest_job.json` — enriched fields added

After MDI-11, completed jobs stored in `mdi_latest_job.json` include all
enrichment fields that were populated during RDAP/WHOIS lookup:

```json
{
  "created_at": "1995-08-14T04:00:00+00:00",
  "age_bucket": "mature",
  "registrar": "IANA",
  "epp_status": ["clientTransferProhibited", "clientUpdateProhibited"],
  "nameservers": ["a.iana-servers.net", "b.iana-servers.net"],
  "domain_hold": {
    "has_hold": false,
    "hold_types": ["none"],
    "source": "rdap",
    "raw_statuses": ["clientTransferProhibited", "clientUpdateProhibited"]
  }
}
```

These are publicly available RDAP fields — no PII. The file remains `0600`
permissions and is excluded from git via `.gitignore`.

### `vt_usage_history.jsonl` — enrichment counts added

MDI-11 adds five new count fields to each history record. **No raw domain names,
registrar names, nameservers, or EPP status strings are ever written** to this file.

New count-only fields per record:
- `rdap_enriched_count` — number of items enriched via RDAP or WHOIS
- `rdap_failed_count` — number of items where both RDAP and WHOIS failed
- `whois_fallback_count` — number of items where RDAP failed but WHOIS succeeded
- `hold_detected_by_enrichment_count` — items where live hold caused VT skip
- `enrichment_skipped_uploaded_hold_count` — items whose hold was already confirmed by upload

### External services used during live job processing

MDI-11 introduces two new external service dependencies for live job runs:

| Service | URL | Purpose | Failure behavior |
|---|---|---|---|
| rdap.org | `https://rdap.org/domain/{domain}` | RDAP lookups | Non-fatal; WHOIS fallback |
| WHOIS (system) | N/A (subprocess) | Fallback if RDAP fails | Non-fatal; item proceeds to VT |

These services are used **only during `process_job()` execution** — not during:
- `POST /api/mdi/jobs/estimate` (pure estimate, no enrichment)
- `POST /api/mdi/jobs/submit` (job creation only; enrichment happens in background task)
- `GET /api/mdi/jobs/{id}` (status polling)
- `GET /api/mdi/jobs/latest` (recovery)
- Any upload/preview endpoints

### Rate limiting and timeout behavior (MDI-11A)

**rdap.org** allows approximately 10 requests per 10 seconds (~1 req/s).
MDI enforces a conservative **1.1-second minimum gap** between consecutive RDAP
requests via `_rdap_acquire_slot()` in `domain_enrichment.py`.

- RDAP rate limiter: `_RDAP_MIN_INTERVAL_SECONDS = 1.1 s` enforced before each request
  (both initial and retry).
- RDAP timeout: 10 seconds per request.
- RDAP 429 handling:
  - If a `Retry-After` header is present and numeric, wait that many seconds (capped at 60 s).
  - If the header is absent or invalid, wait the default **5 seconds**.
  - Retry **once only**. If the retry also fails or is rate-limited, fall through to WHOIS.
- WHOIS: blocking I/O in thread executor; no explicit timeout (relies on OS).
- Per-job domain cache: duplicate registered domains enriched once per job, avoiding
  redundant RDAP calls.

> **Future consideration:** IANA bootstrap routing (`https://data.iana.org/rdap/`)
> could route queries to TLD-specific RDAP servers rather than rdap.org, which
> would eliminate the shared rate limit for large batches. This is deferred to a
> future deliverable if large-batch enrichment becomes common.

### Estimate runtime impact (MDI-11A)

`POST /api/mdi/jobs/estimate` returns separate enrichment duration fields:

| Field | Description |
|---|---|
| `estimated_enrichment_lookups` | Conservative: 1 RDAP lookup per item |
| `estimated_enrichment_duration_seconds_min` | Best case: 0 s (all items share 1 registered domain) |
| `estimated_enrichment_duration_seconds_max` | Worst case: N × 1.1 s (all unique registered domains) |
| `enrichment_note` | Informational note about RDAP throttle behavior |
| `enrichment_warning` | Non-empty when N > 100; warns about extended enrichment time |

`estimated_duration_seconds_min/max` represent the **total** (VT + enrichment):
- `total_min = VT_min + 0`
- `total_max = VT_max + (N × 1.1 s)`

**Warning threshold:** For batches larger than 100 unique domains, the estimate
includes an `enrichment_warning` describing the expected delay:
> *Example for 500 unique domains: "RDAP enrichment may add up to 9.2 minutes …"*

The per-job domain cache means real-world enrichment time is typically lower than
the worst-case estimate.

---

## MDI-12 — Live-Check Runtime Impact

### No new runtime files

MDI-12 adds no new files to `/var/lib/dns-tool/`.  The live-check results are
held in memory on `InMemoryJob.results[...].live_status` and written to
`mdi_latest_job.json` via the existing persistence path.

### `mdi_latest_job.json` changes

`MdiResultItem.live_status` is now populated for flagged/suspicious items.
Recovery (`GET /api/mdi/jobs/latest`) restores `live_status` correctly.

**Allowed `live_status` values in persisted JSON:**
`active`, `redirect`, `forbidden`, `not_found`, `gone`, `timeout`,
`dns_failure`, `connection_refused`, `blocked`, `server_error`, `unknown`,
`not_checked`.

### `vt_usage_history.jsonl` changes

Three new aggregate-count fields are appended per job record:

| Field | Description |
|---|---|
| `live_check_count` | Number of items that received a live check |
| `live_check_skipped_count` | Number of items skipped by eligibility rules |
| `live_check_error_count` | Number of items where live check returned an error |

**Privacy guarantee — must not appear in history records:**
- Submitted URLs, domains, or hostnames
- Resolved IP addresses from DNS
- Redirect chain URLs or hop counts per item
- Final resolved URLs
- `live_status` value per item
- HTTP status codes per item
- Live-check error messages per item

All three new fields are metadata-only aggregate integers.

### Live-check estimate fields

Added to `EstimateResponse` (no runtime file interaction):

| Field | Value |
|---|---|
| `estimated_live_check_count` | Always `0` — flagged count unknown before VT runs |
| `live_check_note` | Explanatory string about conditional timing |

Live-check duration is **not** added to `estimated_duration_seconds_min/max`
because the number of flagged items is not known at estimate time.

### External services contacted at runtime

Live checks contact the target URL's server directly.  MDI-12 connects only
to public internet hosts; SSRF protections block all internal/private targets.

No new third-party APIs are added.  No credentials or tokens are required for
live checks.  No results are sent to external services.

---

## MDI-15A — Auto-Rescan Estimate Fields

Added to `EstimateResponse` (no runtime file interaction when estimating):

| Field | Description |
|---|---|
| `auto_rescan_estimated_quota_min` | Always `0` when enabled |
| `auto_rescan_estimated_quota_max` | `min(max_auto_rescans, url_report_mode_count) × 4` |
| `total_estimated_vt_calls_max` | Base worst-case + auto-rescan worst-case |
| `auto_rescan_estimated_duration_seconds_min` | `0` |
| `auto_rescan_estimated_duration_seconds_max` | Sequential VT gap overhead for auto-rescan max |
| `auto_rescan_note` | Conditional usage disclaimer |

Submit guard uses `total_estimated_vt_calls_max` when `auto_rescan_stale` is enabled.
