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
| Frontend | VTFIX-02C UI: `fbef931481501f42e104009100ce41f1c402718e` | Static bundle: `index-QhEGJa8t.js`, `index-CZdxqujH.css` at `/var/www/html/tools/mdi/` |
| Backend | VTFIX-02C: `a3286491f2429af6bd7ecbd4ba48f9e4bb2f4a3e` | `/opt/mdi/backend`; `/api/mdi/version` build marker |

The frontend/backend split is expected after frontend-only deploys. VTFIX-02C
backend (source attribution + metric ownership) deployed 2026-06-11; the UI layout
revision (`fbef931`) deployed frontend-only with **no backend restart** and **no
nginx reload**. Backend `build_info.commit` remains at `a328649` until the next
backend deploy.

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

### VTFIX-02 shared VT quota / dashboard attribution series

| Ticket | Outcome |
|---|---|
| VTFIX-02A | Discovery — architecture and schema mismatch report |
| VTFIX-02E | `vt_usage_history.jsonl` permission hardening — merged, deployed (docs/script) |
| VTFIX-02B | VT Bulk Check JSONL contract (`tool_name`, `timestamp`, `quota_units_consumed`) — deployed to VT Bulk backend |
| VTFIX-02C | MDI dashboard shared attribution, metric ownership, and horizontal card layout — **merged, deployed, operator-smoked, visually confirmed** |

VTFIX-02C commits on `main`: `6ff4811` (source attribution), `a328649` (metric
ownership, backend), `fbef931` (dashboard card layout, frontend).

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
- bulk actions
- CSV / JSON evidence exports
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
| Export actions | No VT quota |
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
| No tagged `vt_bulk_check` history until future VTFIX-02B-tagged jobs append records | Acceptable — pending new jobs |
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

### VTFIX follow-on (not started)

| Ticket | Scope | Status |
|---|---|---|
| VTFIX-02D | Daily-history schema unification | **Not started** |
| VTFIX-02G | Dashboard UI polish / quota trend / cards | **Not started** |
| VTFIX-02H | Jun 10 metadata backfill (optional) | **Not started** |

### Other non-blocking items

- Add quota-cost hint parity for Request New Scan tooltip.
- Add backup-pruning routine or runbook note.
- Surface dashboard quota trends if still desired.
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
