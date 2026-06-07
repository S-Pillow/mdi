# MDI Deployment Notes

## Server layout

| Path | Purpose |
|---|---|
| `/root/mdi/` | Operator dev clone (git repo; not used by systemd service) |
| `/opt/mdi/` | Production backend deploy tree (MDI-18B) |
| `/opt/mdi/backend/` | FastAPI backend run by `mdi-backend.service` |
| `/root/mdi/frontend/` | Frontend source (build from dev clone) |
| `/var/www/html/tools/mdi/` | Deployed static frontend (built dist/ contents) |
| `/var/lib/dns-tool/` | Shared runtime directory (MDI + VT Bulk Check) |

## Backend service

`/etc/systemd/system/mdi-backend.service`

Runs as dedicated system user **`mdi`** (primary group `mdi`, supplementary group `dns-tool`).
Application path: **`/opt/mdi/backend`**. Port: `127.0.0.1:8011`.
Secrets injected from `/etc/dns-tool/secrets.env` via `EnvironmentFile=`.

Systemd hardening (phase 1): `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`,
`ReadWritePaths=/var/lib/dns-tool`, `ProtectHome`, `RestrictAddressFamilies`, `LockPersonality`.

### First-time / redeploy backend

```bash
# Deploy code (from dev clone)
sudo rsync -a --exclude '.git' --exclude 'frontend/dist' --exclude 'node_modules' \
  --exclude 'backend/venv' --exclude '.env' --exclude '.env.*' \
  /root/mdi/ /opt/mdi/

# Venv
cd /opt/mdi/backend
sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt
sudo chown -R mdi:mdi /opt/mdi
sudo chmod 755 /opt/mdi /opt/mdi/backend

sudo systemctl daemon-reload
sudo systemctl restart mdi-backend.service
sudo systemctl status mdi-backend.service
```

### Runtime permission matrix (MDI-18B)

| Path | Owner:Group | Mode | Access |
|---|---|---|---|
| `/var/lib/dns-tool/` | root:dns-tool | 2770 | MDI + VT Bulk (via `dns-tool` group) |
| `vt_usage.json` | root:dns-tool | 660 | Shared quota counter |
| `vt_usage_history.jsonl` | root:dns-tool | 660 | Shared metadata history (append) |
| `vt_daily_history.json` | root:dns-tool | 660 | Shared daily history |
| `mdi_latest_job.json` | mdi:mdi | 600 | MDI-only job recovery |
| `vt_latest_job.json` | www-data:www-data | 600 | VT Bulk only |
| `/etc/dns-tool/secrets.env` | root:dns-tool | 640 | `mdi` + `www-data` via `dns-tool` group |

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

### Backend (MDI-18B non-root migration)

```bash
TS=YYYYMMDD-HHMMSS   # backup timestamp from migration
cp -a /etc/systemd/system/mdi-backend.service.bak-$TS \
      /etc/systemd/system/mdi-backend.service
systemctl daemon-reload
# Restore runtime ownership/modes from mdi-18b baseline capture
systemctl restart mdi-backend.service
# Leave /opt/mdi in place until explicit approval to remove
```

### Backend (code-only rollback)

```bash
git -C /root/mdi checkout <previous-commit>
rsync -a --exclude '.git' --exclude 'backend/venv' /root/mdi/ /opt/mdi/
chown -R mdi:mdi /opt/mdi
systemctl restart mdi-backend.service
```

## Environment variables

Real values injected via `/etc/dns-tool/secrets.env` (managed separately, never committed).
See `.env.example` for the full variable list.
