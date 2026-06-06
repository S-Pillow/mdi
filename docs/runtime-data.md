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

## MDI-03 runtime file access summary

| File | MDI-03 Access | Notes |
|---|---|---|
| `vt_usage.json` | **READ** | Via `GET /api/mdi/usage` → `vt_quota.get_usage_summary()` |
| `vt_usage_history.jsonl` | None | Not touched this ticket |
| `vt_daily_history.json` | None | Not touched this ticket |
| `vt_latest_job.json` | **NEVER** | MDI must never access this file |
| `mdi_latest_job.json` | None | Does not exist yet |
| `mdi_daily_history.json` | None | Does not exist yet |
