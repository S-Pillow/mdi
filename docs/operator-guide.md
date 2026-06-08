# MDI Operator Guide

**Audience:** MDI operators and analysts  
**Production URL:** `https://forgeforward.app/tools/mdi/`  
**Related docs:** [Production Runbook](runbooks/mdi-production-runbook.md) · [Runtime Data](runtime-data.md) · [Field Purpose Map](field-purpose-map.md) · [Error Recovery Matrix](error-recovery-matrix.md)

---

## 1. Overview

### What MDI does

MDI (Malicious Domain Identifier) is a **triage and support tool** for reviewing
domains and URLs submitted by operators. For each accepted item, MDI may:

- Validate and normalize input
- Enrich registered domains via RDAP/WHOIS (domain age, registrar, hold status)
- Query VirusTotal (VT) for malicious/suspicious engine counts
- Run optional live URL checks on flagged items
- Classify items into triage buckets with recommended actions
- Support manual VT report refresh and new-scan requests
- Optionally auto-rescan stale flagged items (URL scans and domain reanalysis) during initial job processing
- Export CSV summaries or JSON evidence
- Show an operational dashboard (metadata-only aggregates; nav **Dashboard** button)

MDI helps operators **prioritize investigation**. It does not take enforcement
action on your behalf.

### What MDI does not do

- Block domains, URLs, or traffic
- Add items to a watchlist (not implemented)
- Create firewall or DNS block rules (not implemented)
- Open items in VirusTotal unless a saved `vt_report_url` is available
- Guarantee that every item receives a fresh VT scan on first pass
- Reserve VT quota in advance (estimate is advisory; see §4)
- Store a searchable historical database of every domain ever submitted

### Triage tool, not enforcement

Treat MDI output as **analyst guidance**. `recommended_action` values such as
`investigate`, `monitor`, or `takedown` are suggestions based on available
signals. Confirm findings through your own procedures before any external action.

---

## 2. Access and session recovery

### Production access

Open **`/tools/mdi/`** on the Forge Forward host (served as static frontend;
API at `/api/mdi/`).

### Recovered latest job

On page load, MDI calls `GET /api/mdi/jobs/latest`. If a prior completed job
was persisted to disk, the UI restores it and shows **"↩ Restored previous job input"**
in the input panel (with a dismiss control ✕). Job progress and Job ID appear in
**VT Usage & Status** in the sidebar — not in a separate bottom status strip.

**Daily quota vs recovered job:** **Used today (UTC)** and **Remaining** reflect the
current UTC quota day from `GET /api/mdi/usage`. If a recovered job completed on a
prior UTC day, the sidebar labels that section **Recovered job** (not **Current run**)
and shows how many VT lookups that saved job used. Daily quota counts reset at UTC
midnight and are independent of recovered-job progress stats.

**Expectations:**

- Only the **last completed or errored** job is recovered
- A job **still running** when the backend restarted is **lost**; the previous
  completed job may appear instead
- Recovery reads `mdi_latest_job.json` on the server (operators must never
  inspect this file directly — see [Runtime Data](runtime-data.md))

### Clear / dismiss restored session

Use the UI control to dismiss the restored session when you want a fresh start.
This clears the in-browser view; it does not delete server-side recovery data
until a new job completes and overwrites the recovery file.

**Saved job options vs next-run Settings:** A recovered job shows a read-only
**"Job ran with…"** summary (domain reports, auto-rescan, max auto-rescans,
stale threshold) from the saved job record. These are **historical options for
that job**, not the editable Run Options / Advanced Settings for your next run.
Editable settings in the sidebar (**Run Options**) and gear menu (**Advanced Settings**)
always reflect **defaults or your choices for the next job** — auto-rescan remains
**OFF** by default until you enable it in Advanced Settings.

**Results mode:** after a current or recovered job is displayed, the pre-scan
setup console (paste/upload, Estimate, Run MDI Check, VT Usage & Status, and Run
Options) is hidden so the results table, filters, and detail drawer remain the
primary workspace. **Start New Scan** appears above results. It clears the
displayed results in the browser, closes result-only UI state, returns you to the
input panel/setup mode, and **does not consume quota** or delete backend/runtime
history. It also **resets editable Settings to new-job defaults**. You can
manually change Settings again before Estimate or Run MDI Check. If auto-rescan
appeared ON only because a recovered job had been run with it ON, Start New Scan
returns it to OFF.

---

## 3. Input workflow

### Paste domains/URLs

Enter one item per line in the text area. MDI normalizes common forms (with or
without scheme, trailing slashes, etc.).

### Upload CSV/Excel

1. Choose a **CSV or XLSX** file (legacy `.xls` is not supported).
2. Click **Validate Upload** — preview shows accepted, rejected, held, and detected columns. **No quota consumed.**
3. Review column mapping and held domains in the upload validation panel.
4. Click **Estimate Quota & Runtime** — held upload domains are excluded from the VT estimate.
5. Click **Run MDI Check** — upload metadata (create date, EPP status, registrar, nameservers) is preserved into job results.

**Domain column** (required): DNS Form, Domain, Domain Name, Hostname, Host, URL, Target, Indicator.

**Optional metadata columns**: Create Date, EPP Status, Domain State, Registrar Name, Assigned Nameservers.

MDI detects the header row automatically, including files with leading `#` comment rows before the header.

### Auto-validation

Before running, MDI validates input offline:

| Outcome | Meaning |
|---|---|
| **Accepted** | Normalized item will be processed |
| **Rejected** | Invalid format, unsupported type, or policy skip |
| **Duplicate** | Same normalized key already in this batch |

### Common rejection causes

- Empty or whitespace-only lines
- Malformed URLs or hostnames
- Private/internal targets blocked by SSRF rules (live checks)
- Rows that fail normalization rules

### Domain / report mode

**Domain-report mode** (`use_domain_reports`) queries VT domain reports instead
of URL reports. Use when your input is primarily registered domains.

**Request New Scan** in domain-report mode uses VT **domain reanalysis**
(`POST /domains/{domain}/analyse`). **Refresh Report** re-fetches the existing
domain report only (lower cost). See §10–§11.

### Settings structure (Run Options vs Advanced Settings)

MDI splits configurable options into two places. Both apply to your **next**
Estimate or Run MDI Check and are **saved with the job at submit time**.

| Location | Label in UI | Controls |
|---|---|---|
| **Sidebar** | **Run Options** | Domain reports for bare domains (active); live-check scope (read-only — flagged items only, not configurable today) |
| **Nav gear menu** | **Advanced Settings** | Stale threshold (active); auto-rescan + max auto-rescans (active, **OFF by default**, quota-consuming when enabled) |

**Exports are not configured in Settings.** Use Results bulk actions, row More
Actions, or the detail drawer after a job completes. Exports do not consume VT quota.

**Live-check scope** is fixed today (eligible flagged items during processing).
Custom live-check settings are deferred (future backlog).

**Not in MVP:** Watchlist, Create Block Rule, Salesforce/ticketing, monitoring,
or automated enforcement — these do not appear in Settings.

When reviewing a recovered or in-progress job, both panels show **Locked**;
editable values apply to the next run only. See §2 for dismiss/clear behavior.

---

## 4. Estimate before running

### Why estimate matters

Always click **Estimate** before **Run MDI Check**. Estimate is free: it makes
**no VT, RDAP, WHOIS, DNS, or live URL calls** and does not consume quota.
Estimate output appears in a compact panel below the input action buttons; after
results exist it minimizes to a "Last estimate" line when still present.

Estimate shows:

- Accepted / rejected / duplicate counts
- Estimated VT call range (min/max)
- Estimated duration range
- Current quota remaining
- Whether the job would exceed available quota (`will_exceed_quota`)

### Shared VT quota

MDI shares a **500 lookups/day** VirusTotal quota with **VT Bulk Check**
(`/tools/vt-bulk-check/`). Both tools read the same counter at
`/var/lib/dns-tool/vt_usage.json`.

### Advisory estimate, enforced checks

The estimate is **advisory** for duration and auto-rescan worst cases. Before
each VT call during job processing, the backend performs **locked pre-VT quota
checks** to reduce the risk of exceeding the daily limit. This is not a full
reservation system — concurrent use by VT Bulk Check can still affect
headroom.

### `will_exceed_quota`

When `true`, the job is expected to need more VT units than remain today.
**Do not submit** large jobs in this state without coordinating quota use with
other operators or waiting for UTC midnight rollover.

---

## 5. Running a job

### Run MDI Check

After a satisfactory estimate:

1. Review **Run Options** (domain reports) and **Advanced Settings** (stale threshold, auto-rescan)
2. Click **Run MDI Check**
3. Monitor progress in the UI (status polling)

### Progress / status

The job moves through processing states per item. Held domains skip VT and live
checks by default. Errors on individual items do not necessarily fail the entire
job.

### Recovered job expectations

If you see a restored session, that job is **read-only for auto-rescan** —
auto-rescan runs only during **initial** job submission processing, not on
recovered jobs. The **Job ran with…** line shows whether that saved job was
submitted with auto-rescan enabled; it does not change your next-run Settings.

### What not to do during a job

- Do not start a second large job without checking quota
- Do not enable auto-rescan casually on big batches
- Do not assume estimate max duration is exact (RDAP throttle, live checks)
- Do not refresh the page expecting mid-job checkpoint recovery (not supported)

---

## 6. Triage cards and filtering

Triage filter cards are the **single client-side filter system** over the current
job results. They are **not** separate backend job types.

| Card | Filter logic |
|---|---|
| **All** | All result rows |
| **Domain On Hold** | `held` triage bucket |
| **Flagged + Live + Recent** | Malicious/suspicious + live/redirect + very new/new domain age |
| **Flagged + Live** | Malicious/suspicious + live or redirect |
| **Flagged + Recent** | Malicious/suspicious + very new/new age (live not required) |
| **Flagged + Stale** | Malicious/suspicious + stale/very stale VT freshness |
| **Flagged + No-Live** | Malicious/suspicious + not found/gone/DNS fail/etc. |
| **Unknown / Errors** | `error`, `unresolvable`, or `pending` buckets |
| **Clean** | `clean` bucket |

Click a card to filter the results table. Counts and percentages on cards reflect
the current job only. Active filter is indicated by card styling and `aria-pressed`.

---

## 7. Results table

### Important columns

| Column | Meaning |
|---|---|
| **Triage bucket** | Primary classification: malicious, suspicious, held, clean, etc. |
| **Confidence** | high / medium / low / unknown — strength of triage signal |
| **Recommended action** | Operator guidance: investigate, monitor, takedown, clear, skip, etc. |
| **VT ratio** | Malicious hits vs total engines (e.g. `3/72`) |
| **Freshness** | fresh, stale, very_stale, never_scanned — based on VT scan date |
| **Live status** | HEAD-request outcome for flagged URL-mode items |
| **Evidence status** | complete, partial, none — whether expected checks ran |

Rows are priority-sorted by virtual triage tier (critical flagged+live+recent
first).

---

## 8. Error and recovery guide

MDI stores per-item problems in structured `errors[]` objects (code, message,
severity, category). The UI shows severity badges — **ERROR**, **WARNING**,
**SKIPPED**, **INFO** — not raw JSON.

### Severity at a glance

| Severity | Meaning | What to do |
|---|---|---|
| **error** | Blocking failure; primary evidence incomplete | Retry later, Refresh/Scan if eligible, or contact admin |
| **warning** | Partial evidence (WHOIS, live check, scan pending) | Review context; VT triage may still be valid |
| **skip** | Intentional non-processing (hold, quota, unsupported scan) | Not a failure — usually no action |
| **info** | Operational notice (auto-rescan ineligible) | Read and continue |

**Skips are not failures.** Warnings do **not** automatically force an ERROR
triage bucket when VT succeeded.

### Accepted input shape (parse / upload)

MDI accepts **domains** and **URLs with domain hostnames** only (e.g.
`example.com`, `https://example.com/path`, `123.example.com`). **IP addresses**
(IPv4/IPv6 literals), **CIDR notation** (`1.2.3.0/24`), **IP ranges**
(`1.2.3.4-1.2.3.8`), and **IP-hostname URLs** (`http://8.8.8.8/`,
`http://[::1]/`) are rejected at parse-preview and upload validation with
`ip_address_not_supported`. No quota is consumed for rejected IP input.

Bare domains must be **dotted public-style names**. **Single-label hostnames**
(`localhost`, `printer01`, bare words like `not` or `valid`) and malformed
fragments (`domain/.com`, `example..com`) are rejected with `invalid_input`.
Numeric domain labels (`123.example.com`, `example123.com`, `1-example.com`) are
still accepted. Internal hostname inventory is out of scope unless a future
setting adds it.

### When to retry, refresh, or scan

| Situation | Preferred action |
|---|---|
| Parse-time rejection (`invalid_input`, `ip_address_not_supported`) | Fix input; wait for auto-validation — do **not** Run MDI Check until accepted |
| VT failure / quota block on row (`retry_lookup`) | New job later when quota allows |
| Stale VT report (`refresh_report`) | **Refresh Report** (~1 quota unit) |
| Very stale / pending scan (`request_new_scan`) | **Request New Scan** (~2–4 units); URL-mode only |
| `quota_lock_timeout` | Wait and retry — lock contention, **not** daily quota exhaustion |
| `auth_error` / `no_api_key` | **Contact admin** — configuration fix, not analyst retry |
| Export failed (`no_flagged_rows`, etc.) | Adjust export scope — **no new lookups** |

Full code-level matrix, recovery behavior, and test scenarios:
**[Error Recovery Matrix](error-recovery-matrix.md)**

---

## 9. Detail drawer

Open a row to inspect full evidence. Sections include:

- **Triage classification** — bucket, confidence, recommended action, reasons
- **VT Summary** — hits, suspicious count, ratio, scan date, freshness
- **VT Hit Details** — per-engine detections (when present)
- **Domain Age Context** — created date, age bucket, registrar (from RDAP/WHOIS)
- **Live Activity Context** — live status and check timestamp (when run)
- **Triage Reasons** — plain-language explanation strings
- **Evidence** — evidence status, freshness, and structured `errors[]` with severity badges

### Row More Actions menu (MDI-30C)

Each results row has a **More actions** button (⋮) beside the detail eye icon.
Clicking it opens a compact **Actions** menu with four explicit controls:

| Action | Status | Quota | Notes |
|---|---|---|---|
| **Export evidence (JSON)** | **Active** when a row is selected and no action is in progress | **None** | Uses existing `POST /api/mdi/jobs/{job_id}/export` with `format=json`, `scope=selected` |
| **Open in VirusTotal** | **Active** when row includes `vt_report_url` | **None** | Opens public VT GUI in a new browser tab; no backend call |
| **Refresh report** | **Active** when row is eligible (not held, has normalized input, job loaded) | **~1 unit per row** when confirmed | Reuses existing refresh modal + `POST …/refresh` |
| **Request new scan** | **Active** when row is scannable (URL or domain, not held) | **2–4+ units** when confirmed | Reuses existing scan modal + `POST …/scan` |

**Menu behavior:** Opening the menu does **not** call backend APIs or consume quota.
Disabled actions use `disabled` + `aria-disabled` and show a tooltip explaining why.
Only one row menu is open at a time. Press **Escape** or click outside to close.

**Not in MVP:** Watchlist, Create Block Rule, Salesforce/ticketing, monitoring, or
automated enforcement actions do not appear in this menu.

### Detail drawer actions

The drawer **8. Actions** section uses the same four controls and contracts as
the row More Actions menu (see above).

**Not in MVP:** Watchlist, Create Block Rule, Salesforce/ticketing, monitoring, or
automated enforcement actions do not appear in the drawer.

---

## 10. Manual Refresh Report

**Refresh VT Report** re-fetches the existing VT report for eligible rows.

| Aspect | Detail |
|---|---|
| **Typical cost** | ~1 VT quota unit per item (lower than Request New Scan) |
| **When to use** | VT data is stale but a new scan is not yet justified |
| **Confirmation** | Modal shows item count and quota impact before starting |
| **Scope** | Per-row, selected rows, or stale scannable rows |

### Scope cautions

- Held rows are not eligible
- Rows without a normalized input are skipped
- Large refresh batches near quota limits can block mid-batch

Refresh updates the **current job in place** (same `job_id`). It does not
create a new job.

---

## 11. Request New Scan

**Request New Scan** asks VT to reanalyse the item, then polls for results.

| Aspect | Detail |
|---|---|
| **Typical cost** | **2–4 VT quota units** per URL-scan row; **2–5** per domain-rescan row |
| **URL rows** | Submits URL for VT scan (existing URL workflow) |
| **Bare domain rows (domain-report mode)** | Requests VT **domain reanalysis** |
| **Bare domain rows (URL-report mode)** | Uses URL scan on `http://{domain}/` |
| **When not to use** | Near quota limit, held domains, or when refresh is sufficient |
| **Pending** | May return `vt_scan_pending` — prior VT evidence is preserved |

Use sparingly on high-priority items. Prefer **Refresh Report** when an
existing report may still be useful.

---

## 12. Auto-rescan stale flagged items

| Setting | Default |
|---|---|
| **Enabled** | **OFF** (`auto_rescan_stale = false`) |
| **Max auto-rescans** | **3** per job |

### Behavior

- Runs **only during initial job processing** (inline after first VT pass)
- Targets **stale flagged or suspicious** items only (not held, not clean, not fresh)
- May request **URL scans** (URL-report mode) or **domain reanalysis** (domain-report bare domains)
- Does **not** run on recovered jobs
- Does **not** run after manual refresh or Request New Scan
- Domain auto-rescan may produce `vt_scan_pending` — prior VT evidence is preserved; no retry loop
- Stops when quota is exhausted (`auto_rescan_quota_blocked_count` may increment)
- IP inputs remain rejected at parse/upload (MDI-27)

### Quota warning

Worst-case auto-rescan adds up to `domain_slots × 5 + url_slots × 4` VT units
(where slots are capped by `max_auto_rescans`) to the estimate max. **Do not enable**
on large batches without reviewing estimate totals and shared quota with VT Bulk Check operators.

---

## 13. Exports

Exports are **browser downloads** generated in memory by the backend. They
**do not consume VT quota** and **do not write server-side export files**.
They are **not configured in Settings** — use the Results area after a job completes:

| Export | Where | Scope |
|---|---|---|
| **Export All CSV** | Bulk actions | All rows in current job |
| **Export Selected CSV** | Bulk actions | Checked rows only |
| **Export Flagged CSV** | Bulk actions | Flagged rows (malicious/suspicious with VT hits) |
| **Evidence JSON** | Row More Actions or detail drawer | Selected row — full `mdi-evidence-v1` structure |

Additional export scopes (clean-only, stale-only, etc.) may be reviewed in a future ticket.

### CSV injection mitigation

Exported CSV fields that begin with `=`, `+`, `-`, or `@` are prefixed to reduce
spreadsheet formula injection risk. Still open exports from trusted jobs only.

### Large export caution

Exports are built **in memory**. Very large jobs (thousands of rows) may be
slow or fail in the browser. Export in smaller scopes if needed.

---

## 14. Dashboard

The operational dashboard (`GET /api/mdi/dashboard`) is **metadata-only**.

Open it from the nav **Dashboard** button. The panel behaves as a popover: click outside,
press **Escape**, or use the **×** close control to dismiss it. Interacting with the
results workspace (row actions, detail drawer, filters) also closes the dashboard so it
does not block triage review on narrower viewports.

| Window | Content |
|---|---|
| **Current** | Aggregates from latest recovered job (if any) |
| **7 Days** | Rolling window from usage history |
| **30 Days** | Rolling window from usage history |
| **All Time** | All MDI history records |

### Data-quality notes

- Older history records (pre-MDI-17) may lack triage percentage fields
- Dashboard shows `data_quality` notes when fields are absent
- Dashboard **never** lists raw historical domains or URLs
- Do not use the dashboard as a domain search tool

---

## 15. Quota awareness

| Rule | Detail |
|---|---|
| Shared limit | **500/day** combined MDI + VT Bulk Check |
| Always estimate first | Free; shows `will_exceed_quota` |
| Near limit | Avoid large jobs and auto-rescan |
| Refresh vs scan | Refresh is usually cheaper than Request New Scan |
| Auto-rescan | Can multiply VT use during initial processing |
| Dashboard / export | **Zero** VT quota consumption |

Check the quota widget in the nav bar. It reflects the shared counter.

---

## 16. Disabled / deferred / rejected features

### Active but limited

| Feature | Status |
|---|---|
| **Open in VirusTotal** | **Active** when `vt_report_url` is present on the row (domain or URL GUI link derived from saved VT results). Opens a new browser tab to the public VT site — **no quota consumed**, no VT API call. Disabled when no safe link can be built. |

### Deferred / future backlog

| Feature | Status |
|---|---|
| **Open in VirusTotal link population** | ~~Deferred~~ **Active (MDI-34)** when `vt_report_url` is derivable from saved results |
| **Custom live-check scope controls** | Deferred — fixed to eligible flagged items today |
| **Extra export scopes** (clean-only, stale-only, etc.) | Deferred — may be reviewed in a future ticket |
| **Post-results UI layout cleanup** (MDI-35) | Done — unified filter cards, Job ID in VT Usage & Status, compact estimate near input |
| **Row click-target refinement** | Deferred — eye icon vs row click behavior |
| **Dashboard quota trend surfacing** | Deferred — dashboard is metadata aggregates; nav quota widget shows current counter |

### Rejected / out of scope (MVP)

| Feature | Status |
|---|---|
| **Watchlist** | **Not implemented** — rejected for MVP unless explicitly approved later |
| **Create Block Rule** | **Not implemented** — rejected for MVP |
| **Salesforce / ticketing integration** | **Not implemented** |
| **Automated serverHold/clientHold enforcement** | **Not implemented** — MDI surfaces hold status; does not act on registries |
| **Enforcement actions** | **None** — MDI does not block, quarantine, or modify infrastructure |
| **Persistent monitoring** | **Not implemented** |

---

## 17. Safe operating rules

- **Always estimate** before running a job
- **Do not enable auto-rescan casually** — it consumes extra VT quota
- **Do not run large jobs** when near the daily quota limit
- **Do not manually edit** runtime files under `/var/lib/dns-tool/`
- **Do not print or paste** runtime file contents (job recovery, history, secrets)
- **Do not delete or truncate** `vt_usage_history.jsonl`
- **Do not treat the dashboard** as a historical domain/URL search
- **Prefer Refresh** over Request New Scan when appropriate
- **Coordinate with VT Bulk Check** operators on shared quota

---

## 18. Known limitations

- Estimate is advisory; locked pre-VT checks reduce race risk but are not a full
  reservation system
- Shared quota locking passed **controlled production validation (MDI-21)** after
  the VT Bulk hotfix (MDI-21A): sequential MDI + VT Bulk jobs, light concurrent
  jobs, usage-endpoint agreement, history reconciliation, no `quota_lock_timeout`,
  no permission errors, no lost updates. This was **not** a stress or load test.
- The initial MDI-21 run failed (VT Bulk stale cache); a one-unit historical
  undercount on the shared counter was documented and not manually corrected
- Dashboard triage percentages unavailable for older pre-MDI-17 history lines
- Large exports are generated in memory
- Auto-rescan only during initial job processing
- Request New Scan on bare domains uses domain reanalysis in domain-report mode (higher cost than refresh)
- Open in VirusTotal is active when `vt_report_url` is present; disabled when no safe GUI link exists
- Mid-job backend restart loses in-flight work; previous completed job may restore

---

## 19. Quick operator checklist

1. ☐ Open `/tools/mdi/`
2. ☐ Paste or upload input
3. ☐ Review accepted / rejected / duplicate counts
4. ☐ Click **Estimate**
5. ☐ Confirm quota headroom (`will_exceed_quota` is false)
6. ☐ Configure options carefully (domain reports, auto-rescan OFF unless needed)
7. ☐ **Run MDI Check**
8. ☐ Filter with triage cards
9. ☐ Inspect rows in detail drawer
10. ☐ Refresh or scan only when justified (quota-aware)
11. ☐ Export CSV/JSON if needed
12. ☐ Check dashboard for operational trends (metadata only)

For deployment, incidents, or permission errors, see the
[Production Runbook](runbooks/mdi-production-runbook.md).
