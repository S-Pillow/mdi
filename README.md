# MDI — Malicious Domain Identifier

Internal Forge Forward tool. Standalone Vite/React frontend + FastAPI backend.

Public route: `https://forgeforward.app/tools/mdi/`

## Status

Shell only. Functionality not yet implemented.

## Architecture

| Layer | Stack | Port/Path |
|---|---|---|
| Frontend | Vite + React 18 | Static — `/var/www/html/tools/mdi/` |
| Backend | FastAPI + uvicorn | `127.0.0.1:8011` |
| nginx | Proxy + static | `/tools/mdi/` and `/api/mdi/` |

## Planned capabilities (future tickets)

- Domain reputation check via VirusTotal (shared quota with vt-bulk-check)
- WHOIS / RDAP lookup
- URL live activity check (SSRF-safe)
- DNS lookup helper
- clientHold / serverHold skip logic
- Triage summary and results dashboard
- CSV export

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

## Deployment

See `docs/deployment/deployment-notes.md`.

## Environment variables

Copy `.env.example` to `.env` on the production host and fill in real values.
Never commit `.env`.
