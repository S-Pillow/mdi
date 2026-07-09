# MDI Release Readiness and Operator Handoff

**Audience:** analysts, operators, and maintainers  
**Status:** MDI is good enough for internal analyst use with the limitations below.  
**Production URL:** `https://forgeforward.app/tools/mdi/`

Related docs:
- [Operator Guide](operator-guide.md)
- [Field Purpose Map](field-purpose-map.md)
- [Deployment Notes](deployment/deployment-notes.md)
- [Production Runbook](runbooks/mdi-production-runbook.md)
- [Runtime Data](runtime-data.md)
- [Error Recovery Matrix](error-recovery-matrix.md)

---

## 1. Release Status

MDI is release-ready for internal use as a production-capable prototype. No current
release blocker is known.

The UI/workflow reached a **good-enough stable checkpoint**. Good-enough status
means a stable checkpoint, not a permanent design freeze. Future UI changes are
allowed when supported by real operator use, screenshots, accessibility/readability
concerns, workflow clarity issues, or external review. Such changes must remain
AIPF-controlled, scoped, reversible, and must preserve stable backend, quota,
runtime, and results-mode behavior unless separately approved.

UI-only work should still be prioritized when it addresses one of:

- functional defect
- unreadable or unclickable control
- broken workflow
- accessibility failure
- major layout regression
- misleading quota/action behavior
- production-blocking usability issue
- reviewed workflow-clarity or readability friction (see MDI-FABLE-01 intake below)

Taste-only changes without supporting evidence belong in backlog.

## 2. Production Version Alignment

| Component | Production state | Notes |
|---|---|---|
| Frontend | MDI-57B: `d001df62bfe9ec0b272efc5a7a527ef83f363537` | Static bundle: `index-p3SY0k4J.js`, `index-BQreofYY.css` at `/var/www/html/tools/mdi/`; previous `index-BlibenHD.js` removed |
| MDI backend | MDI-57B: `d001df62bfe9ec0b272efc5a7a527ef83f363537` | `/opt/mdi/backend`; Bulk Refresh Pending (`scope=pending`), shared pending-analysis helper, Pending Analysis filter; previous backend `f886ceb8` (MDI-57A) |
| VT Bulk backend | VTFIX-02F: `413d6334d816724b0476562cdbc4fdb894187221` | `/var/www/dns-tool/backend`; shared `vt_usage.json` flock read-modify-write restored |

MDI-57B (2026-07-09T02:41–02:42 UTC) deployed **full-stack** from `main` @
`d001df62bfe9ec0b272efc5a7a527ef83f363537` on host `srv766238`. Backend files
copied: `models.py`, `services/pending_analysis.py` (**new**),
`services/export_service.py`, `services/job_actions.py`, `routers/mdi.py`;
`build_info.json` updated; `mdi-backend.service` **restarted** and **active**
at 2026-07-09T02:42:04 UTC; frontend built and rsynced (`rsync -av --delete`)
to `/var/www/html/tools/mdi/`; old bundle `index-BlibenHD.js` **removed**;
nginx **not** reloaded; VT Bulk Check **untouched**. Backups: backend
`/root/backups/mdi-57b-pre-deploy-backend-20260709T024112Z/`, frontend
`/root/backups/mdi-57b-pre-deploy-frontend-20260709T024112Z/`. Previous
production: backend `f886ceb8` (MDI-57A), frontend `index-BlibenHD.js` /
`index-BQreofYY.css`.

MDI-57B extends existing `POST /api/mdi/jobs/{job_id}/refresh` with
`scope="pending"` so operators can bulk-refresh all pending-analysis URL rows
(1 VT lookup each, GET-only `refresh_report()`, no URL submit, no Request New
Scan). UI adds **Refresh Pending (N)** bulk control and a **Pending Analysis**
filter card. Live Refresh Pending smoke was **not** run — quota approval
pending.

MDI-57A (2026-07-09T00:45–00:47 UTC) deployed **full-stack** from `main` @
`f886ceb8c2900e4999329260c99868fd5ab9fd72` on host `srv766238`. Backend files
copied: `services/vt_service.py`, `services/triage_rules.py`,
`services/job_processor.py`, `services/estimate.py`,
`services/job_persistence.py`, `services/job_store.py`,
`services/export_service.py`, `models.py`, `routers/mdi.py`;
`build_info.json` updated; `mdi-backend.service` **restarted** and **active**;
frontend built and rsynced (`rsync -av --delete`) to `/var/www/html/tools/mdi/`;
old bundle `index-DRQeaMJN.js` **removed**; nginx **not** reloaded; VT Bulk
Check **untouched**. Backups: backend
`/root/backups/mdi-57a-pre-deploy-backend-20260709T004552Z/`, frontend
`/root/backups/mdi-57a-pre-deploy-frontend-20260709T004552Z/`. Previous
production: backend `32148c1` (MDI-59A), frontend `index-DRQeaMJN.js` /
`index-BQreofYY.css`.

MDI-57A changes initial URL-mode VirusTotal behavior to submit-only pending
analysis: new unknown URLs use GET + POST submit (2 calls), then stop — no
immediate re-fetch; cached URL reports remain 1 call; URL estimate max changes
3 → 2; stale threshold default 7 → 30 days; very-stale boundary becomes
`max(2 * stale_threshold_days, 30)`; pending rows show `Pending VT analysis`
(not `0/0`), triage_bucket `pending`, recommended_action `refresh_report`,
evidence_status `partial`, freshness `never_scanned`; pending export rows use
`pending_analysis` field; 404 and empty/zero-stat reports are not treated as
clean.

MDI-59A (2026-07-02 04:03 UTC) deployed **backend-only** from `main` @ `32148c1`
on host `srv766238`. Backend files copied: `services/job_actions.py`,
`services/job_persistence.py`; `build_info.json` updated; `mdi-backend.service`
**restarted**; frontend **not** redeployed; nginx **not** reloaded. Backup:
`/opt/mdi/backups/mdi59a-20260702-040308/`. Previous production backend:
`1073bff` (MDI-54B). Fixes stale `action_in_progress=true` on completed recovered
jobs blocking Start New Scan; recovery sanitization clears terminal stale flags on
API read; future refresh/scan actions persist cleared flag after completion.

MDI-54B (2026-06-25 ~03:22–03:23 UTC) deployed **full-stack** from `main` @ `1073bff`
on host `srv766238`. Backend files copied: `models.py`, `routers/mdi.py`,
`services/export_service.py`; `build_info.json` updated; `mdi-backend.service`
**restarted**; frontend built and rsynced to `/var/www/html/tools/mdi/`; nginx
**not** reloaded; **no package install** (`openpyxl 3.1.5` already present).
Backups: `/opt/mdi/backups/mdi54b-20260625-032222/backend/`,
`/var/www/html/tools/mdi.bak-20260625-032222/`. Previous production: backend
`ca5aa9b`, frontend `index-UlaSQnOO.js` / `index-CG0zkzGS.css`.

Bulk exports now support **CSV (default)** or **XLSX** via a single format selector;
JSON evidence export schema (`mdi-evidence-v1`) remains unchanged.

Prior deploy notes (MDI-54A backend-only, MDI-49, VTFIX-02G/02I) remain in section
5 smoke history below.

## 3. Stabilization Sequence

| Ticket | Outcome |
|---|---|
| MDI-30A | CSV/XLSX upload workflow accepted |
| MDI-30B | Settings cleanup accepted |
| MDI-30C | Row More Actions accepted |
| MDI-31 | Build review / reconciliation completed |
| MDI-32 | Documentation reconciliation merged |
| MDI-33 | Row menu click-target fix accepted |
| MDI-34 | Open in VirusTotal support accepted |
| MDI-35 | Post-results layout cleanup and UTC quota labels accepted |
| MDI-36 | Dashboard overlay / narrow viewport cleanup accepted |
| MDI-37 | Good-enough checkpoint completed |
| MDI-38 | Results mode, Start New Scan, centered filters, and calculated Age column accepted |

### Post-release defect series (frontend-only)

| Ticket | Outcome |
|---|---|
| MDI-40A | Cleared completed action status banner accepted |
| MDI-40B | Detail drawer calculated age parity accepted |
| MDI-40C | Enrichment evidence copy clarity accepted |
| MDI-41 | Row More Actions popover clipping/scrollbar fix accepted |
| MDI-44 | Dashboard average runtime formatting fix accepted |
| MDI-45 | Setup detail rail cleanup accepted and deployed |
| MDI-46 | Input page layout cohesion pass accepted and deployed |
| MDI-47 | Type floor / readability pass accepted and deployed |
| MDI-48 | Input workflow guidance and placeholder clarity accepted and deployed |

### MDI-57A VT quota optimization / pending URL state

| Ticket | Outcome |
|---|---|
| MDI-57A | Submit-only pending URL state, VT response-shape verification, 30-day stale default — **merged, full-stack deployed, production-verified, smoke-accepted, closed** |
| MDI-57B | Bulk Refresh Pending (`scope=pending`), Pending Analysis filter — **merged, full-stack deployed, safe-verified, closed** (live Refresh Pending smoke pending explicit quota approval) |
| MDI-61 | Date-drift test fix for `test_age_bucket_very_new` — **merged, test-only, no deploy required, closed** |

MDI-57A commit on `main`: `f886ceb8` (fix url pending analysis quota behavior).

MDI-57B commit on `main`: `d001df6` (add bulk refresh pending action).

MDI-61 commit on `main`: `3818b13` (fix age bucket date drift test).

MDI-59 (progress-phase UX) remains a separate future backlog item — not started.

### MDI export contract series (MDI-54)

| Ticket | Outcome |
|---|---|
| MDI-54A | Lean 10-column CSV export contract — **merged, backend-deployed, production-smoked, accepted** |
| MDI-54B | XLSX export with result-based row coloring — **merged, full-stack deployed, production-smoked, accepted** |
| MDI-59A | Stale `action_in_progress` persistence/recovery fix — **merged, backend-deployed, production-verified, accepted** (operator Start New Scan visual confirmation pending) |

MDI-54A commits on `main`: `b1f9fa6` (fix mdi csv export contract),
`ca5aa9b` (docs: update mdi csv export contract).

MDI-54B commit on `main`: `1073bff` (add mdi xlsx export).

MDI-59A commit on `main`: `32148c1` (fix mdi action flag persistence).

**Release-note context (MDI-54A):** default MDI CSV export is a **breaking** 10-column
analyst contract versus the legacy wide ~39-column CSV.

**Current export paths (MDI-54B):**

- **CSV** — default bulk format; same 10-column contract; `detection_ratio` tab-prefixed in raw CSV
- **XLSX** — optional bulk format; same 10 columns; result-based row coloring; plain-text ratio cells
- **JSON evidence** — full forensic fields (`mdi-evidence-v1`); unchanged

Consumers needing legacy wide spreadsheet fields should use **JSON evidence export**
for full forensic review. XLSX provides the analyst 10-column view with coloring,
not the legacy wide field set.

Exact production analyst export header (CSV and XLSX):

`input,checked_as,result,registrar,hold_status,domain_created,cloudflare_rank,detection_ratio,last_scanned,error`

### VTFIX-02 shared VT quota / dashboard attribution series

| Ticket | Outcome |
|---|---|
| VTFIX-02A | Discovery — architecture and schema mismatch report |
| VTFIX-02E | `vt_usage_history.jsonl` permission hardening — merged, deployed (docs/script) |
| VTFIX-02B | VT Bulk Check JSONL contract (`tool_name`, `timestamp`, `quota_units_consumed`) — deployed to VT Bulk backend |
| VTFIX-02C | MDI dashboard shared attribution, metric ownership, and horizontal card layout — **merged, deployed, operator-smoked, visually confirmed** |
| VTFIX-02D | Unified daily-history schema v2 (`tools.mdi`, `tools.vt_bulk_check`) — **merged, deployed, production-smoked** |
| VTFIX-02F | Shared live `vt_usage.json` flock coordination (VT Bulk regression fix) — **merged, deployed, production-smoked** |
| VTFIX-02G | Dashboard attribution visibility, live quota cards, 7-day per-tool quota trend — **merged, deployed, API-verified, visually confirmed** |
| VTFIX-02H | Historical daily-history metadata backfill dry-run tooling — **merged, dry-run complete** |
| VTFIX-02H-RUNTIME | Approved high-confidence daily-history schema v2 normalization on disk — **completed, verified** |
| VTFIX-02I | Dashboard 7-day quota trend table column alignment — **merged, deployed, visually confirmed** |

VTFIX-02C commits on `main`: `6ff4811` (source attribution), `a328649` (metric
ownership, backend), `fbef931` (dashboard card layout, frontend).

VTFIX-02D commits on `main`: MDI `cf3c5ec`, VT Bulk `9f18607`.

VTFIX-02F commits on `main`: MDI `92d7086` (tests/docs), VT Bulk `413d633` (fix).

VTFIX-02G commit on `main`: MDI `ea103fe` (dashboard VT attribution visibility).

VTFIX-02H commits on `main`: `a100be9` (dry-run script/tests/runbook),
`5591d5e` (approved write mode).

VTFIX-02I commit on `main`: `5b504e3` (dashboard 7-day quota trend table alignment).

### MDI-FABLE-01 external UI/UX review intake

An external UI/UX review (MDI-FABLE-01) of the stable app reopened **targeted**
UI refinement. Key conclusions carried forward:

- The always-rendered empty setup-mode detail rail was identified as the safest
  first correction (addressed by MDI-45).
- Setup-mode stretch above ~1600px was addressed by MDI-46 (centered workbench).
- The small type floor (9–10px labels) was addressed by MDI-47 (readability pass).
- Misleading setup placeholder copy and missing workflow guidance were addressed
  by MDI-48 (input workflow guidance and placeholder clarity).
- A broad redesign is **not justified** at this time; results mode is stable and
  should not be disturbed.

This review is the evidence basis for the scoped UI refinement path below. It
does not reopen unrestricted UI work.

## 4. Current Capabilities

MDI currently supports:

- paste domain/URL input
- CSV/XLSX upload with header-row detection
- upload preview / validation
- quota/runtime estimate
- explicit **Run MDI Check**
- VirusTotal checks for eligible items
- shared VT quota tracking
- domain hold detection
- held-domain VT/live skip
- RDAP/WHOIS enrichment
- live checks for eligible flagged items
- triage buckets
- recommended actions
- confidence/evidence status
- priority results table
- calculated domain Age column with age bucket context
- detail drawer with engine-level VT evidence
- Row More Actions
- Open in VirusTotal
- Refresh Report
- Request New Scan
- pending-analysis URL state (MDI-57A): new unknown URLs are submit-only (2 VT calls); pending rows show `Pending VT analysis`, `Refresh Report` recommended action, and partial evidence — not `0/0` or clean; `pending_analysis` export field
- Bulk Refresh Pending (MDI-57B): `scope=pending` on existing refresh endpoint; **Refresh Pending (N)** bulk control; 1 VT lookup per pending URL; GET-only; no URL submit / no Request New Scan
- Pending Analysis filter card (MDI-57B)
- bulk actions
- CSV export (10-column analyst contract; MDI-54A; default bulk format) and XLSX export (same contract with result-based row coloring; MDI-54B) via bulk Format selector; JSON evidence export (full forensic fields; unchanged schema)
- operational dashboard (metadata-only) with source filter: **MDI**, **All VT Tools**, **VT Bulk Check**
- dashboard metric ownership: shared VT operational metrics vs MDI-only triage/enrichment
- Run Options and Advanced Settings
- latest job recovery
- results mode
- Start New Scan

## 5. Final Acceptance Matrix

### Backend Test History

Do not read this section as tests run during MDI-39. It summarizes prior
stabilization evidence.

| Area | Evidence |
|---|---|
| Full backend suite | Prior full suite reported `812 passed` |
| Upload workflow | MDI-30A upload parser/workflow tests |
| Open in VT | MDI-34 `vt_gui_url` tests |
| Quota safety | quota lock / usage tests |
| Persistence | job persistence and recovery tests |
| Exports | export tests |
| Dashboard | dashboard tests |
| Error handling | error taxonomy tests |

### Frontend Build History

`npm run build` passed during the relevant frontend tickets including MDI-30B,
MDI-30C, MDI-33, MDI-35, MDI-36, and MDI-38.

### Production Smoke History

| Area | Status |
|---|---|
| MDI-30A upload acceptance | Accepted |
| MDI-30C row actions | Accepted |
| MDI-30B Settings labels | Accepted |
| MDI-33 row menu click target | Accepted |
| MDI-34 Open in VT | Accepted |
| MDI-35 results-first layout and UTC quota labels | Accepted |
| MDI-36 dashboard overlay | Accepted |
| MDI-38 results mode / Start New Scan / Age column | Accepted |
| MDI-40A action status banner | Accepted |
| MDI-40B detail drawer calculated age | Accepted |
| MDI-40C enrichment evidence copy | Accepted |
| MDI-41 row More Actions popover | Accepted |
| MDI-45 setup detail rail cleanup | Accepted |
| MDI-46 input page layout cohesion | Accepted |
| MDI-47 type floor / readability pass | Accepted |
| MDI-48 input workflow guidance and placeholder clarity | Accepted |
| VTFIX-02C dashboard source attribution | Accepted |
| VTFIX-02C dashboard metric ownership | Accepted |
| VTFIX-02C dashboard horizontal card layout | Accepted |
| VTFIX-02D unified daily-history schema v2 | Accepted |
| VTFIX-02F shared live counter coordination | Accepted |
| VTFIX-02G dashboard live quota cards and per-tool quota trend | Accepted |
| VTFIX-02G dashboard source banner and helper text | Accepted |
| VTFIX-02G VT Bulk Check MDI triage Not Applicable messaging | Accepted |
| VTFIX-02H daily-history backfill dry-run tooling | Accepted |
| VTFIX-02H-RUNTIME approved daily-history schema normalization | Accepted |
| VTFIX-02I dashboard quota trend table column alignment | Accepted |
| MDI-54A 10-column CSV export contract | Accepted |
| MDI-54B XLSX export with result-based row coloring | Accepted |
| MDI-59A stale action flag persistence/recovery fix | Accepted (API-verified; operator Start New Scan visual confirmation pending) |
| MDI-57A submit-only pending URL state, 30-day stale default, pending-analysis triage + export, updated estimate model | Accepted — full-stack deployed, production-verified, operator smoke-accepted |
| MDI-57B Bulk Refresh Pending (`scope=pending`), Pending Analysis filter | Accepted — full-stack deployed, safe API/static verified; **live Refresh Pending smoke not run — quota approval pending** |

**MDI-57B production deploy and safe verification (2026-07-09T02:41–02:42 UTC):**

Full-stack deploy on `srv766238`: backend `d001df6` → `/opt/mdi/backend` (from
`f886ceb8` / MDI-57A); frontend `index-p3SY0k4J.js` / `index-BQreofYY.css` via
`rsync -av --delete` from `/root/mdi/frontend/dist/` to
`/var/www/html/tools/mdi/`; old bundle `index-BlibenHD.js` removed. Backend
files copied: `models.py`, `services/pending_analysis.py` (**new**),
`services/export_service.py`, `services/job_actions.py`, `routers/mdi.py`;
`build_info.json` updated; `mdi-backend.service` **restarted** and **active**
at 2026-07-09T02:42:04 UTC; nginx **not** reloaded; VT Bulk Check **untouched**.
Backups: `/root/backups/mdi-57b-pre-deploy-backend-20260709T024112Z/`
(`pending_analysis.py` was not present pre-deploy — recorded as new),
`/root/backups/mdi-57b-pre-deploy-frontend-20260709T024112Z/`.

Pre-deploy verification: focused backend tests **129 passed**; full backend
suite **1046 passed**; frontend build succeeded (`index-p3SY0k4J.js`).

Safe API verification (read-only): `/api/mdi/health` → 200, commit
`d001df62bfe9ec0b272efc5a7a527ef83f363537`; `/api/mdi/version` → 200, same
commit; `/api/mdi/usage` → 200, `daily_lookups_used=3`, `remaining=497`
(unchanged from pre-deploy); `/api/mdi/jobs/latest` → 200, `status=done`,
`action_in_progress=false`; OpenAPI `RefreshScanScope` includes `selected`,
`stale`, **`pending`**.

UI/static verification: production `index.html` references `index-p3SY0k4J.js`
and `index-BQreofYY.css`; JS bundle contains `Refresh Pending`,
`Pending Analysis`, `Refresh Pending VT Analysis`, `1 VT lookup per pending`,
`Confirm Refresh Pending`, `Refresh Pending in progress`, and no-new-scan
warning copy fragments; no progress-phase UI.

Behavior deployed: existing `POST /api/mdi/jobs/{job_id}/refresh` accepts
`scope="pending"`; selects all eligible pending-analysis URL rows; 1 VT lookup
per row; estimate blocks if quota would be exceeded; per-row quota guard during
async action; partial completion allowed; GET-only `refresh_report()`; no URL
submit; no Request New Scan; completed rows re-triage normally; still-pending
rows remain Pending VT analysis; refresh 404 does not auto-submit; Pending
Analysis filter card available; completion summary is client-derived and
advisory.

**Smoke status:** quota-approved live Refresh Pending smoke was **not** run
(no explicit quota approval in the deployment prompt). No POST/job action was
performed during deploy. First real Refresh Pending on a pending row will be
the live functional verification.

Recommended smoke (when approved): prefer an existing production job with
exactly **1** pending URL row; estimate should show 1 VT lookup; expected usage
delta **+1**; verify no URL submit / no Request New Scan; verify
completed/still-pending/failed outcomes. Avoid creating a new unknown URL
unless separately approved (~2 calls to create pending + 1 to refresh).

Runtime/quota safety: all five runtime files identical size/mtime before and
after deploy; usage remained **3/500**; no runtime JSON edit; no quota reset;
no external API calls; no VT quota consumed by deploy; VT Bulk Check untouched.

Rollback (documented; not executed): restore from
`/root/backups/mdi-57b-pre-deploy-backend-20260709T024112Z/`; remove new
`/opt/mdi/backend/services/pending_analysis.py`; restore frontend from
`/root/backups/mdi-57b-pre-deploy-frontend-20260709T024112Z/`; restart
`mdi-backend.service`; verify `/api/mdi/version` returns `f886ceb8`.

**MDI-57A production deploy and smoke acceptance (2026-07-09T00:45–00:47 UTC):**

Full-stack deploy on `srv766238`: backend `f886ceb8` → `/opt/mdi/backend` (from
`32148c1` / MDI-59A); frontend `index-BlibenHD.js` / `index-BQreofYY.css` via
`rsync -av --delete` from `/root/mdi/frontend/dist/` to
`/var/www/html/tools/mdi/`; old bundle `index-DRQeaMJN.js` removed. Backend
files copied: `services/vt_service.py`, `services/triage_rules.py`,
`services/job_processor.py`, `services/estimate.py`,
`services/job_persistence.py`, `services/job_store.py`,
`services/export_service.py`, `models.py`, `routers/mdi.py`;
`build_info.json` updated; `mdi-backend.service` **restarted** and **active**;
`daemon-reload` executed (unit-file change warning cleared); nginx **not**
reloaded; VT Bulk Check **untouched**. Backups:
`/root/backups/mdi-57a-pre-deploy-backend-20260709T004552Z/` (10 files),
`/root/backups/mdi-57a-pre-deploy-frontend-20260709T004552Z/`.

Safe API verification (read-only): `/api/mdi/health` → 200, commit
`f886ceb8c2900e4999329260c99868fd5ab9fd72`; `/api/mdi/version` → 200, same
commit; `/api/mdi/usage` → 200, `daily_lookups_used=0`, `remaining=500`
(unchanged from pre-deploy); `/api/mdi/jobs/latest` → 200, `status=done`, no
recovered-job regression; `/api/mdi/schema-summary` → `STALE_THRESHOLD_DAYS: 30`
confirmed. Production `index.html` references `index-BlibenHD.js` and
`index-BQreofYY.css`; JS bundle confirmed to contain `isPendingAnalysis` and
`stale_threshold_days:30`; no Refresh Pending bulk button; no progress-phase UI.

Focused backend pre-deploy tests: **393 passed, 0 failed**
(`test_vt_service.py`, `test_estimate.py`, `test_jobs_submit.py`,
`test_triage_rules.py`, `test_export.py`, `test_job_persistence.py`,
`test_mdi57a_submit_only_pending.py`). Frontend build: 31 modules, no generated
artifacts committed.

Smoke acceptance: operator (Steven) reported all MDI-57A smoke tests passed
after deployment. Detailed per-step smoke artifacts were not added to docs
beyond operator acceptance. Live pending-analysis workflow verification gap is
closed by operator acceptance. Any quota consumed during smoke was
operator-approved and expected.

Runtime/quota safety: all five runtime files (`mdi_latest_job.json`,
`vt_usage.json`, `vt_usage_history.jsonl`, `vt_daily_history.json`,
`vt_usage.lock`) had identical sizes and mtimes before and after deployment.
No runtime JSON edit; no quota reset; no external API calls; no VT quota
consumed during deploy; no MDI jobs submitted during deploy; VT Bulk Check
untouched.

Rollback (documented; not executed): restore from
`/root/backups/mdi-57a-pre-deploy-backend-20260709T004552Z/` (nine service/model/router files + `build_info.json`) to
`/opt/mdi/backend/`; restore from
`/root/backups/mdi-57a-pre-deploy-frontend-20260709T004552Z/` to
`/var/www/html/tools/mdi/`; restart `mdi-backend.service`; verify
`/api/mdi/version` returns `32148c1`.

**MDI-59A production deploy and stuck-action unblock (2026-07-02 04:03 UTC):**

Backend-only deploy on `srv766238`: backend `32148c1` → `/opt/mdi/backend` (from
`1073bff` / MDI-54B). Frontend unchanged: `index-DRQeaMJN.js` /
`index-BQreofYY.css`. Backend files copied: `services/job_actions.py`,
`services/job_persistence.py`; `build_info.json` updated; `mdi-backend.service`
**restarted** and **active**; nginx **not** reloaded; frontend **not** redeployed.
Backup: `/opt/mdi/backups/mdi59a-20260702-040308/`.

Safe API verification (read-only): `/api/mdi/health`, `/api/mdi/version`,
`/api/mdi/usage`, `/api/mdi/jobs/latest` → 200; `/api/mdi/health` and
`/api/mdi/version` commit `32148c102639cbb9adcf84646c80039d8b9b0617`;
`/api/mdi/usage` `daily_lookups_used=0`, `remaining=500` (unchanged).

Stuck recovered job unblock (recovered job `2aac9b0b-88c2-4f7a-81d0-f86e50e589d3`;
no new scan; no MDI job submit; no POST actions): **PASS** via API — `/api/mdi/jobs/latest`
returned `status=done`, `action_in_progress=false`, `last_action_type=refresh`.
Backend log confirmed recovery sanitization (not runtime edit):
`sanitize_terminal_action_state: clearing stale action_in_progress for terminal job 2aac9b0b-88c2-4f7a-81d0-f86e50e589d3 (status=done)`.

UI verification: production UI loads (`https://forgeforward.app/tools/mdi/` → 200;
same bundle hashes). Start New Scan enablement inferred from API state matching
frontend gating (`status=done`, `action_in_progress=false`). **Pending operator
visual confirmation** that Start New Scan is enabled and blocked copy is gone;
no scan was submitted during deploy or docs closure.

Runtime/quota safety: metadata unchanged before/after deploy for
`mdi_latest_job.json`, `vt_usage.json`, `vt_usage.lock`, `vt_usage_history.jsonl`,
`vt_daily_history.json`. No runtime JSON edit; no quota reset; no external API
calls; no VT quota consumed; no MDI jobs submitted; VT Bulk Check untouched.

**Accepted known limitation:** disk/API divergence — on-disk
`/var/lib/dns-tool/mdi_latest_job.json` still has stale `action_in_progress=true`
while API returns `action_in_progress=false` through recovery sanitization. This
is acceptable for operator unblock after deploy. Optional separate runtime cleanup
ticket may align disk/API state if desired. Next refresh/scan action should persist
`action_in_progress=false` to disk.

Rollback (documented; not executed): restore from
`/opt/mdi/backups/mdi59a-20260702-040308/` (`job_actions.py`, `job_persistence.py`,
`build_info.json`) and restart `mdi-backend.service`.

**MDI-54B production deploy and export smoke (2026-06-25 ~03:22–03:23 UTC):**

Full-stack deploy on `srv766238`: backend `1073bff` → `/opt/mdi/backend` (from
`ca5aa9b` / MDI-54A); frontend `index-DRQeaMJN.js` / `index-BQreofYY.css` via
`rsync -a --delete` from `/root/mdi/frontend/dist/` to `/var/www/html/tools/mdi/`.
Backend files copied: `models.py`, `routers/mdi.py`, `services/export_service.py`;
`build_info.json` updated; `mdi-backend.service` **restarted**; nginx **not**
reloaded; **no package install** (`openpyxl 3.1.5` already present). Backups:
`/opt/mdi/backups/mdi54b-20260625-032222/backend/`,
`/var/www/html/tools/mdi.bak-20260625-032222/`.

Safe API verification (read-only): `/api/mdi/health`, `/api/mdi/version`,
`/api/mdi/usage`, `/api/mdi/schema-summary`, `/api/mdi/jobs/latest` → 200;
`/api/mdi/version` commit `1073bff456d551d97f63a99826748b35db35e617`.

Export smoke (recovered saved job `8b31c76e-a4f5-4082-b153-ccfc349b3760`; no new
scan; no MDI job submit): **PASS** for CSV and XLSX Export All, Export Flagged,
and Export Selected. Exact header (CSV and XLSX):

`input,checked_as,result,registrar,hold_status,domain_created,cloudflare_rank,detection_ratio,last_scanned,error`

Sample row checks on saved production data:

- `checked_as`: `url_report:http://truereligionus.us/` (actual lookup method/target)
- `cloudflare_rank`: `>200000 / UNRANKED` (popularity bucket display)
- CSV `detection_ratio`: raw cell tab-prefixed (`\t1/92`); displays as `1/92` in spreadsheets
- XLSX `detection_ratio`: plain text `1/92`, cell format `@`, no tab prefix
- XLSX formatting: header bold; freeze `A2`; autofilter `A1:J2`
- XLSX row coloring: `flagged` fill `FFFDE8E8`; `result` text present in cell
- JSON evidence export: unchanged — `schema_version: mdi-evidence-v1`; 46 fields;
  `vt_targeted_brand` preserved

Frontend verification: format selector visible in deployed bundle (`index-DRQeaMJN.js`);
default **CSV**; options CSV / XLSX; three bulk buttons preserved (Export Flagged,
Export All, Export Selected); no modal/popup; row JSON evidence remains JSON-only.

No runtime/quota file changes; VT daily usage remained **244**; no external API
calls; no VT quota consumed; no MDI jobs submitted; VT Bulk Check untouched.

**Non-blocking smoke note:** production export smoke used one flagged saved row;
`clean` / `on_hold` / `error` / `unknown` XLSX fills were not re-smoked because
no safe saved job exposed those rows. Do not create live jobs to manufacture them.

**MDI-54A production deploy and export smoke (2026-06-25 02:29 UTC):**

Backend-only deploy: `ca5aa9b` → `/opt/mdi/backend` (from `b1a9650` / MDI-49).
Files copied: `export_service.py`, `vt_gui_url.py`; `build_info.json` updated.
`mdi-backend.service` **restarted**; nginx **not** reloaded; frontend **not**
redeployed (bundle remains `index-UlaSQnOO.js`). Backup:
`/opt/mdi/backups/mdi54a-20260625-022850/backend/`.

Safe API verification (read-only): `/api/mdi/health`, `/api/mdi/version`,
`/api/mdi/usage`, `/api/mdi/schema-summary`, `/api/mdi/jobs/latest` → 200;
`/api/mdi/version` commit `ca5aa9b6b45d3b65871632eee8b5a72afd5eeb33`.

Export smoke (recovered saved job `8b31c76e-a4f5-4082-b153-ccfc349b3760`; no new
scan; no MDI job submit): **PASS** for Export All, Export Flagged, and Export
Selected. All three scopes returned the exact 10-column header:

`input,checked_as,result,registrar,hold_status,domain_created,cloudflare_rank,detection_ratio,last_scanned,error`

Sample row checks on saved production data:

- `checked_as`: `url_report:http://truereligionus.us/` (actual lookup method/target)
- `cloudflare_rank`: `>200000 / UNRANKED` (popularity bucket display)
- `detection_ratio`: raw cell tab-prefixed (`\t1/92`); displays as `1/92` in spreadsheets
- JSON evidence export: unchanged — `schema_version: mdi-evidence-v1`; full forensic
  fields preserved (e.g. `vt_targeted_brand`, `vt_redirection_chain`)

No runtime/quota file changes; no external API calls; no VT quota consumed; no MDI
jobs submitted.

**VTFIX-02I production deploy and visual smoke (2026-06-12 01:18 UTC):** via
`rsync -a --delete`. No backend deploy; no VT Bulk deploy; `mdi-backend.service`
**not** restarted; nginx **not** reloaded. Backup:
`/var/www/html/tools/mdi.bak-20260612-011810/`. Bundles before:
`index-UBWBOg5l.js`, `index-BoqbTN7t.css`. Bundles after:
`index-9Cqf9ev9.js`, `index-DseIq5wp.css`.

Root cause: numeric trend table headers were right-aligned while body cells for
Total/MDI/VT Bulk were left-aligned (only Legacy used right-align via generic
`.dashboard-table td:last-child`), producing a phantom-column appearance after
VTFIX-02H-RUNTIME on-disk normalization exposed all five per-tool columns.

Fix: always render five columns (Date, Total, MDI, VT Bulk, Legacy); use
`table-layout: fixed` with shared `<colgroup>`; right-align all numeric header
and body cells consistently.

Production visual confirmation (read-only, headless Playwright with screenshots):
**PASS** at `https://forgeforward.app/tools/mdi/` on 1280×800 and 1920×1080 for
source tabs MDI / All VT Tools / VT Bulk Check. Five headers and five body
columns per row; header/body column boxes align; numeric columns right-aligned; no
phantom/unlabeled column; today row highlight preserved (`2026-06-12 (today)`);
live quota cards visible; source-tab switching does not break layout; console
errors none; no job/scan POSTs; no VT calls; quota unchanged (0/500); runtime
metadata unchanged.

Evidence:
`/tmp/vtfix-02i-prod-smoke/1280x800-mdi.png`,
`/tmp/vtfix-02i-prod-smoke/1280x800-all.png`,
`/tmp/vtfix-02i-prod-smoke/1280x800-vt-bulk.png`,
`/tmp/vtfix-02i-prod-smoke/1920x1080-mdi.png`,
`/tmp/vtfix-02i-prod-smoke/1920x1080-all.png`,
`/tmp/vtfix-02i-prod-smoke/1920x1080-vt-bulk.png`.

**VTFIX-02H-RUNTIME approved normalization (2026-06-11 22:11 UTC):**

Operator-approved runtime write to `/var/lib/dns-tool/vt_daily_history.json` only.
Script: `scripts/vtfix-02h-daily-history-backfill-dry-run.py`
(`--write-approved-normalization`). Tooling on `main` at `5591d5e`. Backup:
`/var/lib/dns-tool/backups/vtfix-02h-runtime-20260611-221110/vt_daily_history.json`.
No deploy; no service restart/reload; `vt_usage.json` and
`vt_usage_history.jsonl` **not** modified.

Five high-confidence dates normalized to schema v2 on disk (totals preserved):

| Date | Before | After | Total | MDI | VT Bulk | Legacy |
|---|---|---|---:|---:|---:|---:|
| 2026-06-05 | legacy_int | v2 | 1 | 0 | 0 | 1 |
| 2026-06-06 | legacy_dict (`tool=mdi`) | v2 | 1478 | 1478 | 0 | 0 |
| 2026-06-08 | legacy_dict (`tool=mdi`) | v2 | 89 | 89 | 0 | 0 |
| 2026-06-09 | legacy_dict (`tool=mdi`) | v2 | 4 | 4 | 0 | 0 |
| 2026-06-10 | legacy_int | v2 | 242 | 0 | 0 | 242 |

Preserved unchanged:

- Manual-review dates (not written): `2026-06-03` (legacy_int, total 138, JSONL
  sum 2); `2026-06-07` (legacy_int, total 5, JSONL sum 3).
- Existing v2 date: `2026-06-11` (total 4, MDI 2, VT Bulk 2, Legacy 0).

Post-write verification: all eight day totals preserved; post-write dry-run showed
zero high-confidence write candidates; `/api/mdi/dashboard?source=all` → 200;
`/api/mdi/usage` → 3 used / 497 remaining at verification time; no jobs; no VT
calls; no quota consumed by the backfill operation.

**VTFIX-02H dry-run tooling (2026-06-11):**

Dry-run script, tests, and runbook merged on `main` (`a100be9`, then write mode
`5591d5e`). See [VTFIX-02H runbook](runbooks/vtfix-02h-backfill-dry-run.md).
Dry-run identified five high-confidence schema-normalization candidates and two
manual-review dates. Runtime write executed only after explicit operator approval
(VTFIX-02H-RUNTIME).

**VTFIX-02G production deploy and visual smoke (2026-06-11 09:04 UTC):**

Coordinated MDI deploy: `ea103fe` → `/opt/mdi/backend` and `/var/www/html/tools/mdi/`.
`mdi-backend.service` restarted. VT Bulk backend **not** redeployed; nginx **not**
reloaded. Backups: `/opt/mdi/backups/vtfix-02g-20260611-090410/`,
`/var/www/html/tools/mdi.bak-20260611-090410/`. Bundles after deploy:
`index-UBWBOg5l.js`, `index-BoqbTN7t.css`.

Safe API verification (read-only): `/api/mdi/health` and `/api/mdi/version` → 200,
commit `ea103fe06129`; `/api/mdi/dashboard?source=mdi|all|vt_bulk_check` → 200;
`/api/mdi/usage` → used 3, remaining 497; `live_quota` present; per-tool quota
trend fields present (`mdi_quota_units`, `vt_bulk_check_quota_units`,
`legacy_quota_units`, `schema_version`). Today row (2026-06-11): Total 4, MDI 2,
VT Bulk 2, Legacy 0.

Production visual confirmation (read-only, headless Playwright with screenshots):
**PASS** at `https://forgeforward.app/tools/mdi/` on 1280×800 and 1920×1080.
Source tabs MDI / All VT Tools / VT Bulk Check visible and selectable; source
banner `Viewing: {source} · {window}` confirmed; source helper text confirmed
for all three filters; usage attribution line `MDI 2 · VT Bulk 2 · Legacy /
Unattributed 5` visible; live quota cards (Live used today 3, Remaining 497,
Daily limit 500); 7-day daily-history trend table with columns Date (UTC), Total,
MDI, VT Bulk, Legacy; today row highlighted `2026-06-11 (today)`; shared VT
metrics and MDI triage/enrichment cards preserve horizontal 7-card layout; VT
Bulk Check tab shows structured **Not Applicable** message for MDI
triage/enrichment; no misleading unavailable zeros; no clipping/overlap in
screenshots; panel scroll at 1280×800 content-driven and acceptable; console
errors none; no job/scan POSTs; no VT calls; quota unchanged (3/497); runtime
metadata unchanged.

Evidence:
`/tmp/vtfix-02g-visual-smoke/1280x800-mdi.png`,
`/tmp/vtfix-02g-visual-smoke/1280x800-all.png`,
`/tmp/vtfix-02g-visual-smoke/1280x800-vt-bulk.png`,
`/tmp/vtfix-02g-visual-smoke/1920x1080-mdi.png`,
`/tmp/vtfix-02g-visual-smoke/1920x1080-all.png`,
`/tmp/vtfix-02g-visual-smoke/1920x1080-vt-bulk.png`,
`/tmp/vtfix-02g-visual-smoke/1280x800-mdi-scrolled.png`.

Known remaining notes: at 1280×800, today row and lower metric sections require
panel scroll; verification used headless Playwright with screenshots (not a live
operator browser session); historical pre-v2 days may show 0 or blank where no
per-tool attribution existed.

**VTFIX-02D production deploy and smoke (2026-06-11):**

Coordinated backend deploy: MDI `cf3c5ec` → `/opt/mdi/backend`; VT Bulk `9f18607`
→ `/var/www/dns-tool/backend`. Both `mdi-backend.service` and
`dns-tool-backend.service` restarted. Backups:
`/opt/mdi/backups/vtfix-02d-20260611-075800/`,
`/var/www/dns-tool/backups/vtfix-02d-20260611-075800/`. No frontend deploy; no
nginx reload.

Minimal quota smoke (approved): one MDI job (`example.com`, domain reports) +
one VT Bulk job (`iana.org`, domain reports). Daily-history v2 verified:
`tools.mdi` and `tools.vt_bulk_check` coexisted; `total_quota_units` reached 2.
**Anomaly:** live `vt_usage.json` counter reported 1 while daily-history
reported 2 — not hand-edited; led to VTFIX-02F.

**VTFIX-02F production deploy and smoke (2026-06-11 08:43 UTC):**

VT Bulk deploy (`413d633`): `quota_lock.py` and `routers/vt_bulk_check.py` →
`/var/www/dns-tool/backend`; docs →
`/var/www/dns-tool/docs/deployment/vtfix-02f-shared-live-counter.md`.
`dns-tool-backend.service` restarted; `mdi-backend.service` **not** restarted.
Backup: `/var/www/dns-tool/backups/vtfix-02f-20260611-083713/`. No frontend
deploy; no nginx reload.

Minimal quota smoke (approved): MDI job `335be6ef-b732-4440-ada3-9ffff92edb79`
(`example.com`, done 1/1); VT Bulk job `d7ddcb99-69e4-41b6-845a-05855501fff8`
(`iana.org`, done 1/1). **PASS.** Live counter 1→3 (+2); both usage endpoints
agreed at 3. Daily-history `total_quota_units` 2→4 (+2);
`tools.mdi.quota_units` 1→2; `tools.vt_bulk_check.quota_units` 1→2. No
live-counter undercount; no daily-history overwrite. Forward writes after
VTFIX-02F behaved correctly.

**VTFIX-02C production deploy and smoke (2026-06-11):**

Backend deploy (`a328649`): `/opt/mdi/backend` files updated; `mdi-backend.service`
restarted. Backup: `/opt/mdi/backups/vtfix-02c-20260611-061442/`. Frontend at
that point: `index-BglVtk-f.js`, `index-5Tt7Lr8D.css`. Backup:
`/var/www/html/tools/mdi.bak-20260611-061442/`.

Operator source-attribution smoke (read-only): source tabs MDI / All VT Tools /
VT Bulk Check visible; MDI triage applicable under MDI; All VT Tools shows shared
metrics plus **MDI only** triage label; VT Bulk Check shows MDI triage **Not
Applicable** with no misleading Flagged/Clean/Held percentages. Evidence:
`/tmp/vtfix-02c-smoke/{mdi,all,vt_bulk_check,all-alltime}.png`.

UI layout revision (`fbef931`, frontend-only): no backend restart; no nginx
reload; no runtime file changes; no quota consumed. Backup:
`/var/www/html/tools/mdi.bak-20260611-065336/`. Bundles after deploy:
`index-QhEGJa8t.js`, `index-CZdxqujH.css`.

Layout production smoke (read-only): Shared VT metrics and MDI triage/enrichment
each display as organized **7-card horizontal rows** on desktop; no unnecessary
vertical scroll at 1280×800 or 1920×1080; source-tab regression passed; console
errors none; network safe GETs only; no job/scan POSTs; no VT calls. Evidence:
`/tmp/vtfix-02c-layout-prod-smoke/{1280x800,1920x1080}.png`.

**MDI-48 production smoke (2026-06-10):** frontend-only deploy from
`95f3e752d3135bcdd7c100ab50bf407555ff54bd`; no backend restart; no nginx
reload; no runtime file changes; no quota consumed (quota remained 2/500 used,
498 remaining). Backup: `/var/www/html/tools/mdi.bak-20260610-080836`. Read-only
smoke passed at 1280×720, 1366×768, 1440×900, 1600×1200, and 1920×1080.
Setup workflow guidance and four-step workflow strip visible in setup mode;
misleading “Results will appear here” placeholder copy removed; placeholder
accurately explains setup view switches to results workspace; Estimate helper
clarifies no VT quota consumed; Run helper clarifies triage may consume VT quota
for eligible domains/URLs. Guidance and placeholder absent in recovered/results
mode. Results/recovered mode, row selection/drawer, Row More Actions, Dashboard,
Advanced, and Start New Scan round-trip all passed. MDI-46 workbench remained
centered; MDI-47 readability preserved.

**MDI-47 production smoke (2026-06-10):** frontend-only deploy from
`9f2388c5c44bb4bdf75cf8726a691a9a3f5b7e5e`; no backend restart; no nginx
reload; no runtime file changes; no quota consumed (quota remained 2/500 used,
498 remaining). Backup: `/var/www/html/tools/mdi.bak-20260610-070939`. Read-only
smoke passed at 1280×720, 1366×768, 1440×900, 1600×1200, and 1920×1080.
MDI-46 workbench remained centered/capped; setup placeholder visible; detail rail
hidden in setup mode. Results/recovered mode, row selection/drawer, Row More
Actions, Dashboard, Advanced, and Start New Scan round-trip all passed.
Readability improved; 8px/9px eliminated; results table density preserved.

Recent frontend/read-only smokes consumed no quota and did not modify runtime
metadata. Production upload acceptance consumed expected quota only when an
operator explicitly ran the upload job.

## 6. Operator Workflow

1. Open `/tools/mdi/`.
2. Paste domains/URLs or upload a CSV/XLSX.
3. If uploading, click **Validate Upload** and review accepted/rejected/held items.
4. Click **Estimate Quota & Runtime**.
5. Review quota warnings and settings.
6. Click **Run MDI Check** only when ready.
7. Review triage cards.
8. Filter results.
9. Open the detail drawer for evidence.
10. Use Row More Actions when needed:
    - **Export evidence (JSON)**
    - **Open in VirusTotal**
    - **Refresh report**
    - **Request new scan**
11. Use bulk actions if needed.
12. Export results if needed.
13. Use **Start New Scan** to clear the displayed frontend results and return to
    input/setup mode.

Do not use Refresh Report, Request New Scan, or auto-rescan casually; they can
consume shared VT quota.

## 7. Quota-Safe Operating Rules

| Action | VT quota impact |
|---|---|
| Paste validation | None |
| Upload preview / validation | None |
| Estimate Quota & Runtime | None |
| Run MDI Check | Consumes quota for eligible items |
| Held-domain VT/live skip | No VT/live checks for held domains |
| Refresh Report | Consumes quota when confirmed |
| Request New Scan | Consumes quota when confirmed; often more than Refresh |
| Auto-rescan | OFF by default; quota-impacting when enabled |
| Open in VirusTotal | Opens public VT GUI; no VT API quota |
| Export actions | No VT quota; CSV (default) or XLSX bulk export — 10-column analyst contract (MDI-54A/54B); JSON evidence for full forensic fields |
| Dashboard | No VT quota; read-only; source filter does not consume quota |
| Start New Scan | No VT quota; clears displayed frontend results only |

Daily quota is UTC-based. A recovered job may show VT lookups from a previous UTC
day while the current **Used today (UTC)** counter remains separate.

## 8. Runtime and Data Handling

Runtime files are excluded from Git. Operators may inspect metadata such as
mtime, size, and line count, but must not print or paste runtime file contents.

Known runtime files:

- `vt_usage.json`
- `vt_usage_history.jsonl`
- `vt_daily_history.json`
- `mdi_latest_job.json`
- `vt_usage.lock`

Rules:

- Do not manually edit runtime files.
- Do not print runtime file contents.
- Latest job recovery uses the persisted MDI snapshot.
- Dashboard history is metadata-focused.
- Frontend-only deploys should not touch runtime files.
- Backend deploys must follow the production runbook and preserve runtime files.

See [Runtime Data](runtime-data.md) for the detailed inventory and side-effect
matrix.

## 9. Deployment and Rollback Handoff

Use the existing deployment docs:

- [Deployment Notes](deployment/deployment-notes.md)
- [Production Runbook](runbooks/mdi-production-runbook.md)

Minimum frontend-only deploy checklist:

1. Confirm source branch, commit, and clean working tree.
2. Record current frontend bundle hashes from `/tools/mdi/`.
3. Record backend `/api/mdi/version` and `/api/mdi/health`.
4. Record quota from `/api/mdi/usage`.
5. Record runtime metadata only (mtime/size/line count as applicable).
6. Build frontend with `npm run build`.
7. Back up `/var/www/html/tools/mdi/`.
8. `rsync -a --delete dist/ /var/www/html/tools/mdi/`.
9. Confirm new bundle hashes are served.
10. Run read-only production smoke unless quota-consuming acceptance is explicitly approved.
11. Re-check quota and runtime metadata.

Frontend-only deploys do not require backend restart or nginx reload when only
static files change. Roll back by rsyncing a prior `/var/www/html/tools/mdi.bak-*`
directory back to `/var/www/html/tools/mdi/`.

Old frontend backups accumulate. Prune only after an agreed stabilization window.

## 10. Known Limitations

| Limitation | Classification |
|---|---|
| Frontend/backend version split after frontend-only deploys | Acceptable |
| No persistent searchable historical domain database | Acceptable |
| Dashboard history is metadata-focused | Acceptable |
| Dashboard default source filter is **MDI**; operators must select **All VT Tools** to see shared VT Bulk usage | Acceptable — by design |
| VT Bulk Check **Current** window may reflect in-memory/recovered MDI job shared metrics while MDI triage is Not Applicable | Acceptable — known |
| Pre–VTFIX-02I: dashboard 7-day quota trend table header/body column misalignment | **Resolved** by VTFIX-02I (2026-06-12) |
| Pre–VTFIX-02H-RUNTIME: legacy daily-history shapes on disk for dates before v2 forward writes | **Partially resolved** — five approved dates normalized on disk (2026-06-11); two manual-review dates remain legacy_int |
| Pre–VTFIX-02F smoke: live `vt_usage.json` could undercount vs daily-history when VT Bulk regressed flock coordination | **Resolved** by VTFIX-02F — historical 1-vs-2 mismatch not hand-edited |
| No tagged `vt_bulk_check` history until VTFIX-02B-tagged jobs append records | Acceptable — legacy lines remain under All VT Tools / Legacy |
| Five legacy/unattributed JSONL lines (no `tool_name`) appear under **All VT Tools** only as Legacy / Unattributed | Acceptable |
| MDI triage percentages require MDI-tagged history with triage aggregate fields | Acceptable |
| Data-heavy dashboard breakdown tables may still add vertical scroll when present | Acceptable |
| Older dashboard records may lack full triage aggregates | Acceptable |
| Open in VirusTotal depends on saved `vt_report_url` | Acceptable |
| Refresh/Scan consume quota when confirmed | Acceptable |
| Auto-rescan is off by default but quota-impacting when enabled | Acceptable |
| Narrow/mobile use is not primary; desktop 1280+ smoke tested | Acceptable |
| RDAP/WHOIS/live-check failures may occur due to upstream variability | Acceptable |
| In-flight jobs across backend restart are limited; latest completed/error snapshot recovery is supported | Acceptable |
| Old frontend backups accumulate until operator cleanup | Housekeeping |
| Failed/error job edge cases were not fully production-smoked during final UI smoke | Future test |
| Current completed non-recovered job path was not live-smoked during MDI-38 because no live job was submitted | Future test |
| Legacy wide ~39-column CSV consumers | **Breaking change (MDI-54A)** — use JSON evidence for full forensic fields; XLSX provides the 10-column analyst view with row coloring (MDI-54B), not the legacy wide field set |
| MDI-54A/54B export smoke used single flagged saved row | Acceptable — contract verified on real production data; multi-row and non-flagged XLSX fills not re-smoked in production |
| XLSX bulk export built in memory | Acceptable — very large exports may be slower/heavier than CSV |
| XLSX result-based row fills | Acceptable — spreadsheet apps may render pastel fills slightly differently; `result` text remains the primary signal |
| Pre–MDI-59A: completed recovered job with stale `action_in_progress=true` blocked Start New Scan | **Resolved** by MDI-59A (2026-07-02) — API recovery sanitization; future actions persist cleared flag |
| Post–MDI-59A: disk `mdi_latest_job.json` may still show the stale `action_in_progress=true` while API returns `false` | Acceptable — operator unblock via API; optional runtime cleanup ticket for disk/API alignment; next refresh/scan should persist `false` to disk |
| Bulk Refresh Pending (MDI-57B) refreshes **all** pending rows only — no selected pending subset in v1 | Acceptable — by design for v1 |
| Bulk Refresh Pending uses batch-end persistence only (same as Rescan Stale) | Acceptable — crash mid-batch can lose in-loop updates; same pattern as existing actions |
| Mid-action progress for Refresh Pending is indeterminate | Acceptable — MDI-59 progress-phase UX remains future backlog |
| Client-derived Refresh Pending completion summary is advisory | Acceptable — may miscount rare failure shapes |
| Live Refresh Pending production smoke | **Pending** — explicit quota approval required; prefer 1 existing pending row (+1 VT call) |
| Pre-existing date-drift test: `test_upload_parser.py::TestUploadParserCSV::test_age_bucket_very_new` | **Resolved by MDI-61 (2026-07-09)** — fixture date `2026-05-30` aged out of VERY_NEW; test now rewrites date to yesterday in memory before parsing; no fixture CSV change; full backend suite green at 1021 passed |
| Progress-phase UX (MDI-59) — per-item progress indicators during job execution | **Future backlog** — not started; separate ticket required |
| Manual Request New Scan completedness check | **Future backlog** — not part of MDI-57A/57B scope |
| Pending URL rows require operator-initiated Refresh Report / Refresh Pending; no automatic promotion on job rerun | Acceptable — by design; prevents hidden quota consumption |
| Refresh 404 on pending URL does not auto-submit | Acceptable — by design |

## 11. Future Backlog / Non-Blocking Items

### Scoped UI refinement path (from MDI-FABLE-01)

| Ticket | Scope | Status |
|---|---|---|
| MDI-45 | Hide empty setup-mode detail rail; handoff UI-lock clarification | Accepted and deployed |
| MDI-46 | Input Page Layout Cohesion Pass — centered setup workbench (frontend-only; input/start screen layout only; not a broad redesign; no backend/quota/runtime/results-mode behavior change) | Accepted and deployed |
| MDI-47 | Type-floor/readability pass (raise 9px floor; CSS-only; no layout/behavior change) | Accepted and deployed (production frontend) |
| MDI-48 | Input workflow guidance and placeholder clarity (setup-only guidance strip, Estimate/Run helpers, accurate placeholder copy) | Accepted and deployed (production frontend) |
| MDI-43 | Registration-not-found future logic | Future backlog — not started |
| Broad redesign | Full layout/visual redesign | Rejected/deferred unless separately approved |

MDI-43 is **documented backlog only — not started**. MDI-48 is accepted and
deployed; it addressed only setup-mode workflow guidance, Estimate/Run helper
copy, and placeholder clarity (no backend/quota/runtime/results-mode behavior
change). MDI-47 addressed only typography/readability (type floor,
`--text-faint` brighten). MDI-45 addressed only the empty setup-mode detail
rail; MDI-46 addressed only setup-mode layout cohesion and subtle visual polish.

### VTFIX follow-on

| Ticket | Scope | Status |
|---|---|---|
| VTFIX-02D | Daily-history schema unification | **Closed** — merged, deployed, production-smoked (2026-06-11) |
| VTFIX-02F | Shared live `vt_usage.json` flock coordination | **Closed** — merged, deployed, production-smoked (2026-06-11) |
| VTFIX-02G | Dashboard attribution visibility, live quota cards, 7-day per-tool quota trend | **Closed** — merged, deployed, API-verified, visually confirmed (2026-06-11) |
| VTFIX-02H | Historical daily-history metadata backfill dry-run | **Closed** — merged on `main` (`a100be9`, `5591d5e`); see [runbook](runbooks/vtfix-02h-backfill-dry-run.md) |
| VTFIX-02H-RUNTIME | Approved high-confidence daily-history schema v2 normalization | **Closed** — production write completed and verified (2026-06-11 22:11 UTC) |
| VTFIX-02I | Dashboard 7-day quota trend table column alignment | **Closed** — merged, deployed, visually confirmed (2026-06-12) |

MDI-43 remains **documented backlog only — not started**.

Manual-review daily-history dates still open (not written): `2026-06-03` (total 138,
JSONL sum 2) and `2026-06-07` (total 5, JSONL sum 3). Further backfill requires
operator review and separate approval.

### MDI-54 export follow-on

| Ticket | Scope | Status |
|---|---|---|
| MDI-54A | Lean 10-column CSV export contract | **Closed** — merged, backend-deployed, production-smoked, accepted (2026-06-25) |
| MDI-54B | XLSX export with result-based row coloring | **Closed** — merged, full-stack deployed, production-smoked, accepted (2026-06-25) |

MDI-54 series complete. Legacy wide-CSV consumers should use **JSON evidence
export** for full forensic fields. Bulk CSV (default) and XLSX share the 10-column
analyst contract; XLSX adds result-based row coloring.

### MDI-59A action flag persistence follow-on

| Ticket | Scope | Status |
|---|---|---|
| MDI-59A | Stale `action_in_progress` persistence/recovery fix | **Closed** — merged, backend-deployed, production-verified, accepted (2026-07-02) |
| MDI-59A-RUNTIME (optional) | One-time disk alignment of `mdi_latest_job.json` `action_in_progress` for job `2aac9b0b-…` | **Optional backlog** — not required for operator unblock; backup + verify if pursued |

MDI-57 and other tickets remain separate; do not conflate with MDI-59A closure.

### MDI-57A VT quota optimization follow-on

| Ticket | Scope | Status |
|---|---|---|
| MDI-57A | Submit-only pending URL state, VT response-shape verification, 30-day stale default | **Closed** — merged, full-stack deployed, production-verified, smoke-accepted (2026-07-09) |
| MDI-57B | Bulk Refresh Pending (`scope=pending`), Pending Analysis filter | **Closed** — merged, full-stack deployed, safe-verified (2026-07-09); live Refresh Pending smoke pending explicit quota approval |
| MDI-59 | Progress-phase UX — per-item progress indicators during job execution | **Future backlog** — not started |
| MDI-61 | `test_upload_parser.py::TestUploadParserCSV::test_age_bucket_very_new` fixture date-drift fix | **Closed** — merged, test-only, no deployment required (2026-07-09) |

MDI-59 is **documented backlog only — not started**. Do not conflate with
MDI-57A/57B closure. Production is at MDI-57B `d001df6`.

### Other non-blocking items

- Add quota-cost hint parity for Request New Scan tooltip.
- Add backup-pruning routine or runbook note.
- ~~Surface dashboard quota trends if still desired.~~ Addressed by VTFIX-02G.
- Add searchable historical job/domain history if approved.
- Add additional export scopes if needed.
- Add more complete automated frontend tests if the project expands.
- Smoke failed/error job UI when a safe fixture/state is available.

## 12. Change Control

MDI UI/workflow is at a good-enough **stable checkpoint** for internal use — a
checkpoint, not a permanent design freeze. Future UI-only changes should proceed
only when they address a real defect, an accessibility/readability issue, a
misleading quota/action behavior, a broken workflow, a reviewed workflow-clarity
friction (e.g. MDI-FABLE-01 findings), or an approved product decision. All such
changes must remain AIPF-controlled, scoped, reversible, and must preserve stable
backend, quota, runtime, and results-mode behavior unless separately approved.

For any future work, keep merge approval and deployment approval separate.
