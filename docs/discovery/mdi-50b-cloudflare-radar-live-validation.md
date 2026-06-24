# MDI-50B — Cloudflare Radar Rank Lookup Live Validation + Integration Plan

**Status:** Live validation **complete** (2026-06-24T07:42:36Z UTC)  
**Date:** 2026-06-24 (initial blocked), 2026-06-24 (rerun blocked), 2026-06-24 (live success)  
**Parent:** [MDI-50A Cloudflare Radar API Contract](./mdi-50a-cloudflare-radar-api-contract.md)  
**Main baseline:** `a8bf7dc429120d05177eb6087710c8a9fc990fc5`

---

## 1. Summary verdict

**LIVE VALIDATION COMPLETE**

After operator saved `CLOUDFLARE_RADAR_API_TOKEN` to `/etc/dns-tool/secrets.env`, three Cloudflare Radar domain lookups succeeded. Token was not exposed, printed, or committed.

| Attempt | Date | Calls | Outcome |
|---------|------|-------|---------|
| Initial | 2026-06-24 | 0 | Token missing |
| Rerun (unsaved token) | 2026-06-24 | 0 | Token not on disk |
| **Live success** | 2026-06-24T07:42:36Z | **3** | Auth OK; response shape confirmed |

**MDI-50B implementation readiness:** **Ready to proceed** — endpoint, auth, and normalization rules validated live with one MDI-50A deviation (unranked domains may return HTTP 200 with bucket `>N` instead of 404).

**Implementation plan:** Retained and updated in §5–§8 based on live results.

---

## 2. Token handling confirmation

| Check | Result |
|-------|--------|
| Token pasted in chat | No |
| Token printed | No |
| Token committed | No |
| Token in docs | No |
| Env file contents printed | No |
| Variable name checked only | Yes — `CLOUDFLARE_RADAR_API_TOKEN` **present** (live run) |
| `/etc/dns-tool/secrets.env` exists | Yes (mode `640`, `root:dns-tool`) |
| Token loadable without echo | **Yes** |
| Live validation timestamp | 2026-06-24T07:42:36Z UTC |

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

## 3. Live validation results

### Endpoint

```
GET https://api.cloudflare.com/client/v4/radar/ranking/domain/{domain}?rankingType=POPULAR&format=JSON
Authorization: Bearer <CLOUDFLARE_RADAR_API_TOKEN>
```

### Domains tested

| # | Domain | Purpose |
|---|--------|---------|
| 1 | `google.com` | High rank / top bucket |
| 2 | `example.com` | Well-known; bucket without exact rank |
| 3 | `definitely-not-real-mdi-radar-validation-20260624.example` | Low/unranked behavior |

### API calls made

| Attempt | Calls |
|---------|-------|
| Initial / blocked reruns | 0 |
| **Live success (2026-06-24T07:42:36Z)** | **3** |
| Retries | 0 |
| **Total live** | **3** |

### Sanitized result table

| Domain | HTTP | success | details_0 | rank | bucket | dateRange | Normalized bucket | MDI status | Notes |
|--------|------|---------|-----------|------|--------|-----------|-------------------|------------|-------|
| `google.com` | 200 | true | yes | **1** | `"200"` | yes | `TOP_100` | **ranked** | Rank + bucket both returned; rank drives normalization |
| `example.com` | 200 | true | yes | — | `"200"` | yes | `TOP_1K` | **ranked** | Bucket only (not in ordered top 100) |
| `definitely-not-real-mdi-radar-validation-20260624.example` | 200 | true | yes | — | `">200000"` | yes | `UNRANKED` | **unranked** | Not 404; inequality bucket means beyond top 200K |

**Unexpected keys:** None on top-level, `result`, or `details_0` for all three calls.

**Errors:** None. No 401/403/429 observed.

---

## 4. Response-shape findings (live confirmed 2026-06-24)

| Finding | Expected (MDI-50A / docs) | Live confirmed |
|---------|---------------------------|----------------|
| Endpoint path | `/client/v4/radar/ranking/domain/{domain}` | **Yes** |
| Auth Account → Radar → Read | Bearer token | **Yes** — all 3 calls HTTP 200 |
| Top-level shape | `success`, `errors[]`, `result` | **Yes** — no unexpected top keys |
| Result body | `result.details_0`, `result.meta` | **Yes** |
| `details_0.rank` | Optional number; top ~100 | **Yes** — `google.com` rank `1`; absent on others |
| `details_0.bucket` | Optional string | **Yes** — numeric strings (`"200"`) and inequality (`">200000"`) |
| `details_0.categories` | Often empty outside top 100 | Not inspected (ignore for MDI) |
| `meta.dateRange` | `startTime`, `endTime` | **Yes** — present on all 3 |
| Unranked domain | HTTP 404 / error **7003** | **Deviation** — synthetic domain returned **200** with bucket `">200000"` |
| Rate limit / auth | 429 / 401 | **Not observed** |

### Deviations from MDI-50A assumptions

1. **Unranked ≠ always 404.** Domains outside tracked buckets may return `success: true` with `bucket: ">200000"` (beyond top 200K). MDI must treat inequality buckets as **UNRANKED**, not API error.
2. **Rank and bucket can coexist.** `google.com` returned `rank: 1` and `bucket: "200"`. Prefer **exact rank** when `1 ≤ rank ≤ 100` for normalization.
3. **Bucket `"200"`** means top-200 bucket (not rank 200). Map via numeric parse to `TOP_1K` when rank absent.

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

### Mapping algorithm (validated live — implement in MDI-50B)

```
function normalize_bucket(rank, raw_bucket, http_status, cf_success, errors):
  if auth failure (401/403): return UNKNOWN, error=auth_failed
  if rate limit (429): return UNKNOWN, error=rate_limited
  if 5xx or timeout: return UNKNOWN, error=api_unavailable|timeout
  if malformed JSON: return UNKNOWN, error=invalid_response

  if http 404 or cf error 7003:
    return UNRANKED, error=null

  if rank is int and 1 <= rank <= 100:
    return TOP_100

  if raw_bucket is string matching /^>(\d+)$/:
    return UNRANKED, error=null   # live: ">200000" = beyond tracked buckets

  if raw_bucket present:
    n = parse_int(raw_bucket)     # e.g. "200", "2000", "1000000"
    if n <= 1000: return TOP_1K
    if n <= 5000: return TOP_5K
    if n <= 10000: return TOP_10K
    if n <= 100000: return TOP_100K
    if n <= 1000000: return TOP_1M

  if success and no rank and no bucket:
    return UNRANKED, error=null

  return UNKNOWN, error=no_rank_signal
```

**Live fixtures for tests** (sanitized):

| Fixture | rank | raw_bucket | normalized |
|---------|------|------------|------------|
| `google.com` | 1 | `"200"` | `TOP_100` |
| `example.com` | null | `"200"` | `TOP_1K` |
| synthetic unranked | null | `">200000"` | `UNRANKED` |

**Tightest bucket wins:** store both `cloudflare_rank_raw_bucket` and normalized `cloudflare_rank_bucket`.

---

## 6. Failure behavior (live-informed)

| Condition | `cloudflare_rank_available` | `cloudflare_rank_bucket` | `cloudflare_rank_error` |
|-----------|----------------------------|--------------------------|-------------------------|
| 200 + rank and/or numeric bucket | true | normalized | null |
| 200 + bucket `>N` | false | UNRANKED | null |
| 404 / 7003 | false | UNRANKED | null |
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

1. Mock 200 with rank `1` + bucket `"200"` → `TOP_100` (live `google.com` shape)
2. Mock 200 with bucket `"200"` only → `TOP_1K` (live `example.com` shape)
3. Mock 200 with bucket `">200000"` → `UNRANKED` (live synthetic shape)
4. Mock 404 / error 7003 → `UNRANKED`, no error string
5. Mock 401 → `UNKNOWN`, `auth_failed`
6. Mock 429 → `UNKNOWN`, `rate_limited`; cap stops further calls
7. Feature disabled → no HTTP calls (assert mock not called)
8. Missing token → no HTTP calls, `not_configured`
9. Cache hit → no second HTTP call within TTL
10. Job completion succeeds when Cloudflare fails
11. VT triage fields unchanged (regression)

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
| 1 | Account → Radar → Read works? | **Yes** — 3/3 HTTP 200 |
| 2 | Path exact? | **Yes** |
| 3 | `google.com`? | **rank=1**, bucket=`"200"` → `TOP_100` |
| 4 | `example.com`? | **rank absent**, bucket=`"200"` → `TOP_1K` |
| 5 | Unranked synthetic domain? | **HTTP 200**, bucket=`">200000"` → `UNRANKED` |
| 6 | 404 vs 7003 vs other? | **Not 404** for synthetic; inequality bucket used |
| 7 | Bucket format? | **Numeric strings** and **`>N` inequality labels** |
| 8 | `meta.dateRange`? | **Yes** on all 3 |
| 9 | Stable for MDI-50B? | **Yes** with `>N` handling added |
| 10 | Rate-limit/auth issues? | **None** in this run |

---

## 10. Recommended next step

1. **Approve MDI-50B implementation** using live fixtures in §5 and §8.7.
2. Implement `backend/services/cloudflare_radar.py` with `>N` bucket handling.
3. Merge docs branch when ready; implement on feature branch; do **not** start MDI-50C until MDI-50B deployed.
4. Post-deploy live smoke: same 3 domains, setting enabled, confirm no VT quota change.

---

## 11. Scope reminders

Cloudflare Radar rank is **popularity/blast-radius context only**. It must **not**:

- Make a domain malicious
- Change VT flagged/suspicious logic or `triage_bucket`
- Trigger `serverHold` / `clientHold` or any enforcement
- Automate Salesforce/registrar/takedown actions
