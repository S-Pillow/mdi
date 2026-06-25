# MDI — Malicious Domain Identifier

Internal Forge Forward triage utility for reviewing domains and URLs submitted
by operators. Standalone Vite/React frontend + FastAPI backend.

**Production URL:** `https://forgeforward.app/tools/mdi/`

## What MDI does today

MDI is an analyst workflow for reviewing potentially malicious domains and URLs
using saved evidence, quota-aware checks, and exportable results. It:

- Accepts **paste** input (domains/URLs, one per line or separated)
- Accepts **CSV/XLSX upload** with automatic header detection (legacy `.xls` not supported)
- Runs **quota-free** input validation, upload preview, and quota/runtime **estimate**
- **Hold-aware upload estimate** — spreadsheet rows with `clientHold` / `serverHold` (including pipe-delimited EPP status cells) are counted as hold-skipped and excluded from eligible VT estimates
- Runs **VirusTotal checks only after explicit job submission** (`Run MDI Check`)
- Skips VT and live checks for **held domains** (from upload metadata or RDAP/WHOIS enrichment)
- Surfaces **limited VT URL evidence** on URL-report checks (targeted brand, redirection chain, last final URL) — context only, not enforcement
- Enriches registered domains via **RDAP/WHOIS** (age, registrar, hold context)
- Optionally enriches with **Cloudflare Radar DNS popularity** rank/bucket when enabled (blast-radius context, not maliciousness proof)
- Provides **hold-impact guidance** from popularity bucket (Critical → Unknown) — guidance only; does not override triage or act on registries
- Runs **live URL checks** for eligible **flagged** items during job processing
- Classifies results with **updated recommended actions** (investigate/hold review, request new scan for stale evidence, verify/investigate when live/age is uncertain, action already taken for held domains)
- Classifies results into **triage cards**, a priority-sorted **results table**, and a **detail drawer**
- Provides a per-row **More Actions** menu (export evidence, refresh, request scan)
- Exposes **Run Options** (sidebar) and **Advanced Settings** (nav gear menu), including optional Cloudflare Radar rank lookup
- Shows an operational **dashboard** (metadata-only aggregates; no domain search)
- Exports **CSV** (default) or **XLSX** analyst reports (all / flagged / selected) and **JSON evidence** for full forensic fields

MDI does not perform automated enforcement or takedown actions; operator review
remains required.

## MDI Processing Flow

- Upload or paste domains/URLs.
- MDI normalizes input and previews estimated quota usage.
- Spreadsheet uploads detect hold statuses (comma, semicolon, pipe, or whitespace separated) and exclude hold-skipped rows from VT quota estimates.
- MDI checks eligible items using the selected VT mode (URL report or domain report for bare domains).
- MDI enriches saved results with domain/URL evidence, registrar/hold context, optional Cloudflare Radar popularity context, freshness/live context, and triage guidance.
- Results show triage, recommended action, hold-impact guidance, VT ratio, freshness, live status, created date, and age.
- Operators can export CSV/XLSX analyst reports or JSON evidence.

## Architecture

| Layer | Stack | Path / port |
|---|---|---|
| Frontend | Vite + React 18 | Static — `/var/www/html/tools/mdi/` |
| Backend | FastAPI + uvicorn | `127.0.0.1:8011` — `/opt/mdi/backend/` |
| nginx | Static + API proxy | `/tools/mdi/` and `/api/mdi/` |
| Runtime data | Shared with VT Bulk Check | `/var/lib/dns-tool/` (**excluded from Git**) |

Runtime files (`vt_usage.json`, `mdi_latest_job.json`, usage history, locks) live
under `/var/lib/dns-tool/` and are **never committed**. See
[`docs/runtime-data.md`](docs/runtime-data.md).

## Quota safety

MDI shares a **500 lookups/day** VirusTotal quota with **VT Bulk Check**
(`/tools/vt-bulk-check/`). Preview and estimate consume **no quota**. Always
**Estimate** before **Run MDI Check**. Auto-rescan (Advanced Settings) is **OFF
by default** but can consume significant additional quota when enabled.

## Local development

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8011
```

### Frontend production build

```bash
cd frontend
npm install
npm run build
```

## Deployment

See [`docs/deployment/deployment-notes.md`](docs/deployment/deployment-notes.md)
and [`docs/runbooks/mdi-production-runbook.md`](docs/runbooks/mdi-production-runbook.md).

**Frontend-only deploys** update static bundle hashes under `/tools/mdi/` without
changing backend `build_info`. Check both backend commit (`GET /api/mdi/version`)
and frontend asset filenames when auditing production.

## Documentation

| Doc | Purpose |
|---|---|
| [`docs/operator-guide.md`](docs/operator-guide.md) | Analyst workflow, quota rules, UI behavior |
| [`docs/release-readiness-handoff.md`](docs/release-readiness-handoff.md) | Release status, operator handoff, known limitations |
| [`docs/field-purpose-map.md`](docs/field-purpose-map.md) | Field/control contracts and classification |
| [`docs/runtime-data.md`](docs/runtime-data.md) | Runtime files and API side effects |
| [`docs/error-recovery-matrix.md`](docs/error-recovery-matrix.md) | Error codes and recovery actions |
| [`docs/runbooks/mdi-production-runbook.md`](docs/runbooks/mdi-production-runbook.md) | Deploy, smoke, incidents |

## Environment variables

Copy `.env.example` to `.env` on the production host and fill in real values.
Production secrets are injected via `/etc/dns-tool/secrets.env` (never commit).

Optional Cloudflare Radar rank lookup requires `CLOUDFLARE_RADAR_API_TOKEN` in
server-side secrets when the job option is enabled.
