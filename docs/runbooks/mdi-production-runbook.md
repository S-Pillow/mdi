# MDI Production Runbook

**Audience:** Administrators and operators maintaining MDI in production  
**Related docs:** [Operator Guide](../operator-guide.md) · [Deployment Notes](../deployment/deployment-notes.md) · [Runtime Data](../runtime-data.md) · [Error Recovery Matrix](../error-recovery-matrix.md)

---

## 1. Emergency quick reference

### Service status

```bash
sudo systemctl status mdi-backend.service
sudo systemctl status dns-tool-backend.service
sudo systemctl status nginx
```

### Safe GET smoke (0 VT quota)

```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8011/api/mdi/health
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8011/api/mdi/usage
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8011/api/mdi/dashboard
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8011/api/mdi/jobs/latest
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/vt-bulk-check/usage
curl -sS -o /dev/null -w "%{http_code}\n" https://forgeforward.app/tools/mdi/
curl -sS -o /dev/null -w "%{http_code}\n" https://forgeforward.app/tools/vt-bulk-check/
```

Expect **200** (404 on `/jobs/latest` is acceptable when no recovery file exists).

### Runtime metadata only (never print contents)

```bash
sudo stat /var/lib/dns-tool/vt_usage.lock
sudo stat /var/lib/dns-tool/vt_usage.json
sudo stat /var/lib/dns-tool/vt_usage_history.jsonl
sudo stat /var/lib/dns-tool/mdi_latest_job.json
```

### Journal checks

```bash
sudo journalctl -u mdi-backend.service -n 100 --no-pager
sudo journalctl -u dns-tool-backend.service -n 100 --no-pager
```

### Rollback reminder

- Frontend: restore from `mdi.bak-*` directory
- Backend: restore systemd unit + rsync previous code to `/opt/mdi`
- Coordinated quota-lock rollback: **both** MDI and VT Bulk services
- **Do not edit** runtime file contents during rollback

---

## 2. Architecture overview

```
Browser
   │
   ▼
nginx (forgeforward.app)
   ├── /tools/mdi/          → static files (/var/www/html/tools/mdi/)
   ├── /api/mdi/            → mdi-backend :8011 (user: mdi)
   ├── /tools/vt-bulk-check/ → static (VT Bulk frontend)
   └── /api/vt-bulk-check/  → dns-tool-backend :8000 (user: www-data)

Shared runtime: /var/lib/dns-tool/
   ├── vt_usage.json         (shared daily VT quota counter)
   ├── vt_usage.lock         (shared flock — MDI-19)
   ├── vt_usage_history.jsonl (shared metadata history)
   ├── vt_daily_history.json
   ├── mdi_latest_job.json   (MDI private recovery)
   └── vt_latest_job.json    (VT Bulk private recovery)

Secrets: /etc/dns-tool/secrets.env (group dns-tool, never print)
```

Both MDI and VT Bulk Check share the **500/day** VirusTotal quota.

---

## 3. Paths

| Path | Role |
|---|---|
| `/opt/mdi/backend` | **Production MDI backend** (systemd `WorkingDirectory`) |
| `/root/mdi` | Dev/operator git clone — **not** the runtime service path |
| `/var/www/html/tools/mdi/` | Deployed MDI frontend (static `dist/`) |
| `/var/www/dns-tool/backend` | VT Bulk Check backend |
| `/var/lib/dns-tool/` | Shared runtime directory |
| `/etc/dns-tool/secrets.env` | API keys and env (never commit, never cat) |

---

## 4. Services

| Service | User | Port | Restart when |
|---|---|---|---|
| `mdi-backend.service` | `mdi` | 8011 | MDI backend code, venv, or unit changes |
| `dns-tool-backend.service` | `www-data` | 8000 | VT Bulk code or shared quota-lock changes |
| `nginx` | root | 443/80 | nginx config or TLS changes only |

**Frontend-only MDI deploy:** no backend restart required.  
**Backend-only MDI deploy:** restart `mdi-backend` only — not nginx, not VT Bulk.  
**Quota-lock changes:** restart **both** backends in the same window.

---

## 5. Users and groups

| Identity | Purpose |
|---|---|
| `mdi` | Runs MDI backend; owns `/opt/mdi`; owns `mdi_latest_job.json` |
| `www-data` | Runs VT Bulk backend; owns `vt_latest_job.json` |
| `dns-tool` | Supplementary group for shared runtime, lock file, secrets read |

### Why MDI no longer runs as root (MDI-18B)

MDI previously ran as root with code under `/root/mdi/backend`. MDI-18B migrated
to dedicated user `mdi` at `/opt/mdi/backend` with systemd hardening and
group-based access to shared runtime. This limits blast radius if the service is
compromised.

**Never run production MDI from `/root/mdi/backend`.**

---

## 6. Runtime permission matrix

| Path | Owner:Group | Mode | Notes |
|---|---|---|---|
| `/var/lib/dns-tool/` | root:dns-tool | 2770 | setgid; both services via `dns-tool` group |
| `vt_usage.json` | *:dns-tool | 660 | Shared quota counter; owner = last writer |
| `vt_usage_history.jsonl` | *:dns-tool | 660 | Shared metadata history (append-only) |
| `vt_daily_history.json` | *:dns-tool | 660 | Shared daily totals |
| `vt_usage.lock` | root:dns-tool | 660 | Shared POSIX flock (MDI-19) |
| `mdi_latest_job.json` | mdi:mdi | 600 | MDI-only job recovery |
| `vt_latest_job.json` | www-data:www-data | 600 | VT Bulk only |
| `/etc/dns-tool/secrets.env` | root:dns-tool | 640 | Read via `dns-tool` group |

Verify with `stat` (metadata only). See [Runtime Data](../runtime-data.md).

---

## 7. Shared quota and lock

| Item | Detail |
|---|---|
| Daily limit | **500** VT lookups (MDI + VT Bulk combined) |
| Counter file | `/var/lib/dns-tool/vt_usage.json` |
| Lock file | `/var/lib/dns-tool/vt_usage.lock` |
| Mechanism | `fcntl.flock` — shared lock for reads, exclusive for writes |
| Timeout | 5 seconds → `quota_lock_timeout`; **no quota file mutation** on timeout |
| Critical rule | **Never hold lock during VT HTTP calls** |

### Coordinated deploy requirement

Any change to quota-lock behavior must deploy **both**:

1. MDI (`mdi-backend`) from this repo
2. VT Bulk Check (`dns-tool-backend`) from the dns-tool repo

Restart both in the **same maintenance window**. Partial rollout restores the
lost-update race on `vt_usage.json`.

### Partial rollout danger

If only one service has flock support, concurrent writes can corrupt quota
accounting. Treat mismatched versions as an incident.

### Quota lock validation status (MDI-21)

| Item | Result |
|---|---|
| Initial MDI-21 | **Failed** — VT Bulk stale `_USAGE_STATE` overwrote shared counter |
| MDI-21A hotfix | VT Bulk re-reads `vt_usage.json` under flock before GET/increment |
| MDI-21 rerun | **Passed** (after VT Bulk deploy @ `81e13a9`) |
| Sequential | Baseline **1** → after MDI **2** → after VT **3**; endpoints agreed |
| Concurrent | Baseline **3** → after concurrent MDI + VT **5**; no lost update |
| Rerun quota | 4 VT units consumed |
| Errors | No `quota_lock_timeout`, no `Permission denied` |
| Historical note | First failed run consumed 2 calls but recorded 1; not hand-corrected |
| Scope | Controlled validation only — **not** a stress or load test |

---

## 8. MDI-only backend deployment

```bash
cd /root/mdi
git fetch origin && git checkout main && git pull
git log -1 --oneline   # verify expected commit

sudo rsync -a --exclude '.git' --exclude 'frontend/dist' --exclude 'node_modules' \
  --exclude 'backend/venv' --exclude '.env' --exclude '.env.*' \
  /root/mdi/ /opt/mdi/

# MDI-26: deploy build marker (no runtime git)
COMMIT=$(git -C /root/mdi rev-parse HEAD)
BRANCH=$(git -C /root/mdi rev-parse --abbrev-ref HEAD)
sudo tee /opt/mdi/backend/build_info.json > /dev/null <<EOF
{
  "app": "mdi",
  "commit": "${COMMIT}",
  "branch": "${BRANCH}",
  "built_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "source": "deploy_marker"
}
EOF
sudo chown mdi:mdi /opt/mdi/backend/build_info.json
sudo chmod 644 /opt/mdi/backend/build_info.json

cd /opt/mdi/backend
sudo venv/bin/pip install -r requirements.txt   # if requirements changed

sudo chown -R mdi:mdi /opt/mdi
sudo chmod 755 /opt/mdi /opt/mdi/backend

sudo systemctl restart mdi-backend.service
sudo systemctl status mdi-backend.service
```

### Post-deploy verification

```bash
# Process user must be mdi
ps -o user= -p "$(systemctl show -p MainPID --value mdi-backend.service)"

# Safe GET smoke (§12)
curl -sS http://127.0.0.1:8011/api/mdi/usage

# Deploy commit stamp (MDI-26)
curl -sS http://127.0.0.1:8011/api/mdi/health | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d['build_info']['commit'])"
curl -sS http://127.0.0.1:8011/api/mdi/version

# Quota unchanged (compare daily_lookups_used before/after — metadata only)
sudo stat /var/lib/dns-tool/vt_usage.json
```

---

## 9. Frontend-only deployment

```bash
cd /root/mdi/frontend
npm install
npm run build

cp -r /var/www/html/tools/mdi /var/www/html/tools/mdi.bak-$(date +%Y%m%d-%H%M%S)
rsync -a --delete dist/ /var/www/html/tools/mdi/
```

No `mdi-backend` restart unless backend also changed.

Verify: `curl -sS -o /dev/null -w "%{http_code}\n" https://forgeforward.app/tools/mdi/`

---

## 10. Coordinated MDI + VT Bulk deployment

**Required when:** shared quota-lock code or quota accounting semantics change.

### MDI side

Follow §8 (rsync to `/opt/mdi`, chown `mdi:mdi`).

### VT Bulk side

Deploy from `/var/www/dns-tool` git clone per VT Bulk procedures (separate repo).

### Restart (same window)

```bash
sudo systemctl restart mdi-backend.service dns-tool-backend.service
sudo systemctl status mdi-backend.service dns-tool-backend.service
```

### Verify lock file

```bash
sudo stat /var/lib/dns-tool/vt_usage.lock
# Expect: root:dns-tool 660

# Both users must open for rw (metadata check via sudo -u)
sudo -u mdi test -r /var/lib/dns-tool/vt_usage.lock && echo mdi_ok
sudo -u www-data test -r /var/lib/dns-tool/vt_usage.lock && echo www-data_ok
```

### Safe GET smoke + quota unchanged

Run §12 checklist. Confirm `daily_lookups_used` did not change from deploy alone.

---

## 11. Rollback procedures

### MDI backend rollback (code)

```bash
git -C /root/mdi checkout <previous-good-commit>
sudo rsync -a --exclude '.git' --exclude 'backend/venv' /root/mdi/ /opt/mdi/
sudo chown -R mdi:mdi /opt/mdi
sudo systemctl restart mdi-backend.service
```

### Frontend rollback

```bash
rsync -a --delete /var/www/html/tools/mdi.bak-YYYYMMDD-HHMMSS/ /var/www/html/tools/mdi/
```

### Coordinated MDI + VT rollback

Rollback **both** codebases to last known-good commits. Restart both services.
Verify lock file permissions (§6). Do not truncate history.

### Systemd unit restore (MDI-18B migration)

```bash
TS=YYYYMMDD-HHMMSS
sudo cp -a /etc/systemd/system/mdi-backend.service.bak-$TS \
          /etc/systemd/system/mdi-backend.service
sudo systemctl daemon-reload
sudo systemctl restart mdi-backend.service
# Restore runtime ownership/modes from baseline capture if needed
```

### Rules

- **Do not edit** runtime file contents during rollback
- **Leave `/opt/mdi` in place** unless explicitly approved to remove
- Capture `stat` metadata and journal excerpts before destructive steps

---

## 12. Safe smoke test checklist

**GET-only. Zero VT quota consumption.**

| # | Check | Command / endpoint |
|---|---|---|
| 1 | MDI health | `GET /api/mdi/health` → 200; `build_info.commit` matches deploy |
| 1b | MDI version | `GET /api/mdi/version` → 200 |
| 2 | MDI usage | `GET /api/mdi/usage` → 200 |
| 3 | MDI dashboard | `GET /api/mdi/dashboard` → 200 |
| 4 | MDI recovery | `GET /api/mdi/jobs/latest` → 200 or 404 |
| 5 | VT usage | `GET /api/vt-bulk-check/usage` → 200 |
| 6 | MDI UI | `GET /tools/mdi/` → 200 |
| 7 | VT UI | `GET /tools/vt-bulk-check/` → 200 |
| 8 | Lock file | `stat /var/lib/dns-tool/vt_usage.lock` |
| 9 | MDI process user | `ps` → `mdi` |
| 10 | VT process user | `ps` → `www-data` |

**Not smoke tests:** job submit, refresh, rescan, export POST, live VT calls.

---

## 13. Journal / log checks

```bash
sudo journalctl -u mdi-backend.service -f
sudo journalctl -u dns-tool-backend.service -f
```

| Pattern | Meaning |
|---|---|
| `Permission denied` | Runtime ownership/mode mismatch — check §6 |
| `quota_lock_timeout` | Lock contention or stuck holder — check both services |
| `uvicorn.error` / traceback | Startup or request handler failure |
| `Address already in use` | Port conflict on 8011 or 8000 |

---

## 14. Troubleshooting

### Structured error recovery quick reference

See **[Error Recovery Matrix](../error-recovery-matrix.md)** for the full
code-level table and test matrix. Quick admin/operator cues:

| Code / topic | Severity | Action |
|---|---|---|
| `quota_lock_timeout` | error | Lock contention — retry later; check both backends and `vt_usage.lock`; **not** daily quota exhaustion |
| `quota_blocked` | skip | Daily quota exhausted — wait for UTC midnight; do not hand-edit `vt_usage.json` |
| `auth_error` / `no_api_key` | error | **Admin** — verify `/etc/dns-tool/secrets.env` and service group membership; not analyst retry loops |
| `whois_failed` / live-check warnings | warning | Partial evidence — VT triage may still stand; do not treat as incident |
| `vt_scan_not_supported` | skip | Domain-report mode or ineligible row — Refresh only |
| Export `no_flagged_rows` / `no_rows` | skip | Adjust export scope — **no new VT lookups** |
| Persistence / recovery | n/a | Missing/corrupt `mdi_latest_job.json` → 404, no crash; operator runs new job |
| Dashboard old history | n/a | Pre-MDI-17 lines may lack triage %; `data_quality.notes` explains gaps — metadata only |

### MDI 502/503

| Step | Action |
|---|---|
| Check | `systemctl status mdi-backend.service` |
| Check | `journalctl -u mdi-backend.service -n 50` |
| Check | `curl http://127.0.0.1:8011/api/mdi/health` |
| Action | Restart `mdi-backend` if code deploy completed |
| Escalate | nginx proxy config if backend healthy but edge 502 |

### VT Bulk 502/503

| Step | Action |
|---|---|
| Check | `systemctl status dns-tool-backend.service` |
| Check | Port 8000 listening |
| Action | Restart `dns-tool-backend` |

### Permission denied on runtime files

| Step | Action |
|---|---|
| Check | `stat` on failing path — compare §6 matrix |
| Check | `id mdi` and `id www-data` show `dns-tool` group |
| Action | Restore ownership/modes from MDI-18B baseline (do not edit contents) |

### `quota_lock_timeout`

| Step | Action |
|---|---|
| Check | Both services running and on MDI-19+ lock code |
| Check | `vt_usage.lock` exists, mode 660, group `dns-tool` |
| Check | Journals on both sides for lock errors |
| Action | Retry after brief wait; if persistent, coordinated restart |

### Quota mismatch suspicion

| Step | Action |
|---|---|
| Check | `GET /api/mdi/usage` vs `GET /api/vt-bulk-check/usage` |
| Check | `stat vt_usage.json` mtime (metadata only) |
| Action | Do **not** hand-edit `vt_usage.json`; escalate |
| Note | UTC midnight rollover resets date key automatically |

### Dashboard metrics unavailable

| Step | Action |
|---|---|
| Check | `GET /api/mdi/dashboard` response `data_quality` notes |
| Note | Pre-MDI-17 history lacks triage percentage fields |
| Note | Dashboard is metadata-only — not a domain search |

### Export failure

| Step | Action |
|---|---|
| Check | Job exists in memory or recovery file |
| Check | Browser network tab for 4xx/5xx on `POST .../export` |
| Note | Large jobs may OOM in memory — reduce scope |

### Recovered job confusion

| Step | Action |
|---|---|
| Check | `GET /api/mdi/jobs/latest` |
| Note | In-flight job lost on restart; previous completed job restores |
| Guide | Point operator to [Operator Guide §2](../operator-guide.md) |

### VT Bulk write failures

| Step | Action |
|---|---|
| Check | Shared file permissions (§6) |
| Check | `journalctl -u dns-tool-backend.service` |
| Check | Partial deploy suspicion — versions aligned? |

### Partial deploy suspicion

| Step | Action |
|---|---|
| Check | MDI and VT git commits both include quota-lock changes |
| Check | Lock file present and both users can read |
| Action | Complete coordinated deploy or rollback both sides |

---

## 15. Incident response

1. **Stop and preserve state** — avoid truncating history or editing quota files
2. **Capture metadata only** — `stat`, `systemctl status`, journal excerpts
3. **Do not print** `secrets.env`, `*_latest_job.json`, or history contents
4. **Restore last known-good** unit + code if service is down
5. **Coordinated rollback** if quota-lock mismatch suspected
6. **Escalate** with commit hashes, timestamps, and symptom table from §14

---

## 16. Do not do this

| Prohibited action | Why |
|---|---|
| Manually edit `vt_usage.json` | Breaks shared accounting |
| Delete or truncate `vt_usage_history.jsonl` | Loses audit trail |
| `cat /etc/dns-tool/secrets.env` | Exposes API keys |
| `cat` `mdi_latest_job.json` or `vt_latest_job.json` in reports | Contains operator-submitted domains |
| Deploy only one side of quota-lock changes | Restores lost-update race |
| Run live VT smoke without quota approval | Consumes shared quota |
| Restart nginx for backend-only changes | Unnecessary risk |
| Run production service from `/root/mdi/backend` | Wrong user, wrong path |
| Submit jobs/refresh/export during deploy smoke | Consumes quota, mutates state |

---

## 17. Known limitations

- Shared quota race mitigated by flock, not a full reservation model; MDI-21
  passed controlled sequential and light concurrent validation (not a load test)
- `vt_daily_history.json` schema differs between MDI and VT Bulk (documented, not unified)
- Dashboard old records may lack triage/runtime aggregate fields
- Large exports are in-memory only
- Open in VirusTotal is **disabled**
- Watchlist and Create Block Rule are **not implemented**
- Mid-job restart loses in-progress work

---

## 18. Admin quick checklist

### Pre-deploy

- ☐ Identify change type: MDI-only, frontend-only, or coordinated
- ☐ Note current `main` commit hash
- ☐ Record `daily_lookups_used` from usage GET (metadata)
- ☐ Confirm maintenance window if coordinated

### Deploy

- ☐ Rsync/build per §8–§10
- ☐ `chown mdi:mdi /opt/mdi` after backend rsync
- ☐ Restart correct service(s) only

### Smoke

- ☐ Run §12 GET checklist
- ☐ Verify process users (`mdi`, `www-data`)
- ☐ Verify quota unchanged from deploy alone

### Rollback (if needed)

- ☐ Restore code/unit from backup
- ☐ Restart affected service(s)
- ☐ Re-run smoke
- ☐ Do not edit runtime contents
