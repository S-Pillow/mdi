# MDI-50A — Cloudflare Radar API Discovery and Data Contract

**Status:** Discovery complete (documentation-only)  
**Date:** 2026-06-24  
**Production baseline:** `a193b4428744df34a557b7096f38c4ce6c2b0cf8` (MDI-52/52A)  
**Live API validation:** Not performed (no Cloudflare API token configured in MDI secrets)

---

## 1. Summary verdict

**Cloudflare Radar can support MDI rank lookup for a future hold-impact guardrail**, with important constraints:

- **Yes** — per-domain rank/bucket lookup is available via the Radar Ranking API.
- **Yes** — a free Cloudflare account with a Radar Read API token appears sufficient (per official docs).
- **Constraint** — exact numeric rank is only reliable for the **global top 100**; most domains receive a **coarse bucket** (e.g. top 2,000 / top 1M) or **no data** (404).
- **Constraint** — ranking reflects **1.1.1.1 DNS popularity**, not maliciousness, reputation, or business criticality.
- **Constraint** — per-domain API calls do not scale to large uploads without **caching**, **rate limiting**, and an **operator opt-in** default-off setting.
- **Not in scope** — Cloudflare URL Scanner, Intel categorization APIs, automated holds, or VT triage changes.

**Recommendation:** Proceed to implementation split **MDI-50B (lookup integration)** then **MDI-50C (hold-impact guardrail UI/rules)** after live API validation with an operator-provided token.

---

## 2. Discovery method

- Official Cloudflare Radar / API documentation review (June 2026 docs).
- MDI repo inspection (no existing Cloudflare integration).
- Secrets presence check: `/etc/dns-tool/secrets.env` exists but contains **zero** `CLOUDFLARE` / `CF_` variables — no live probes performed.
- No production code, config, services, runtime files, or quota touched.

**Primary references:**

- [Cloudflare Radar overview](https://developers.cloudflare.com/radar/)
- [Make your first Radar API request](https://developers.cloudflare.com/radar/get-started/first-request/)
- [Ranking API](https://developers.cloudflare.com/api/resources/radar/subresources/ranking/)
- [Domain ranking datasets](https://developers.cloudflare.com/radar/investigate/domain-ranking-datasets/)
- [Radar API error codes](https://developers.cloudflare.com/radar/get-started/error-codes/)
- [Cloudflare API rate limits](https://developers.cloudflare.com/fundamentals/api/reference/limits/)

---

## 3. Cloudflare product/API identified

| Item | Value |
|------|-------|
| Product | **Cloudflare Radar** |
| API base | `https://api.cloudflare.com/client/v4/radar/` |
| Data source | Aggregated **1.1.1.1 public DNS resolver** query popularity |
| License (Radar API data) | **CC BY-NC 4.0** — operator/legal review recommended before production use |
| Correct for MDI rank guardrail? | **Yes**, for popularity/blast-radius context only |
| Wrong products (out of scope) | URL Scanner, page tech, screenshots, Intel domain categorization as primary rank source |

---

## 4. Endpoint(s) found

### Primary — per-domain lookup (recommended for MDI-50B)

```
GET /client/v4/radar/ranking/domain/{domain}
Authorization: Bearer <API_TOKEN>
```

Optional query parameters:

| Parameter | Purpose |
|-----------|---------|
| `rankingType` | `POPULAR` (default for hold-impact), `TRENDING_RISE`, `TRENDING_STEADY` |
| `date` | Historical date filter |
| `includeTopLocations` | Country-level rank breakdown |
| `format` | `JSON` or `CSV` |

**Batch support:** One domain per path segment. No documented multi-domain batch on this endpoint.

### Secondary — list / historical

| Endpoint | Use case |
|----------|----------|
| `GET /radar/ranking/top` | Ordered top-N list (global/country); not per uploaded domain |
| `GET /radar/ranking/timeseries_groups?domains=...` | Rank history; comma-separated domains; better for analytics than triage |
| `GET /radar/datasets?datasetType=RANKING_BUCKET` | List weekly bucket dataset IDs |
| `GET /radar/datasets/ranking_top_{N}` | Stream newline-delimited domain list for bucket N |
| `POST /radar/datasets/download` | Signed download URL for bucket file |

**MDI note:** Bucket dataset streaming is useful for **local cache / bulk pre-index** (optional future optimization) but is **weekly**, **unordered within bucket**, and **not** a substitute for simple per-row API lookup in MVP.

### Ranking data characteristics (official)

| Data type | Availability |
|-----------|--------------|
| Ordered exact rank | Top **100** globally (and per-country top lists via `top`) |
| Coarse bucket | Domains in buckets: 200, 500, 1K, 2K, 5K, 10K, 20K, 50K, 100K, 200K, 500K, **1M** |
| Top-100 list refresh | **Daily** (last 24h) |
| Bucket datasets refresh | **Weekly** (last 7 days) |

---

## 5. Authentication requirements

| Requirement | Detail |
|-------------|--------|
| Token required | **Yes** — `Authorization: Bearer <token>` |
| Permission | **Account → Radar → Read** (custom token) |
| Account type | Free Cloudflare account documented as sufficient for Radar API |
| Enterprise | Not documented as required for ranking endpoints |
| Secret storage (proposed) | `/etc/dns-tool/secrets.env` — e.g. `CLOUDFLARE_RADAR_API_TOKEN` (**proposed only; not added in MDI-50A**) |
| Token in code/logs | **Never** |

No token was available on the MDI host during discovery; live validation is **pending operator token**.

---

## 6. Rate limits / cost constraints

| Constraint | Value | Source |
|------------|-------|--------|
| Cloudflare global API limit | **1,200 requests / 5 minutes** per user/token | Fundamentals API limits |
| Per-IP limit | 200/sec | Fundamentals API limits |
| Radar-specific daily cap | **Not officially documented** in Cloudflare docs reviewed | — |
| Third-party anecdote | ~10,000 requests/day (unverified) | Community blog; treat as unknown |
| Cost | Documented as **free** Radar API | Radar overview |
| MDI upload risk | 200–300 row CSV × 1 lookup/row could exhaust 5-minute window without cache/throttle | Engineering assessment |

**MDI-50B recommendations:**

- Feature **off by default** (`cloudflare_rank_lookup_enabled: false`).
- Per-job cap (e.g. skip lookup after N domains or on 429).
- In-memory/disk cache keyed by registrable domain + ranking date window.
- Timeout: 5–10s; retries: 1 with backoff on 429/5xx only.
- Never block VT job completion on Cloudflare failure.

---

## 7. Response shape summary

Standard Cloudflare v4 envelope:

```json
{
  "success": true,
  "errors": [],
  "result": { ... },
  "messages": []
}
```

### `GET /radar/ranking/domain/{domain}` (sanitized example from API docs)

```json
{
  "success": true,
  "result": {
    "details_0": {
      "categories": [{ "id": 81, "name": "Content Servers", "superCategoryId": 26 }],
      "bucket": "2000",
      "rank": 3,
      "top_locations": [{ "locationCode": "US", "locationName": "United States", "rank": 1 }]
    },
    "meta": {
      "dateRange": [{ "startTime": "...", "endTime": "..." }]
    }
  }
}
```

**Field notes:**

- `rank` — optional; meaningful for top-100 contexts; may be absent for bucket-only domains.
- `bucket` — optional string; POPULAR ranking, most recent window; values align to bucket sizes (e.g. `"2000"`, `"1000000"`).
- `categories` — often **empty outside top 100** (community + docs); **do not use for MDI hold-impact**.
- `top_locations` — optional; country-level rank; optional for MDI MVP.

---

## 8. Exact fields available (for MDI mapping)

| Cloudflare field | MDI use |
|------------------|---------|
| `result.details_0.rank` | `cloudflare_rank` when present (1–100 trusted) |
| `result.details_0.bucket` | Map to `cloudflare_rank_bucket` |
| `result.meta.dateRange` | `cloudflare_rank_as_of` / staleness context |
| `result.details_0.categories` | **Ignore for guardrail** (incomplete outside top 100) |
| `success` / `errors[]` | Error handling |
| HTTP 404 + error code 7003 | Treat as **UNRANKED** / not in Radar dataset |

---

## 9. Gaps / unknowns

| Gap | Impact | Mitigation |
|-----|--------|------------|
| No live API validation in MDI-50A | Bucket string normalization unverified | MDI-50B smoke with operator token on `google.com`, mid-tier domain, unranked domain |
| 404 vs empty `details_0` for unranked | UNRANKED detection logic | Live test + defensive parsing |
| API vs Radar UI discrepancies | Operator confusion | Document that MDI uses API contract only |
| CC BY-NC 4.0 license | Possible use restriction | Legal/operator sign-off |
| Exact bucket string format | Mapping to TOP_1K etc. | Normalize numeric bucket → enum in MDI-50B |
| Batch upload at scale | Rate limits | Cache, opt-in, per-job caps |
| Historical rank for hold-impact | Low value for MVP | Use current POPULAR only initially |

---

## 10. Proposed MDI data contract

Per result row (or sidecar object), **additive only** — does not alter VT/triage fields:

```json
{
  "cloudflare_rank_available": true,
  "cloudflare_rank": 42,
  "cloudflare_rank_bucket": "TOP_10K",
  "cloudflare_rank_raw_bucket": "10000",
  "cloudflare_rank_source": "cloudflare_radar_popular",
  "cloudflare_rank_checked_at": "2026-06-24T12:00:00Z",
  "cloudflare_rank_as_of_start": "2026-06-23T00:00:00Z",
  "cloudflare_rank_as_of_end": "2026-06-24T00:00:00Z",
  "cloudflare_rank_error": null,
  "hold_impact_level": "high",
  "hold_impact_reason": "Domain is in Cloudflare top 10K by 1.1.1.1 DNS popularity; review blast radius before hold action."
}
```

| Field | Type | Notes |
|-------|------|-------|
| `cloudflare_rank_available` | bool | `true` when lookup succeeded with rank or bucket |
| `cloudflare_rank` | int \| null | Set when API returns `rank` (typically ≤100) |
| `cloudflare_rank_bucket` | string \| null | MDI normalized enum (see §11) |
| `cloudflare_rank_raw_bucket` | string \| null | Raw API `bucket` preserved |
| `cloudflare_rank_source` | string | e.g. `cloudflare_radar_popular` |
| `cloudflare_rank_checked_at` | ISO timestamp \| null | MDI lookup time |
| `cloudflare_rank_error` | string \| null | Sanitized error code/message |
| `hold_impact_level` | enum | MDI-50C derived; not from Cloudflare |
| `hold_impact_reason` | string \| null | Operator-facing; MDI-50C |

---

## 11. Proposed rank bucket model

Normalize API `rank` + `bucket` into MDI enums:

| MDI bucket | Condition (proposed) |
|------------|----------------------|
| `TOP_100` | `rank` present and 1–100 |
| `TOP_1K` | raw bucket ≤ 1000 or rank implied |
| `TOP_5K` | raw bucket ≤ 5000 |
| `TOP_10K` | raw bucket ≤ 10000 |
| `TOP_100K` | raw bucket ≤ 100000 |
| `TOP_1M` | raw bucket ≤ 1000000 |
| `UNRANKED` | 404 / not in any bucket |
| `UNKNOWN` | API error, timeout, or unparsable response |

Mapping uses **smallest bucket that contains the domain** (a domain in bucket `"2000"` is also in TOP_5K, TOP_10K, etc.). MDI should store both `cloudflare_rank_raw_bucket` and normalized `cloudflare_rank_bucket` (recommend storing **tightest** bucket as primary).

---

## 12. Proposed hold-impact interpretation

**Principles (non-negotiable):**

1. Cloudflare rank **does not** make a domain malicious.
2. Cloudflare rank **does not** change VT flagged logic or `triage_bucket`.
3. Cloudflare rank **does not** trigger automated `serverHold` / `clientHold` or any enforcement.
4. Rank is **blast-radius / escalation context** only when an operator considers hold or takedown.

**Proposed `hold_impact_level` (MDI-50C):**

| Level | Suggested condition | Operator guidance |
|-------|---------------------|-------------------|
| `critical` | TOP_100 or TOP_1K | High-traffic domain; senior review before hold |
| `high` | TOP_5K – TOP_10K | Elevated caution; confirm scope and comms |
| `medium` | TOP_100K | Moderate popularity; standard review |
| `low` | TOP_1M | Lower but measurable popularity |
| `none` | UNRANKED | No Radar popularity signal |
| `unknown` | Lookup failed / disabled | Do not infer impact; proceed with existing triage |

Display: badge/warning in drawer and export columns; **no new action buttons** in MVP.

---

## 13. Failure handling recommendation

| Condition | MDI behavior |
|-----------|--------------|
| 401 / 403 | `cloudflare_rank_available=false`, `cloudflare_rank_error=auth_failed`, `hold_impact_level=unknown` |
| 404 / error 7003 | `UNRANKED`, `hold_impact_level=none` |
| 429 | Stop further lookups for job; cache negative; `hold_impact_level=unknown` for skipped rows |
| 5xx / timeout | Retry once; then `unknown`; never fail job |
| Feature disabled | Skip lookup; fields null/absent |
| Missing token | Skip; log at info; settings UI explains requirement |

---

## 14. Security / secrets handling recommendation

- Store token only in `/etc/dns-tool/secrets.env` (same pattern as VT key).
- Load at service startup; never return in API responses.
- Dedicated low-privilege token: **Radar Read** only.
- Redact token from logs, exports, and evidence bundles.
- Optional IP restriction on token in Cloudflare dashboard.

---

## 15. Live API validation performed?

**No.** No operator-approved token or explicit permission for live probes. `/etc/dns-tool/secrets.env` has no Cloudflare variables.

---

## 16. Sanitized live validation summary

N/A — pending MDI-50B pre-implementation smoke with operator token on:

1. `google.com` (expect rank or top bucket)
2. Mid-popularity domain (expect bucket only)
3. Random unregistered/low-traffic domain (expect UNRANKED/404)

---

## 17. Recommended future ticket split

| Ticket | Scope |
|--------|-------|
| **MDI-50B** | Cloudflare Radar rank lookup integration: API client, normalization, cache, settings flag (default off), persist contract fields, unit tests with mocked responses, live smoke script |
| **MDI-50C** | Rank-based hold-impact guardrail: map buckets → `hold_impact_level`, drawer/table/export warnings, docs, operator copy; **no automated hold** |
| **Optional MDI-50B-cache** (only if needed) | Weekly bucket dataset local index for bulk uploads; defer unless rate limits block MVP |

Do **not** combine guardrail rules into MDI-50B; keep lookup and interpretation separate.

---

## 18. Out of scope (confirmed)

- Cloudflare URL Scanner, Intel API, categories, screenshots
- VT / triage / upload / hold detection / quota estimate changes
- Enforcement, Salesforce, registrar automation
- Production deployment in MDI-50A
