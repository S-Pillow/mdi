# MDI-50B — Cloudflare Radar Rank Lookup Live Validation + Integration Plan

**Status:** Live validation **blocked** — token not on server filesystem (rerun 2026-06-24)  
**Date:** 2026-06-24 (initial), 2026-06-24 (rerun)  
**Parent:** [MDI-50A Cloudflare Radar API Contract](./mdi-50a-cloudflare-radar-api-contract.md)  
**Main baseline:** `a8bf7dc429120d05177eb6087710c8a9fc990fc5`

---

## 1. Summary verdict

**LIVE VALIDATION BLOCKED — TOKEN NOT ON SERVER (RERUN)**

A validation rerun was performed after operator reported token installation. On the validation host, `CLOUDFLARE_RADAR_API_TOKEN` is **still not present** in `/etc/dns-tool/secrets.env`. No Cloudflare API calls were made in either attempt. Token was not exposed, printed, or committed.

**Rerun findings (2026-06-24):**

| Check | Result |
|-------|--------|
| `/etc/dns-tool/secrets.env` exists | Yes (`640`, `root:dns-tool`) |
| File line count on disk | **1** (not updated since 2026-05-24) |
| Variable names on disk (keys only) | `VT_API_KEY` only — **no** `CLOUDFLARE_RADAR_API_TOKEN` |
| Token loadable in subshell without echo | **No** (empty after sourcing secrets file) |
| Cloudflare API calls (rerun) | **0** |

**Likely cause:** Token may exist in an unsaved editor buffer but has **not been written** to the server path `/etc/dns-tool/secrets.env`. Operator must save the file on the server (requires root / `dns-tool` group write access).

**MDI-50B implementation readiness:** **Not ready** — live response shape still unvalidated. Proceed with implementation only after a successful rerun with token on disk.

**Implementation plan:** Retained below from MDI-50A + Cloudflare documentation.

---

## 2. Token handling confirmation

| Check | Result |
|-------|--------|
| Token pasted in chat | No |
| Token printed | No |
| Token committed | No |
| Token in docs | No |
| Env file contents printed | No |
| Variable name checked only | Yes — `CLOUDFLARE_RADAR_API_TOKEN` **missing** (initial + rerun) |
| `/etc/dns-tool/secrets.env` exists | Yes (mode `640`, `root:dns-tool`) |
| Rerun date | 2026-06-24 |
| Keys found on disk (rerun) | `VT_API_KEY` only |

### Operator installation required (server-side only)

Add one line to `/etc/dns-tool/secrets.env`:

```
CLOUDFLARE_RADAR_API_TOKEN=<token value>
```

**Do not** paste the token into chat, tickets, or git.

After installation:

- Confirm mode remains `640` and group `dns-tool` (same pattern as other shared secrets).
- `mdi` user reads via supplementary `dns-tool` group (existing MDI-18B pattern).
- **No service restart required** for validation-only shell probes; `mdi-backend.service` restart only needed after MDI-50B code deploy reads the new variable.

**Verification after save (operator):**

```bash
# Keys only — must include CLOUDFLARE_RADAR_API_TOKEN; never print values
awk -F= '/^[A-Za-z0-9_]+=/ {print $1}' /etc/dns-tool/secrets.env
```

Then re-run validation with the same three domains before MDI-50B implementation.

---

## 3. Live validation (not performed — initial and rerun)

### Planned domains (unchanged)

| # | Domain | Purpose |
|---|--------|---------|
| 1 | `google.com` | High rank / top bucket |
| 2 | `example.com` | Well-known; rank vs bucket vs 404 |
| 3 | `definitely-not-real-mdi-radar-validation-20260624.example` | Unranked / no-data behavior |

### Planned endpoint

```
GET https://api.cloudflare.com/client/v4/radar/ranking/domain/{domain}
Authorization: Bearer <CLOUDFLARE_RADAR_API_TOKEN>
```

Query: `rankingType=POPULAR` (default), `format=JSON`.

### API calls made

| Attempt | Calls |
|---------|-------|
| Initial (2026-06-24) | **0** — token missing |
| Rerun (2026-06-24) | **0** — token still not on server filesystem |
| **Total** | **0** |

### Sanitized result table

| Domain | HTTP | success | rank | bucket | MDI status | Notes |
|--------|------|---------|------|--------|------------|-------|
| `google.com` | — | — | — | — | — | Not called |
| `example.com` | — | — | — | — | — | Not called |
| `definitely-not-real-mdi-radar-validation-20260624.example` | — | — | — | — | — | Not called |

---

## 4. Response-shape findings (documentation baseline — unvalidated live)

From MDI-50A and [Cloudflare Ranking API docs](https://developers.cloudflare.com/api/resources/radar/subresources/ranking/) (pending live confirm):

| Finding | Expected (docs) | Live confirmed |
|---------|-----------------|----------------|
| Endpoint path | `/client/v4/radar/ranking/domain/{domain}` | Pending |
| Auth | Account → Radar → Read Bearer token | Pending |
| Top-level shape | `success`, `errors[]`, `result` | Pending |
| Result body | `result.details_0`, `result.meta` | Pending |
| `details_0.rank` | Optional number; top ~100 | Pending |
| `details_0.bucket` | Optional string (e.g. `"2000"`, `"1000000"`) | Pending |
| `details_0.categories` | Often empty outside top 100 — **ignore for MDI** | Pending |
| `meta.dateRange` | `startTime`, `endTime` — use as rank as-of window | Pending |
| Unranked domain | HTTP 404, error code **7003** (Radar error codes doc) | Pending |
| Rate limit | HTTP 429, error 1015 | Pending |

---

## 5. Rank/bucket normalization plan (proposed for MDI-50B)

### Target fields (per result row, additive)

| Field | Type | Source |
|-------|------|--------|
| `cloudflare_rank_available` | bool | `true` when rank or bucket obtained |
| `cloudflare_rank` | int \| null | `details_0.rank` when present |
| `cloudflare_rank_raw_bucket` | string \| null | `details_0.bucket` as returned |
| `cloudflare_rank_bucket` | string | Normalized enum (below) |
| `cloudflare_rank_source` | `"cloudflare_radar_popular"` | Constant |
| `cloudflare_rank_as_of_start` | ISO \| null | `meta.dateRange[0].startTime` |
| `cloudflare_rank_as_of_end` | ISO \| null | `meta.dateRange[0].endTime` |
| `cloudflare_rank_checked_at` | ISO | MDI lookup timestamp |
| `cloudflare_rank_error` | string \| null | Sanitized error code only |

**Not in MDI-50B:** `hold_impact_level`, `hold_impact_reason` (MDI-50C).

### Normalized bucket enum

`TOP_100` | `TOP_1K` | `TOP_5K` | `TOP_10K` | `TOP_100K` | `TOP_1M` | `UNRANKED` | `UNKNOWN`

### Mapping algorithm (implement in MDI-50B)

```
function normalize_bucket(rank, raw_bucket, http_status, cf_success, errors):
  if auth failure (401/403): return UNKNOWN, error=auth_failed
  if rate limit (429): return UNKNOWN, error=rate_limited
  if 5xx or timeout: return UNKNOWN, error=api_unavailable|timeout
  if malformed JSON: return UNKNOWN, error=invalid_response

  if http 404 or cf error 7003 or success with no rank/bucket:
    return UNRANKED, error=null

  if rank is int and 1 <= rank <= 100:
    return TOP_100

  if raw_bucket present:
    n = parse_int(raw_bucket)  # API docs show string e.g. "2000"
    if n <= 1000: return TOP_1K
    if n <= 5000: return TOP_5K
    if n <= 10000: return TOP_10K
    if n <= 100000: return TOP_100K
    if n <= 1000000: return TOP_1M

  if rank present but > 100 and no bucket:
    return UNKNOWN, error=ambiguous_rank  # live validation must confirm

  return UNKNOWN, error=no_rank_signal
```

**Tightest bucket wins:** store both `cloudflare_rank_raw_bucket` and normalized `cloudflare_rank_bucket`.

---

## 6. Failure behavior (proposed — confirm on live re-run)

| Condition | `cloudflare_rank_available` | `cloudflare_rank_bucket` | `cloudflare_rank_error` |
|-----------|----------------------------|--------------------------|-------------------------|
| 200 + rank/bucket | true | normalized | null |
| 404 / 7003 / no data | false | UNRANKED | null |
| 401 / 403 | false | UNKNOWN | `auth_failed` |
| 429 | false | UNKNOWN | `rate_limited` |
| 5xx | false | UNKNOWN | `api_unavailable` |
| Timeout | false | UNKNOWN | `timeout` |
| Feature disabled | omit or false | UNKNOWN | `disabled` |
| Missing token | omit or false | UNKNOWN | `not_configured` |

**Never fail MDI job processing** because of Cloudflare errors.

---

## 7. Security findings

- Token must remain in `/etc/dns-tool/secrets.env` only; loaded by backend at startup.
- Never expose token to frontend, exports, logs, or API responses.
- Use dedicated **Radar Read** token with minimal scope.
- Validation script (if used) must read token via env without `set -x`, without printing headers.
- Radar API data licensed **CC BY-NC 4.0** — operator/legal review before production.

---

## 8. MDI-50B implementation plan (do not implement in this ticket)

### 8.1 Backend files (proposed)

| File | Purpose |
|------|---------|
| `backend/services/cloudflare_radar.py` | HTTP client, normalization, cache, error mapping |
| `backend/models.py` | `CloudflareRankInfo` Pydantic model on `MdiResultItem` |
| `backend/services/job_processor.py` | Optional lookup hook after domain normalization (feature-gated) |
| `backend/routers/mdi.py` | Settings field `cloudflare_rank_lookup_enabled` (default `false`) |
| `backend/tests/test_cloudflare_radar.py` | Mocked HTTP responses for all status paths |
| `backend/tests/fixtures/cloudflare_radar/` | Sanitized JSON fixtures from post-token live validation |

### 8.2 Config

| Item | Value |
|------|-------|
| Env var | `CLOUDFLARE_RADAR_API_TOKEN` |
| Location | `/etc/dns-tool/secrets.env` |
| Job setting | `cloudflare_rank_lookup_enabled: bool = False` |
| Timeout | 8 seconds per request |
| Retries | 0 on 4xx; 1 retry on 5xx/timeout only |
| Per-job cap | 100 lookups (configurable constant) |
| On 429 | Stop remaining lookups for job; mark skipped rows `UNKNOWN` / `rate_limited` |

### 8.3 Cache strategy

- In-process LRU + optional disk cache under `/var/lib/dns-tool/` (e.g. `mdi_cf_rank_cache.json`, mdi-owned, mode 600).
- Key: registrable domain (same normalization as MDI domain parsing).
- TTL: **7 days** (aligns with weekly bucket dataset refresh; tunable).
- Cache negative UNRANKED responses for 24h to reduce repeat 404 calls.

### 8.4 Data model / API

Add optional nested object on each result item:

```json
"cloudflare_rank": {
  "available": true,
  "rank": 1,
  "bucket": "TOP_100",
  "raw_bucket": null,
  "source": "cloudflare_radar_popular",
  "checked_at": "2026-06-24T12:00:00Z",
  "as_of_start": "...",
  "as_of_end": "...",
  "error": null
}
```

Persist in job results and exports as optional columns / nested JSON.

### 8.5 UI (MDI-50B minimal — no hold-impact guardrail)

- Settings panel: toggle **“Cloudflare rank lookup (experimental)”** default **off**; help text explains popularity context only.
- Result drawer: read-only row “Cloudflare rank” / bucket badge when available; “Unavailable” / “Unranked” / “Unknown” otherwise.
- **No** hold-impact warnings, escalation colors, or action buttons (MDI-50C).

### 8.6 Export

- CSV: optional columns `cloudflare_rank`, `cloudflare_rank_bucket`, `cloudflare_rank_error`.
- JSON: nested `cloudflare_rank` object.
- Never export token or raw Cloudflare response.

### 8.7 Tests required (MDI-50B implementation ticket)

1. Mock 200 with rank only → `TOP_100`
2. Mock 200 with bucket `"10000"` → `TOP_10K`
3. Mock 404 / error 7003 → `UNRANKED`, no error string
4. Mock 401 → `UNKNOWN`, `auth_failed`
5. Mock 429 → `UNKNOWN`, `rate_limited`; cap stops further calls
6. Feature disabled → no HTTP calls (assert mock not called)
7. Missing token → no HTTP calls, `not_configured`
8. Cache hit → no second HTTP call within TTL
9. Job completion succeeds when Cloudflare fails
10. VT triage fields unchanged (regression)

### 8.8 Live smoke (MDI-50B implementation ticket, post-deploy)

- Operator enables setting on test job with 3 domains.
- Confirm no VT quota change.
- Re-use same three validation domains.

### 8.9 MDI-50C dependency

**MDI-50C must wait** until MDI-50B is merged, deployed, and live smoke passes. MDI-50C adds `hold_impact_level` / operator warnings only; no new Cloudflare calls.

---

## 9. Validation questions — status

| # | Question | Status |
|---|----------|--------|
| 1 | Account → Radar → Read works? | **Pending** (no token) |
| 2 | Path `/client/v4/radar/ranking/domain/{domain}` exact? | Docs yes; live pending |
| 3 | `google.com` rank vs bucket? | Pending |
| 4 | `example.com` behavior? | Pending |
| 5 | Unranked domain behavior? | Pending |
| 6 | 404 vs 7003 vs empty? | Docs say 7003/404; live pending |
| 7 | Bucket numeric strings? | Docs say string; live pending |
| 8 | `meta.dateRange` useful? | Expected yes; live pending |
| 9 | Response stable for implementation? | Likely yes; live pending |
| 10 | Rate-limit/auth issues? | None observed (no calls) |

---

## 10. Recommended next step

1. **Operator:** **Save** `CLOUDFLARE_RADAR_API_TOKEN` to `/etc/dns-tool/secrets.env` **on the server** (not only in IDE buffer). Use root/sudo; keep mode `640`, group `dns-tool`.
2. **Verify** key name appears via `awk -F= '/^[A-Za-z0-9_]+=/ {print $1}' /etc/dns-tool/secrets.env` (must list `CLOUDFLARE_RADAR_API_TOKEN`).
3. **Re-run MDI-50B live validation** — max 3 API calls; update §3–§6 with sanitized live results.
4. **Approve MDI-50B implementation** only after live validation passes.
5. Implement MDI-50B per §8; deploy; live smoke; then plan MDI-50C.

---

## 11. Scope reminders

Cloudflare Radar rank is **popularity/blast-radius context only**. It must **not**:

- Make a domain malicious
- Change VT flagged/suspicious logic or `triage_bucket`
- Trigger `serverHold` / `clientHold` or any enforcement
- Automate Salesforce/registrar/takedown actions
