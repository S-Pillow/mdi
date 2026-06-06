# MDI Deployment Notes

## Server layout

| Path | Purpose |
|---|---|
| `/root/mdi/` | Source repo (clone of S-Pillow/mdi) |
| `/root/mdi/backend/` | FastAPI backend source |
| `/root/mdi/frontend/` | Vite/React frontend source |
| `/var/www/html/tools/mdi/` | Deployed static frontend (built dist/ contents) |
| `/var/lib/dns-tool/mdi_*.json` | MDI runtime files (shared directory with vt-bulk-check) |

## Backend service

`/etc/systemd/system/mdi-backend.service`

Runs as `www-data`. Uses port `127.0.0.1:8011`.
Secrets injected from `/etc/dns-tool/secrets.env` via `EnvironmentFile=`.

### First-time setup

```bash
cd /root/mdi/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mdi-backend.service
sudo systemctl status mdi-backend.service
```

## Frontend deployment

```bash
cd /root/mdi/frontend
npm install
npm run build

# Backup existing deployment
cp -r /var/www/html/tools/mdi /var/www/html/tools/mdi.bak-$(date +%Y%m%d-%H%M%S)

# Deploy
rsync -a --delete dist/ /var/www/html/tools/mdi/
```

## nginx

Two location blocks in the forgeforward.app nginx config:
- `location ^~ /api/mdi/` — proxy to port 8011
- `location ^~ /tools/mdi/` — static files from `/var/www/html/tools/mdi/`

After editing nginx config:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

## Rollback

### Frontend
```bash
rsync -a --delete /var/www/html/tools/mdi.bak-YYYYMMDD-HHMMSS/ /var/www/html/tools/mdi/
```

### Backend
```bash
git -C /root/mdi checkout <previous-commit>
sudo systemctl restart mdi-backend.service
```

## Environment variables

Real values injected via `/etc/dns-tool/secrets.env` (managed separately, never committed).
See `.env.example` for the full variable list.
