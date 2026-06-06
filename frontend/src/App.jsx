import React, { useState, useEffect, useRef, useCallback } from 'react'

// ── Icons (inline SVG — no external icon library) ────────────────────────────

function IconArrowLeft() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>
    </svg>
  )
}
function IconInfo() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>
    </svg>
  )
}
function IconSearch() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
    </svg>
  )
}
function IconCalculator() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="6" x2="16" y2="6"/>
      <line x1="8" y1="10" x2="16" y2="10"/><line x1="8" y1="14" x2="12" y2="14"/>
    </svg>
  )
}
function IconEye() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>
    </svg>
  )
}
function IconGear() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
  )
}
function IconUpload() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
    </svg>
  )
}
function IconRefresh() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
    </svg>
  )
}
function IconMoreVertical() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>
    </svg>
  )
}

// ── Constants ─────────────────────────────────────────────────────────────────

const API_BASE = ''   // same-origin; nginx proxies /api/mdi/ to port 8011
const QUOTA_STALE_MS = 60_000  // refresh quota if older than 60 s before estimate

// ── Pure helper functions ─────────────────────────────────────────────────────
// These functions are pure: they take only result/job data, make no fetch calls,
// make no external calls, and do not mutate their arguments.

// Null-safe value helper
function nv(value, fallback = '—') {
  return value == null || value === '' ? fallback : value
}

// Live status classification (matches backend services/live_check.py _ACTIVE_LIVE and _NO_LIVE)
const LIVE_ACTIVE_SET  = new Set(['active', 'redirect', 'forbidden'])
const LIVE_NO_SET      = new Set(['not_found', 'gone', 'dns_failure', 'connection_refused', 'timeout'])
const RECENT_AGE_SET   = new Set(['very_new', 'new'])
const STALE_FRESH_SET  = new Set(['stale', 'very_stale'])
const FLAGGED_BUCKET_SET = new Set(['malicious', 'suspicious'])

function isFlagged(r)       { return FLAGGED_BUCKET_SET.has(r?.triage_bucket) }
function isLive(r)          { return LIVE_ACTIVE_SET.has(r?.live_status) }
function isNoLive(r)        { return LIVE_NO_SET.has(r?.live_status) }
function isRecentAge(r)     { return RECENT_AGE_SET.has(r?.age_bucket) }
function isStaleFreshness(r){ return STALE_FRESH_SET.has(r?.freshness) }

// Virtual bucket key — used for both card counts and filter predicates.
// Buckets are mutually exclusive in priority order so card totals add up cleanly.
// NOTE: "Flagged+Live+Recent" takes precedence over "Flagged+Live" and "Flagged+Recent".
function getVirtualBucketKey(r) {
  if (!r) return 'unknown'
  const bucket = r.triage_bucket
  if (bucket === 'held') return 'held'
  if (bucket === 'error' || bucket === 'unresolvable' || bucket === 'pending') return 'unknown'
  if (isFlagged(r)) {
    if (isLive(r) && isRecentAge(r)) return 'flr'    // Flagged + Live + Recent
    if (isLive(r))                   return 'fl'     // Flagged + Live
    if (isRecentAge(r))              return 'fr'     // Flagged + Recent
    if (isStaleFreshness(r))         return 'fs'     // Flagged + Stale
    if (isNoLive(r))                 return 'fnl'    // Flagged + No-Live
    return 'flagged'                                  // Flagged catch-all
  }
  if (bucket === 'clean') return 'clean'
  return 'unknown'
}

// Priority rank map.
// THIS MIRRORS backend/services/triage_rules.py priority order.
// Update this map if the backend triage priority changes.
const PRIORITY_RANK = {
  held:    1,
  unknown: 2,   // error / unresolvable / pending
  flr:     3,   // Flagged + Live + Recent
  fl:      4,   // Flagged + Live
  fr:      5,   // Flagged + Recent
  fs:      6,   // Flagged + Stale
  fnl:     7,   // Flagged + No-Live
  flagged: 8,   // Flagged catch-all
  clean:   9,
}
const CONF_RANK = { high: 1, medium: 2, low: 3, clean: 4, unknown: 5 }

function getItemPriority(r) {
  return PRIORITY_RANK[getVirtualBucketKey(r)] ?? 10
}
function comparePriority(a, b) {
  const pa = getItemPriority(a), pb = getItemPriority(b)
  if (pa !== pb) return pa - pb
  const ca = CONF_RANK[a?.triage_confidence] ?? 6
  const cb = CONF_RANK[b?.triage_confidence] ?? 6
  if (ca !== cb) return ca - cb
  return (a?.position ?? 0) - (b?.position ?? 0)
}

// Filter predicates — inclusive (a row may appear under multiple filters)
const FILTER_PREDICATES = {
  all:     () => true,
  held:    r => r?.triage_bucket === 'held',
  flr:     r => isFlagged(r) && isLive(r) && isRecentAge(r),
  fl:      r => isFlagged(r) && isLive(r),
  fr:      r => isFlagged(r) && isRecentAge(r),
  fs:      r => isFlagged(r) && isStaleFreshness(r),
  fnl:     r => isFlagged(r) && isNoLive(r),
  flagged: r => isFlagged(r),
  unknown: r => ['error','unresolvable','pending'].includes(r?.triage_bucket),
  clean:   r => r?.triage_bucket === 'clean',
}

function getFilteredResults(results, filterKey) {
  const pred = FILTER_PREDICATES[filterKey] ?? FILTER_PREDICATES.all
  return results.filter(pred)
}
function getFilterCount(results, filterKey) {
  return getFilteredResults(results, filterKey).length
}

// Card counts use virtual bucket keys (mutually exclusive)
function getTriageCardCounts(results) {
  const counts = { flr: 0, fl: 0, fr: 0, fs: 0, fnl: 0, flagged: 0, unknown: 0, clean: 0, held: 0 }
  for (const r of results) {
    const k = getVirtualBucketKey(r)
    if (k in counts) counts[k]++
  }
  return counts
}

function formatPercent(count, total) {
  if (!total) return '0%'
  return `${((count / total) * 100).toFixed(1)}%`
}
function formatDate(val) {
  if (!val) return '—'
  try {
    const s = String(val).substring(0, 10)
    return s.match(/^\d{4}-\d{2}-\d{2}$/) ? s : '—'
  } catch { return '—' }
}
function formatAgeBucket(val) {
  return { very_new: 'Very new', new: 'New', established: 'Established', mature: 'Mature', unknown: 'Unknown' }[val] ?? (val ?? '—')
}
function formatVtRatio(r) {
  if (r?.vt_ratio) return r.vt_ratio
  if (r?.vt_hits != null && r?.vt_total_engines != null) {
    const pct = r.vt_total_engines > 0 ? ` (${((r.vt_hits / r.vt_total_engines) * 100).toFixed(1)}%)` : ''
    return `${r.vt_hits} / ${r.vt_total_engines}${pct}`
  }
  return '—'
}
function formatLiveStatus(val) {
  const MAP = {
    active: 'LIVE', redirect: 'REDIRECT', forbidden: 'FORBIDDEN',
    not_found: 'NOT FOUND', gone: 'GONE', dns_failure: 'DNS FAIL',
    connection_refused: 'REFUSED', timeout: 'TIMEOUT',
    server_error: 'SRV ERR', blocked: 'BLOCKED',
    unknown: 'UNKNOWN', not_checked: 'NOT CHECKED',
  }
  return MAP[val] ?? (val ?? '—')
}

function fmtDuration(s) {
  if (s == null) return '—'
  if (s < 60) return `${Math.round(s)}s`
  const m = Math.floor(s / 60), sec = Math.round(s % 60)
  return sec > 0 ? `${m}m ${sec}s` : `${m}m`
}

// CSS class helpers
function bucketBadgeClass(bucket) {
  return { malicious: 'badge-malicious', suspicious: 'badge-suspicious', held: 'badge-held',
    clean: 'badge-clean', error: 'badge-error', unresolvable: 'badge-unresolvable', pending: 'badge-pending' }[bucket] ?? 'badge-unresolvable'
}
function virtualBucketBadgeClass(key) {
  return { flr: 'badge-flr', fl: 'badge-fl', fr: 'badge-fr', fs: 'badge-fs', fnl: 'badge-fnl',
    flagged: 'badge-malicious', clean: 'badge-clean', held: 'badge-held', unknown: 'badge-error' }[key] ?? 'badge-unresolvable'
}
function liveBadgeClass(val) {
  if (LIVE_ACTIVE_SET.has(val)) return 'badge-live'
  if (LIVE_NO_SET.has(val)) return 'badge-no-live'
  return 'badge-live-unknown'
}
function freshnessBadgeClass(val) {
  return { fresh: 'badge-fresh', stale: 'badge-stale', very_stale: 'badge-very-stale',
    never_scanned: 'badge-never-scanned' }[val] ?? 'badge-live-unknown'
}
function evidenceBadgeClass(val) {
  return { complete: 'badge-complete', partial: 'badge-partial',
    skipped_hold: 'badge-skipped-hold', none: 'badge-none-ev' }[val] ?? 'badge-none-ev'
}
function confClass(val) {
  return { high: 'conf-high', medium: 'conf-medium', low: 'conf-low',
    clean: 'conf-clean', unknown: 'conf-unknown' }[val] ?? 'conf-unknown'
}
function rowTierClass(r) {
  const k = getVirtualBucketKey(r)
  if (k === 'flr') return 'tier-critical'
  if (k === 'fl' || k === 'fr') return 'tier-high'
  if (k === 'fs' || k === 'flagged') return 'tier-medium'
  if (k === 'fnl') return 'tier-low'
  if (k === 'unknown' || k === 'held') return 'tier-info'
  if (k === 'clean') return 'tier-clean'
  return 'tier-none'
}
function triageColor(bucket) {
  return { malicious: 'var(--risk-critical)', suspicious: 'var(--risk-medium)', held: '#C4B5FD',
    clean: 'var(--risk-clean)', error: 'var(--risk-critical)', unresolvable: 'var(--text-muted)', pending: 'var(--text-faint)' }[bucket] ?? 'var(--text-muted)'
}

// Card definitions
const TRIAGE_CARDS = [
  { key: 'flr',     label: 'Flagged + Live + Recent', color: 'var(--c-flr)', filter: 'flr' },
  { key: 'fl',      label: 'Flagged + Live',           color: 'var(--c-fl)',  filter: 'fl'  },
  { key: 'fr',      label: 'Flagged + Recent',         color: 'var(--c-fr)', filter: 'fr'  },
  { key: 'fs',      label: 'Flagged + Stale',          color: 'var(--c-fs)', filter: 'fs'  },
  { key: 'fnl',     label: 'Flagged + No-Live',        color: 'var(--c-fnl)',filter: 'fnl' },
  { key: 'unknown', label: 'Unknown / Errors',         color: 'var(--c-unk)',filter: 'unknown' },
  { key: 'clean',   label: 'Clean',                    color: 'var(--c-cln)',filter: 'clean' },
]

// Named filters for the secondary filter bar
const NAMED_FILTERS = [
  { key: 'all',     label: 'All' },
  { key: 'held',    label: 'Domain On Hold' },
  { key: 'flr',     label: 'Flagged + Live + Recent' },
  { key: 'fl',      label: 'Flagged + Live' },
  { key: 'fr',      label: 'Flagged + Recent' },
  { key: 'fs',      label: 'Flagged + Stale' },
  { key: 'fnl',     label: 'Flagged + No-Live' },
  { key: 'flagged', label: 'All Flagged' },
  { key: 'unknown', label: 'Unknown / Errors' },
  { key: 'clean',   label: 'Clean' },
]

// ── QuotaWidget (nav bar compact version) ─────────────────────────────────────

function QuotaNavWidget({ quota, loading, error }) {
  if (loading && !quota) {
    return <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Checking quota…</span>
  }
  if (error && !quota) {
    return <span style={{ fontSize: 11, color: 'var(--status-warning)' }} title={error}>⚠ Quota unavailable</span>
  }
  if (!quota) return null

  const used      = quota.daily_lookups_used ?? 0
  const limit     = quota.daily_limit ?? 500
  const remaining = quota.remaining ?? (limit - used)
  const pct       = Math.min(Math.round((used / limit) * 100), 100)
  const barColor  = remaining <= 0 ? 'var(--risk-critical)' : remaining < 25 ? 'var(--risk-critical)' : remaining < 100 ? 'var(--risk-medium)' : 'var(--risk-clean)'
  const valColor  = remaining <= 0 ? 'var(--risk-critical)' : remaining < 25 ? 'var(--risk-critical)' : remaining < 100 ? 'var(--risk-medium)' : 'var(--text-main)'
  const checkedStr = quota.checkedAt
    ? new Date(quota.checkedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null

  return (
    <div className="quota-nav-widget" title={`VT quota — shared by MDI and VT Bulk Check${checkedStr ? `. Last checked: ${checkedStr}` : ''}`}>
      <span className="quota-label">VT Quota</span>
      <span className="quota-value" style={{ color: valColor }}>
        {used}<span style={{ color: 'var(--text-faint)' }}>/{limit}</span>
      </span>
      <div className="quota-bar-wrap">
        <div className="quota-bar-fill" style={{ width: `${pct}%`, background: barColor }} />
      </div>
      {remaining <= 0
        ? <span style={{ color: 'var(--risk-critical)', fontWeight: 700, fontSize: 11 }}>EXHAUSTED</span>
        : <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{remaining} left</span>
      }
    </div>
  )
}

// ── Settings panel (compact right-anchored dropdown) ──────────────────────────

function CollapsibleSettingsPanel({
  open, id,
  useDomainReports, setUseDomainReports,
  staleThresholdDays, setStaleThresholdDays,
  locked,
}) {
  if (!open) return null
  const ctrlLocked = locked ? { opacity: 0.55, pointerEvents: 'none' } : {}

  return (
    <div className="settings-panel" id={id} role="region" aria-label="MDI Settings">
      <div className="settings-panel-header">
        <span className="settings-panel-title">MDI Settings</span>
        {locked && <span style={{ fontSize: 10, color: 'var(--status-warning)', fontStyle: 'italic' }}>Locked</span>}
      </div>
      <div className="settings-panel-body">
        {locked && (
          <p className="settings-panel-locked-msg">
            Settings locked while a job is active or restored. Clear current results to change settings.
          </p>
        )}

        {/* Section: VT Processing */}
        <div>
          <p className="settings-section-label">VT Processing</p>
          <div style={ctrlLocked}>
            <div className="settings-row" style={{ marginTop: 8 }}>
              <div className="settings-row-info">
                <span className="settings-row-name">VT Report Mode</span>
                <span className="settings-row-desc">
                  {useDomainReports
                    ? 'Domain report — 1 VT call per domain, less detail'
                    : 'URL report (recommended) — up to 3 VT calls, better coverage'}
                </span>
              </div>
              <div className="settings-row-ctrl" style={{ marginLeft: 12 }}>
                <button
                  className="btn btn-ghost"
                  style={{ fontSize: 11, padding: '4px 10px', whiteSpace: 'nowrap' }}
                  onClick={() => setUseDomainReports(v => !v)}
                  disabled={locked}
                  title={locked ? 'Settings locked while a job is active' : undefined}
                >
                  {useDomainReports ? 'Domain' : 'URL'}
                </button>
              </div>
            </div>

            <div className="settings-row" style={{ marginTop: 10 }}>
              <div className="settings-row-info">
                <span className="settings-row-name">Stale threshold</span>
                <span className="settings-row-desc">VT reports older than this are classified STALE. Default: 7 days.</span>
              </div>
              <div className="settings-row-ctrl" style={{ marginLeft: 12, gap: 6, display: 'flex', alignItems: 'center' }}>
                <input
                  type="number" min={1} max={90}
                  value={staleThresholdDays}
                  onChange={e => {
                    const v = parseInt(e.target.value, 10)
                    if (!isNaN(v) && v >= 1 && v <= 90) setStaleThresholdDays(v)
                  }}
                  disabled={locked}
                  className="settings-number-input"
                />
                <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>days</span>
              </div>
            </div>
          </div>
        </div>

        {/* Section: Coming soon */}
        <div>
          <p className="settings-section-label">Coming soon</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
            <span className="settings-placeholder" title="Auto-rescan stale items — not yet available">
              ↺ Auto-rescan stale items
            </span>
            <span className="settings-placeholder" title="URL activity check setting — not yet available">
              🔗 URL activity check
            </span>
            <span className="settings-placeholder" title="Export options — available in MDI-16">
              ↑ Export options (MDI-16)
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Inline validation summary (rendered inside InputSection) ──────────────────

function ValidationSummary({ validating, preview, previewError, onRefresh }) {
  const [showRejected, setShowRejected] = useState(false)
  const [showDupes, setShowDupes]       = useState(false)

  if (validating) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', fontSize: 11, color: 'var(--text-muted)' }}>
        <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block', fontSize: 12 }}>↻</span>
        Validating input…
      </div>
    )
  }
  if (previewError) {
    return (
      <div style={{ fontSize: 11, color: 'var(--risk-critical)', padding: '6px 0' }}>
        Validation error: {previewError}
        <button className="btn btn-ghost" style={{ fontSize: 10, padding: '2px 8px', marginLeft: 8 }} onClick={onRefresh}>Retry</button>
      </div>
    )
  }
  if (!preview) return null

  const accepted = preview.accepted_count ?? 0
  const rejected = preview.rejected_count ?? 0
  const dupes    = preview.duplicate_count ?? 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {/* Compact counts row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', fontSize: 12 }}>
        <span style={{ color: accepted > 0 ? 'var(--risk-clean)' : 'var(--text-muted)', fontWeight: accepted > 0 ? 700 : 400 }}>
          ✓ {accepted} accepted
        </span>
        {rejected > 0 && (
          <span style={{ color: 'var(--risk-critical)', fontWeight: 600 }}>
            ✗ {rejected} rejected
          </span>
        )}
        {dupes > 0 && (
          <span style={{ color: 'var(--risk-medium)' }}>
            ⊘ {dupes} duplicate{dupes !== 1 ? 's' : ''} removed
          </span>
        )}
        {/* Expandable toggles */}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          {rejected > 0 && (
            <button className="btn btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }} onClick={() => setShowRejected(v => !v)}>
              {showRejected ? 'Hide' : 'Show'} rejected
            </button>
          )}
          {dupes > 0 && (
            <button className="btn btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }} onClick={() => setShowDupes(v => !v)}>
              {showDupes ? 'Hide' : 'Show'} dupes
            </button>
          )}
        </span>
      </div>
      {/* Rejected details */}
      {showRejected && preview.rejected?.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-secondary)', maxHeight: 100, overflowY: 'auto', background: 'var(--bg-input)', border: '1px solid var(--border-soft)', borderRadius: 4, padding: '6px 10px' }}>
          {preview.rejected.map((r, i) => (
            <div key={i}><code style={{ color: 'var(--risk-critical)', fontFamily: 'Menlo,Consolas,monospace' }}>{r.original}</code> — {r.reason}</div>
          ))}
        </div>
      )}
      {/* Duplicate details */}
      {showDupes && preview.duplicates?.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', maxHeight: 70, overflowY: 'auto', background: 'var(--bg-input)', border: '1px solid var(--border-soft)', borderRadius: 4, padding: '6px 10px' }}>
          {preview.duplicates.map((d, i) => <div key={i}><code style={{ fontFamily: 'Menlo,Consolas,monospace' }}>{d}</code></div>)}
        </div>
      )}
    </div>
  )
}

// ── Input section ─────────────────────────────────────────────────────────────

function InputSection({
  rawInput, setRawInput,
  validating, preview, previewError, onRefreshValidation,
  onClear,
  fileRef, selectedFile, onFileChange, onUploadPreview, uploadPreviewing,
  onRunJob, submitting, canRunJob,
  onEstimate, estimating,
}) {
  const hasInput = rawInput.trim().length > 0

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Input</span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Paste domains/URLs or upload CSV/XLSX · up to 500 items
        </span>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

        {/* ── Paste area ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <textarea
            className="input-area"
            value={rawInput}
            onChange={e => setRawInput(e.target.value)}
            placeholder="Paste domains or URLs — one per line, comma-separated, or space-separated."
            spellCheck={false}
            autoComplete="off"
          />
          {/* Inline auto-validation summary */}
          {hasInput && (
            <ValidationSummary
              validating={validating}
              preview={preview}
              previewError={previewError}
              onRefresh={onRefreshValidation}
            />
          )}
        </div>

        {/* ── Upload area ── */}
        <div style={{ borderTop: '1px solid var(--border-soft)', paddingTop: 12 }}>
          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
            Or upload a CSV or XLSX file (Domain / DNS Form column required)
          </p>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <label className="btn btn-ghost" style={{ cursor: 'pointer', fontSize: 11, padding: '4px 10px' }}>
              Choose file
              <input ref={fileRef} type="file" accept=".csv,.xlsx,.xlsm" style={{ display: 'none' }} onChange={onFileChange} />
            </label>
            {selectedFile && (
              <span style={{ fontSize: 11, color: 'var(--text-secondary)', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {selectedFile.name}
              </span>
            )}
            <button className="btn btn-ghost" onClick={onUploadPreview} disabled={uploadPreviewing || !selectedFile} style={{ fontSize: 11 }}>
              <IconUpload /> {uploadPreviewing ? 'Validating…' : 'Validate Upload'}
            </button>
          </div>
        </div>

        {/* ── Actions row ── */}
        <div style={{ borderTop: '1px solid var(--border-soft)', paddingTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {/* Primary: Estimate */}
          <button
            className="btn btn-ghost"
            onClick={onEstimate}
            disabled={estimating || !canRunJob}
            title={!canRunJob ? 'Paste input and wait for validation' : undefined}
          >
            <IconCalculator /> {estimating ? 'Estimating…' : 'Estimate Quota & Runtime'}
          </button>

          {/* Primary: Run */}
          <button
            className="btn btn-primary"
            onClick={onRunJob}
            disabled={submitting || !canRunJob}
          >
            <IconSearch /> {submitting ? 'Submitting…' : 'Run MDI Check'}
          </button>

          {/* Secondary: Clear */}
          {hasInput && (
            <button className="btn btn-ghost" onClick={onClear} style={{ fontSize: 11 }}>
              Clear
            </button>
          )}

          {/* Tertiary: Refresh Validation — subtle, only shown when input exists */}
          {hasInput && !validating && (
            <button
              className="btn btn-ghost"
              onClick={onRefreshValidation}
              style={{ fontSize: 10, padding: '3px 8px', color: 'var(--text-faint)', borderColor: 'var(--border-soft)', marginLeft: 'auto' }}
              title="Re-run input validation"
            >
              ↺ Refresh validation
            </button>
          )}

          {/* Helper text when not runnable */}
          {!canRunJob && !submitting && !validating && hasInput && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: canRunJob ? 'auto' : 0 }}>
              {previewError ? 'Fix validation errors above.' : 'No accepted items yet.'}
            </span>
          )}
          {!hasInput && (
            <span style={{ fontSize: 11, color: 'var(--text-faint)', marginLeft: 'auto' }}>
              Validation runs automatically · no quota consumed
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// PreviewResultsSection removed — validation is now inline inside InputSection
// via the ValidationSummary component with debounced auto-parse.

// ── Upload preview results ────────────────────────────────────────────────────

function UploadPreviewResultsSection({ preview, error }) {
  const [showRejected, setShowRejected] = useState(false)
  const [showDupes, setShowDupes] = useState(false)
  const [showHeld, setShowHeld] = useState(true)

  if (error) {
    return (
      <div className="card">
        <div className="card-header"><span className="card-label">Upload Validation</span></div>
        <div className="card-body">
          <p style={{ color: 'var(--risk-critical)', fontSize: 13 }}>Upload error: {error}</p>
        </div>
      </div>
    )
  }
  if (!preview) return null

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Upload Validation</span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          No external calls — no quota consumed
        </span>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div className="summary-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
          {[
            { label: 'Accepted', value: preview.accepted_count, color: 'var(--ok)' },
            { label: 'Rejected', value: preview.rejected_count, color: preview.rejected_count > 0 ? 'var(--danger)' : 'var(--text-muted)' },
            { label: 'Duplicates', value: preview.duplicate_count, color: 'var(--text-muted)' },
            { label: 'Hold-skipped', value: preview.held_skipped_count ?? 0, color: '#818cf8' },
          ].map(t => (
            <div key={t.label} className="summary-tile">
              <span className="tile-label">{t.label}</span>
              <span className="tile-value" style={{ color: t.color, fontSize: 18 }}>{t.value}</span>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {preview.rejected_count > 0 && (
            <button className="btn btn-ghost" style={{ fontSize: 11 }} onClick={() => setShowRejected(v => !v)}>
              {showRejected ? 'Hide' : 'Show'} rejected
            </button>
          )}
          {preview.duplicate_count > 0 && (
            <button className="btn btn-ghost" style={{ fontSize: 11 }} onClick={() => setShowDupes(v => !v)}>
              {showDupes ? 'Hide' : 'Show'} dupes
            </button>
          )}
          {(preview.held_skipped_count ?? 0) > 0 && (
            <button className="btn btn-ghost" style={{ fontSize: 11 }} onClick={() => setShowHeld(v => !v)}>
              {showHeld ? 'Hide' : 'Show'} held ({preview.held_skipped_count})
            </button>
          )}
        </div>
        {showHeld && preview.held_items?.length > 0 && (
          <div>
            <p style={{ fontSize: 11, color: '#818cf8', marginBottom: 6 }}>Hold-skipped domains (not submitted to VT):</p>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr>{['#', 'Domain', 'Hold Type', 'Registrar', 'Created', 'Action'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '4px 8px', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontWeight: 600 }}>{h}</th>
                ))}</tr>
              </thead>
              <tbody>
                {preview.held_items.map((r, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '4px 8px', color: 'var(--text-dim)' }}>{r.position}</td>
                    <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>{r.input_normalized}</td>
                    <td style={{ padding: '4px 8px', color: '#818cf8' }}>{r.domain_hold?.hold_types?.join(', ') || '—'}</td>
                    <td style={{ padding: '4px 8px', color: 'var(--text-muted)' }}>{r.registrar ?? '—'}</td>
                    <td style={{ padding: '4px 8px', color: 'var(--text-muted)' }}>{formatDate(r.created_at)}</td>
                    <td style={{ padding: '4px 8px', color: 'var(--text-muted)' }}>{r.recommended_action ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Estimate section ──────────────────────────────────────────────────────────

function Row({ label, value, note, bold, color, warn }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12 }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontFamily: 'monospace', fontWeight: bold ? 700 : 400, color: warn ? 'var(--warn)' : color ?? 'var(--text)' }}>
        {value}{note && <span style={{ color: 'var(--text-dim)', fontWeight: 400, fontFamily: 'inherit' }}> ({note})</span>}
      </span>
    </div>
  )
}

function EstimateSection({ estimate, error, stale }) {
  if (error) {
    return (
      <div className="card">
        <div className="card-header"><span className="card-label">Quota &amp; Runtime Estimate</span></div>
        <div className="card-body">
          <p style={{ color: 'var(--danger)', fontSize: 13 }}>Estimate error: {error}</p>
        </div>
      </div>
    )
  }
  if (!estimate) return null

  const {
    accepted_count, rejected_count, duplicate_count,
    eligible_vt_count, held_skipped_count,
    domain_count, url_count, domain_report_mode_count, url_report_mode_count,
    estimated_vt_calls_min, estimated_vt_calls_max,
    quota_remaining_now, will_exceed_quota, quota_headroom,
    estimated_duration_seconds_min, estimated_duration_seconds_max,
    rate_limit_note, job_state_note, live_check_note,
  } = estimate

  return (
    <div className="card" style={{ borderColor: will_exceed_quota ? 'var(--danger)' : stale ? 'var(--warn)' : undefined }}>
      <div className="card-header">
        <span className="card-label">Quota &amp; Runtime Estimate</span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Estimate only — no VT calls, no quota consumed</span>
        {stale && <span style={{ fontSize: 11, color: 'var(--warn)', fontWeight: 600 }}>⚠ Input changed — estimate outdated</span>}
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {will_exceed_quota && (
          <div style={{ padding: '8px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.4)', color: '#FCA5A5', display: 'flex', gap: 8, alignItems: 'center' }}>
            <span>⛔</span>
            <span>Worst-case estimate ({estimated_vt_calls_max} VT calls) exceeds remaining quota ({quota_remaining_now}). Submission will be blocked.</span>
          </div>
        )}
        <div className="summary-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
          {[
            { label: 'Accepted',    value: accepted_count,    color: accepted_count > 0 ? 'var(--ok)' : 'var(--text-muted)' },
            { label: 'Eligible VT', value: eligible_vt_count, color: eligible_vt_count > 0 ? 'var(--ok)' : 'var(--text-muted)' },
            { label: 'Rejected',    value: rejected_count,    color: rejected_count > 0 ? 'var(--danger)' : 'var(--text-muted)' },
            { label: 'Duplicates',  value: duplicate_count,   color: duplicate_count > 0 ? 'var(--warn)' : 'var(--text-muted)' },
          ].map(t => (
            <div key={t.label} className="summary-tile">
              <span className="tile-label">{t.label}</span>
              <span className="tile-value" style={{ color: t.color, fontSize: 18 }}>{t.value}</span>
            </div>
          ))}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 6, padding: '10px 14px', fontSize: 12 }}>
            <p style={{ color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600 }}>VT call estimate</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <Row label="Best case" value={`${estimated_vt_calls_min} call${estimated_vt_calls_min !== 1 ? 's' : ''}`} />
              <Row label="Worst case" value={`${estimated_vt_calls_max} call${estimated_vt_calls_max !== 1 ? 's' : ''}`} bold />
              <Row label="Quota remaining" value={quota_remaining_now} />
              <Row label="Headroom" value={quota_headroom >= 0 ? `+${quota_headroom}` : String(quota_headroom)} color={quota_headroom >= 0 ? 'var(--ok)' : 'var(--danger)'} />
            </div>
          </div>
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 6, padding: '10px 14px', fontSize: 12 }}>
            <p style={{ color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600 }}>Estimated runtime</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <Row label="Best case" value={fmtDuration(estimated_duration_seconds_min)} />
              <Row label="Worst case" value={fmtDuration(estimated_duration_seconds_max)} />
              {held_skipped_count > 0 && <Row label="Hold-skipped" value={held_skipped_count} note="0 calls" warn />}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <p style={{ fontSize: 11, color: 'var(--text-muted)' }}><strong style={{ color: 'var(--text-secondary)' }}>Rate limit:</strong> {rate_limit_note}</p>
          <p style={{ fontSize: 11, color: 'var(--status-warning)' }}><strong>Job state:</strong> {job_state_note}</p>
          {live_check_note && <p style={{ fontSize: 11, color: 'var(--text-muted)' }}><strong style={{ color: 'var(--text-secondary)' }}>Live checks:</strong> {live_check_note}</p>}
        </div>
      </div>
    </div>
  )
}

// ── Triage summary cards ──────────────────────────────────────────────────────

function TriageSummaryCards({ results, activeFilter, onFilterChange }) {
  const counts = getTriageCardCounts(results)
  const total = results.length

  return (
    <div className="triage-cards-row" role="group" aria-label="Triage summary — click to filter">
      {TRIAGE_CARDS.map(card => {
        const count = counts[card.key] ?? 0
        const isActive = activeFilter === card.filter
        const isMuted = count === 0 && !isActive
        return (
          <button
            key={card.key}
            data-key={card.key}
            className={`triage-card${isActive ? ' active' : ''}${isMuted ? ' muted' : ''}`}
            style={{ borderLeftColor: card.color }}
            onClick={() => onFilterChange(isActive ? 'all' : card.filter)}
            aria-pressed={isActive}
            title={`Filter by: ${card.label} (${count} item${count !== 1 ? 's' : ''})`}
          >
            <span className="tc-label">{card.label}</span>
            <span className="tc-count" style={{ color: count > 0 ? card.color : 'var(--text-faint)' }}>{count}</span>
            <span className="tc-pct">{formatPercent(count, total)}</span>
          </button>
        )
      })}
    </div>
  )
}

// ── Filter bar ────────────────────────────────────────────────────────────────

function FilterBar({ results, activeFilter, onFilterChange }) {
  return (
    <div className="filter-bar" role="group" aria-label="Result filters">
      {NAMED_FILTERS.map(f => {
        const count = getFilterCount(results, f.key)
        const isActive = activeFilter === f.key
        const isZero = count === 0 && f.key !== 'all'
        return (
          <button
            key={f.key}
            className={`filter-btn${isActive ? ' active' : ''}${isZero ? ' zero' : ''}`}
            style={isActive ? { borderColor: 'var(--accent)', color: 'var(--text)' } : {}}
            onClick={() => onFilterChange(isActive && f.key !== 'all' ? 'all' : f.key)}
            aria-pressed={isActive}
          >
            {f.label}
            <span className="filter-count">{f.key === 'all' ? results.length : count}</span>
          </button>
        )
      })}
    </div>
  )
}

// ── Bulk controls ─────────────────────────────────────────────────────────────

function BulkControls({ selectedCount }) {
  return (
    <div className="bulk-controls">
      <span className="bulk-label">Bulk actions:</span>
      <button className="btn-stub" disabled aria-disabled="true" title="Bulk actions — select rows first">
        Actions {selectedCount > 0 ? `(${selectedCount})` : '▾'}
      </button>
      <button className="btn-stub" disabled aria-disabled="true" title="Export available in MDI-16">
        <IconUpload /> Export Flagged
      </button>
      <button className="btn-stub" disabled aria-disabled="true" title="Export available in MDI-16">
        <IconUpload /> Export All
      </button>
      <button className="btn-stub" disabled aria-disabled="true" title="Rescan not yet available">
        <IconRefresh /> Rescan Selected
      </button>
      <button className="btn-stub" disabled aria-disabled="true" title="Rescan not yet available">
        <IconRefresh /> Rescan Stale
      </button>
    </div>
  )
}

// ── Operations results table ──────────────────────────────────────────────────

function ResultsTable({ results, selectedIds, onToggleSelect, onToggleAll }) {
  const allSelected = results.length > 0 && results.every(r => selectedIds.has(r.position))

  return (
    <div className="ops-table-wrap">
      <table className="ops-table">
        <thead>
          <tr>
            <th scope="col" style={{ width: 32, paddingLeft: 10 }}>
              <input
                type="checkbox"
                checked={allSelected}
                onChange={e => onToggleAll(e.target.checked, results)}
                aria-label="Select all visible rows"
                title="Selection reserved for future bulk actions"
              />
            </th>
            <th scope="col" style={{ width: 36 }}>#</th>
            <th scope="col" style={{ minWidth: 180 }}>Domain / URL</th>
            <th scope="col" style={{ minWidth: 140 }}>Triage Bucket</th>
            <th scope="col">Confidence</th>
            <th scope="col" style={{ minWidth: 130 }}>Recommended Action</th>
            <th scope="col">VT Ratio</th>
            <th scope="col">Freshness</th>
            <th scope="col">Live</th>
            <th scope="col">Created</th>
            <th scope="col">Age</th>
            <th scope="col">Evidence</th>
            <th scope="col" style={{ width: 70 }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {results.map(r => {
            const isSelected = selectedIds.has(r.position)
            const vbKey = getVirtualBucketKey(r)
            const bucket = r.triage_bucket ?? 'pending'
            const hasErrors = r.errors?.length > 0
            return (
              <tr
                key={r.position}
                className={`${rowTierClass(r)}${isSelected ? ' row-selected' : ''}`}
                data-bucket={bucket}
              >
                <td className="accent-cell" style={{ paddingLeft: 8 }}>
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => onToggleSelect(r.position)}
                    aria-label={`Select ${r.input_normalized}`}
                    title="Selection reserved for future bulk actions"
                  />
                </td>
                <td style={{ color: 'var(--text-faint)', textAlign: 'center', fontVariantNumeric: 'tabular-nums' }}>{r.position}</td>
                <td>
                  <code
                    style={{ fontFamily: 'Menlo,Consolas,monospace', fontSize: 11, display: 'block', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-main)' }}
                    title={r.input_normalized}
                  >
                    {r.input_normalized}
                  </code>
                </td>
                <td>
                  <span className={`badge ${bucketBadgeClass(bucket)}`} style={{ textTransform: 'uppercase' }}>
                    {bucket}
                  </span>
                  {Array.isArray(r.triage_reason) && r.triage_reason.length > 0 && (
                    <details className="triage-reasons">
                      <summary>Reasons ▾</summary>
                      <ul>
                        {r.triage_reason.map((t, i) => <li key={i}>{t}</li>)}
                      </ul>
                    </details>
                  )}
                </td>
                <td>
                  <span className={confClass(r.triage_confidence)}>
                    {r.triage_confidence ? r.triage_confidence.charAt(0).toUpperCase() + r.triage_confidence.slice(1) : '—'}
                  </span>
                </td>
                <td style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {r.recommended_action ? r.recommended_action.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : '—'}
                </td>
                <td style={{ fontFamily: 'Menlo,Consolas,monospace', color: (r.vt_hits ?? 0) > 0 ? '#FCA5A5' : 'var(--text-secondary)', fontSize: 11, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                  {formatVtRatio(r)}
                </td>
                <td>
                  {r.freshness ? (
                    <span className={`badge ${freshnessBadgeClass(r.freshness)}`}>
                      {r.freshness.replace(/_/g, ' ')}
                    </span>
                  ) : <span style={{ color: 'var(--text-dim)' }}>—</span>}
                </td>
                <td>
                  {r.live_status && r.live_status !== 'not_checked' ? (
                    <span className={`badge ${liveBadgeClass(r.live_status)}`}>
                      {formatLiveStatus(r.live_status)}
                    </span>
                  ) : <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>—</span>}
                </td>
                <td style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                  {formatDate(r.created_at)}
                </td>
                <td style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                  {formatAgeBucket(r.age_bucket)}
                </td>
                <td>
                  {r.evidence_status ? (
                    <span className={`badge ${evidenceBadgeClass(r.evidence_status)}`}>
                      {r.evidence_status.replace(/_/g, ' ')}
                    </span>
                  ) : <span style={{ color: 'var(--text-dim)' }}>—</span>}
                  {hasErrors && <span style={{ color: 'var(--warn)', marginLeft: 4, fontSize: 10 }} title={r.errors.join('; ')}>⚠</span>}
                </td>
                <td>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button
                      className="btn-stub"
                      style={{ padding: '3px 6px' }}
                      disabled
                      aria-disabled="true"
                      title="Detail view — coming soon (MDI-14)"
                    >
                      <IconEye />
                    </button>
                    <button
                      className="btn-stub"
                      style={{ padding: '3px 6px' }}
                      disabled
                      aria-disabled="true"
                      title="More actions — coming soon"
                    >
                      <IconMoreVertical />
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Job section ───────────────────────────────────────────────────────────────

function JobSection({ job, jobError, jobId, restoredFromSession, onDismissRestore }) {
  const [activeFilter, setActiveFilter] = useState('all')
  const [selectedIds, setSelectedIds] = useState(new Set())

  // Reset selection and filter when job changes
  useEffect(() => {
    setActiveFilter('all')
    setSelectedIds(new Set())
  }, [jobId])

  function handleFilterChange(key) {
    setActiveFilter(key)
    setSelectedIds(new Set())
  }
  function handleToggleSelect(pos) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      next.has(pos) ? next.delete(pos) : next.add(pos)
      return next
    })
  }
  function handleToggleAll(checked, visibleResults) {
    setSelectedIds(checked ? new Set(visibleResults.map(r => r.position)) : new Set())
  }

  if (jobError) {
    return (
      <div className="card">
        <div className="card-header"><span className="card-label">VT Job</span></div>
        <div className="card-body">
          <p style={{ color: 'var(--danger)', fontSize: 13 }}>Submit error: {jobError}</p>
        </div>
      </div>
    )
  }
  if (!job && !jobId) return null

  const done      = job ? (job.processed ?? 0) : 0
  const total     = job ? (job.total ?? 0) : 0
  const pct       = total > 0 ? Math.round((done / total) * 100) : 0
  const allResults = job?.results ?? []
  // Sort by priority before filtering
  const prioritySorted = [...allResults].sort(comparePriority)
  const filteredResults = getFilteredResults(prioritySorted, activeFilter)
  const isComplete = job?.status === 'done' || job?.status === 'error'
  const isRunning  = job?.status === 'running' || job?.status === 'queued'

  const statusColor = { queued: 'var(--text-muted)', running: 'var(--accent-blue)', done: 'var(--risk-clean)', error: 'var(--risk-critical)' }[job?.status] ?? 'var(--text-muted)'

  return (
    <div className="card">
      <div className="card-header" style={{ flexWrap: 'wrap' }}>
        <span className="card-label">Triage Results</span>
        {restoredFromSession && (
          <span style={{ fontSize: 11, color: 'var(--risk-clean)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
            ↩ Restored from last session
            <button
              onClick={onDismissRestore}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-faint)', fontSize: 11, padding: '0 2px' }}
              title="Dismiss"
            >✕</button>
          </span>
        )}
        {job && (
          <span style={{ fontSize: 11, color: statusColor, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {job.status}
          </span>
        )}
        {job && (
          <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
            Job: <code style={{ fontSize: 10 }}>{jobId}</code>
          </span>
        )}
      </div>

      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

        {/* Progress bar */}
        {job && total > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-secondary)' }}>
              <span>
                {isRunning ? `Processing… ${done} / ${total} complete` : `${done} / ${total} processed`}
              </span>
              <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{pct}%</span>
            </div>
            <div className="progress-track">
              <div className="progress-fill" style={{
                width: `${pct}%`,
                background: isComplete && job.status === 'error' ? 'var(--risk-critical)' : isComplete ? 'var(--risk-clean)' : 'var(--accent-blue)'
              }} />
            </div>
          </div>
        )}

        {/* Job settings summary */}
        {job && isComplete && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '6px 12px', background: 'var(--bg-elevated)', borderRadius: 4, border: '1px solid var(--border-soft)', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <span><strong style={{ color: 'var(--text-secondary)' }}>Mode:</strong> {job.use_domain_reports ? 'Domain report' : 'URL report'}</span>
            <span><strong style={{ color: 'var(--text-secondary)' }}>Stale after:</strong> {job.stale_threshold_days ?? 7} days</span>
            <span><strong style={{ color: 'var(--text-secondary)' }}>VT calls used:</strong> {job.lookups_used ?? 0}</span>
            {restoredFromSession && <span style={{ color: 'var(--risk-clean)', fontStyle: 'italic' }}>↩ recovered</span>}
          </div>
        )}

        {/* Enrichment + live-check counters */}
        {job && (
          (() => {
            const lcc  = job.live_check_count ?? 0
            const lcsk = job.live_check_skipped_count ?? 0
            const lce  = job.live_check_error_count ?? 0
            const rdap = job.rdap_enriched_count ?? 0
            const anyLive = lcc > 0 || lcsk > 0 || lce > 0
            const anyRdap = rdap > 0
            if (!anyLive && !anyRdap) return null
            return (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '6px 12px', background: 'var(--bg-elevated)', borderRadius: 4, border: '1px solid var(--border-soft)', display: 'flex', flexWrap: 'wrap', gap: '4px 20px' }}>
                {anyRdap && <span>RDAP enriched: <strong style={{ color: 'var(--text-secondary)' }}>{rdap}</strong></span>}
                {anyLive && <>
                  <span>Live checks run: <strong style={{ color: lcc > 0 ? 'var(--status-info)' : 'var(--text-muted)' }}>{lcc}</strong></span>
                  <span>Live checks skipped: <strong style={{ color: 'var(--text-muted)' }}>{lcsk}</strong></span>
                  {lce > 0 && <span>Live-check errors: <strong style={{ color: 'var(--status-warning)' }}>{lce}</strong></span>}
                </>}
              </div>
            )
          })()
        )}

        {/* Triage cards — only show once we have results */}
        {allResults.length > 0 && (
          <TriageSummaryCards
            results={allResults}
            activeFilter={activeFilter}
            onFilterChange={handleFilterChange}
          />
        )}

        {/* Filter bar */}
        {allResults.length > 0 && (
          <FilterBar
            results={allResults}
            activeFilter={activeFilter}
            onFilterChange={handleFilterChange}
          />
        )}

        {/* Bulk controls */}
        {allResults.length > 0 && (
          <BulkControls selectedCount={selectedIds.size} />
        )}

        {/* Table meta */}
        {filteredResults.length > 0 && (
          <div className="table-meta">
            <span>
              Showing <strong>{filteredResults.length}</strong>
              {activeFilter !== 'all' ? ` of ${allResults.length}` : ''} result{filteredResults.length !== 1 ? 's' : ''}
              {activeFilter !== 'all' && <span style={{ color: 'var(--accent-blue)', marginLeft: 6 }}>— filtered by: {NAMED_FILTERS.find(f => f.key === activeFilter)?.label ?? activeFilter}</span>}
            </span>
            <span style={{ color: 'var(--text-faint)' }}>Priority sorted · {selectedIds.size > 0 ? `${selectedIds.size} selected` : 'no selection'}</span>
          </div>
        )}

        {/* Results table */}
        {filteredResults.length > 0 && (
          <div style={{ maxHeight: 520, overflowY: 'auto' }}>
            <ResultsTable
              results={filteredResults}
              selectedIds={selectedIds}
              onToggleSelect={handleToggleSelect}
              onToggleAll={handleToggleAll}
            />
          </div>
        )}

        {/* Empty filter state */}
        {allResults.length > 0 && filteredResults.length === 0 && (
          <div className="empty-state">
            No results match this filter.
            <br />
            <button className="btn btn-ghost" style={{ marginTop: 10, fontSize: 12 }} onClick={() => handleFilterChange('all')}>
              Clear filter — show all
            </button>
          </div>
        )}

        {/* Loading states */}
        {allResults.length === 0 && isRunning && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <p style={{ fontSize: 13, color: 'var(--text-dim)', textAlign: 'center' }}>
              {job?.status === 'queued' ? 'Queued — waiting to start…' : 'Processing… results will appear as they complete.'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  // Shared VT quota state (MDI-12A)
  const [quotaState, setQuotaState]   = useState(null)
  const [quotaLoading, setQuotaLoading] = useState(false)
  const [quotaError, setQuotaError]   = useState(null)

  // Settings visibility
  const [settingsOpen, setSettingsOpen] = useState(false)
  const settingsPanelId = 'mdi-settings-panel'

  async function refreshQuota() {
    setQuotaLoading(true)
    setQuotaError(null)
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/usage`)
      if (!resp.ok) { setQuotaError(`HTTP ${resp.status}`); return null }
      const data = await resp.json()
      const next = { ...data, checkedAt: Date.now() }
      setQuotaState(next)
      return next
    } catch (err) {
      setQuotaError(err.message || 'Network error')
      return null
    } finally {
      setQuotaLoading(false)
    }
  }

  function isQuotaStale() {
    if (!quotaState?.checkedAt) return true
    return Date.now() - quotaState.checkedAt > QUOTA_STALE_MS
  }

  // Paste input + auto-validation state
  const [rawInput, setRawInput]         = useState('')
  const [validating, setValidating]     = useState(false)  // debounce in-flight
  const [preview, setPreview]           = useState(null)
  const [previewError, setPreviewError] = useState(null)
  const debounceRef                     = useRef(null)

  // Estimate state
  const [estimating, setEstimating]       = useState(false)
  const [estimateResult, setEstimateResult] = useState(null)
  const [estimateError, setEstimateError] = useState(null)
  const [estimateStale, setEstimateStale] = useState(false)

  // Upload preview state
  const fileRef = useRef(null)
  const [selectedFile, setSelectedFile]     = useState(null)
  const [uploadPreviewing, setUploadPreviewing] = useState(false)
  const [uploadPreview, setUploadPreview]   = useState(null)
  const [uploadError, setUploadError]       = useState(null)

  // Settings state
  const [useDomainReports, setUseDomainReports]     = useState(false)
  const [staleThresholdDays, setStaleThresholdDays] = useState(7)

  // VT job state
  const [submitting, setSubmitting]               = useState(false)
  const [jobId, setJobId]                         = useState(null)
  const [job, setJob]                             = useState(null)
  const [jobError, setJobError]                   = useState(null)
  const [restoredFromSession, setRestoredFromSession] = useState(false)
  const pollRef = useRef(null)

  const canRunJob = !!(preview && preview.accepted_count > 0)
  const settingsLocked = !!(
    restoredFromSession ||
    (job && (job.status === 'queued' || job.status === 'running'))
  )
  const settingsPayload = {
    default_scheme: 'http', max_items: 500,
    use_domain_reports: useDomainReports,
    stale_threshold_days: staleThresholdDays,
  }

  async function handleEstimate() {
    if (!rawInput.trim()) return
    if (isQuotaStale()) await refreshQuota()
    setEstimating(true)
    setEstimateResult(null)
    setEstimateError(null)
    setEstimateStale(false)
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/estimate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_input: rawInput, ...settingsPayload }),
      })
      if (!resp.ok) { const t = await resp.text(); setEstimateError(`HTTP ${resp.status}: ${t}`); return }
      setEstimateResult(await resp.json())
    } catch (err) { setEstimateError(err.message || 'Network error') }
    finally { setEstimating(false) }
  }

  // Auto-parse: calls parse-preview with no side effects (no VT, no quota, no job)
  async function autoParseInput(input) {
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/parse-preview`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_input: input, default_scheme: 'http', max_items: 500 }),
      })
      if (!resp.ok) { const t = await resp.text(); setPreviewError(`HTTP ${resp.status}: ${t}`); return }
      setPreview(await resp.json())
      setPreviewError(null)
    } catch (err) {
      setPreviewError(err.message || 'Network error')
    } finally {
      setValidating(false)
    }
  }

  function handleRawInputChange(val) {
    setRawInput(val)
    if (estimateResult) setEstimateStale(true)
    // Cancel any pending debounce
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!val.trim()) {
      setPreview(null); setPreviewError(null); setValidating(false)
      return
    }
    // Show "Validating…" immediately; fire parse after 500ms idle
    setValidating(true)
    debounceRef.current = setTimeout(() => autoParseInput(val), 500)
  }

  // Manual refresh — used by "↺ Refresh validation" button
  function handleRefreshValidation() {
    if (!rawInput.trim()) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    setValidating(true)
    setPreviewError(null)
    autoParseInput(rawInput)
  }

  function handleClear() {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    setRawInput(''); setPreview(null); setPreviewError(null); setValidating(false)
    setEstimateResult(null); setEstimateError(null); setEstimateStale(false)
  }

  function handleFileChange(e) {
    const f = e.target.files?.[0] || null
    setSelectedFile(f); setUploadPreview(null); setUploadError(null)
  }

  async function handleUploadPreview() {
    if (!selectedFile) return
    setUploadPreviewing(true); setUploadPreview(null); setUploadError(null)
    try {
      const form = new FormData()
      form.append('file', selectedFile); form.append('default_scheme', 'http'); form.append('max_items', '500')
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/upload-preview`, { method: 'POST', body: form })
      if (!resp.ok) { const t = await resp.text(); setUploadError(`HTTP ${resp.status}: ${t}`); return }
      setUploadPreview(await resp.json())
    } catch (err) { setUploadError(err.message || 'Network error') }
    finally { setUploadPreviewing(false) }
  }

  const pollJob = useCallback(async (id) => {
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/${id}`)
      if (!resp.ok) return
      const data = await resp.json()
      setJob(data)
      if (data.status === 'done' || data.status === 'error') {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
        refreshQuota()
      }
    } catch (_) { /* ignore poll errors */ }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  async function handleRunJob() {
    if (!rawInput.trim() || submitting) return
    const freshQuota = await refreshQuota()
    if (freshQuota && freshQuota.remaining <= 0) {
      setJobError(
        `VT quota exhausted — ${freshQuota.daily_lookups_used ?? '?'} / ${freshQuota.daily_limit ?? 500} used today. Wait until UTC midnight.`
      )
      return
    }
    setSubmitting(true); setJob(null); setJobId(null); setJobError(null); setRestoredFromSession(false)
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/submit`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_input: rawInput, ...settingsPayload }),
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        setJobError(data?.detail?.message || data?.detail || `HTTP ${resp.status}`)
        return
      }
      const data = await resp.json()
      const id = data.job_id
      setJobId(id)
      pollRef.current = setInterval(() => pollJob(id), 2000)
      await pollJob(id)
    } catch (err) { setJobError(err.message || 'Network error') }
    finally { setSubmitting(false) }
  }

  useEffect(() => {
    if (estimateResult) setEstimateStale(true)
  }, [useDomainReports, staleThresholdDays])  // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch quota on app load
  useEffect(() => { refreshQuota() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Recovery: restore latest completed job on mount
  useEffect(() => {
    let cancelled = false
    async function tryRecover() {
      try {
        const resp = await fetch(`${API_BASE}/api/mdi/jobs/latest`)
        if (cancelled) return
        if (resp.status === 404 || !resp.ok) return
        const data = await resp.json()
        if (cancelled) return
        setJob(data); setJobId(data.job_id); setRestoredFromSession(true)
        if (data.status === 'queued' || data.status === 'running') {
          pollRef.current = setInterval(() => pollJob(data.job_id), 2000)
        }
      } catch (_) { /* non-blocking */ }
    }
    tryRecover()
    return () => { cancelled = true }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (debounceRef.current) clearTimeout(debounceRef.current)
  }, [])

  return (
    <div className="layout">
      {/* ── Nav ── */}
      <nav className="nav">
        <a href="/tools" className="nav-back"><IconArrowLeft /> All tools</a>
        <div className="nav-divider" />
        <div className="nav-brand">
          <span className="nav-title">MDI</span>
          <span className="nav-subtitle">Malicious Domain Identifier</span>
        </div>

        <div className="nav-spacer" />

        <QuotaNavWidget quota={quotaState} loading={quotaLoading} error={quotaError} />

        <div className="nav-settings-anchor">
          <button
            className="settings-gear-btn"
            onClick={() => setSettingsOpen(v => !v)}
            aria-expanded={settingsOpen}
            aria-controls={settingsPanelId}
            title="Toggle MDI settings"
          >
            <IconGear /> Settings
          </button>
          <CollapsibleSettingsPanel
            open={settingsOpen}
            id={settingsPanelId}
            useDomainReports={useDomainReports}
            setUseDomainReports={setUseDomainReports}
            staleThresholdDays={staleThresholdDays}
            setStaleThresholdDays={setStaleThresholdDays}
            locked={settingsLocked}
          />
        </div>
      </nav>

      <main className="main">
        <div className="shell-notice">
          <IconInfo />
          MDI — VT core + RDAP/WHOIS enrichment + live checks + triage UI active.
        </div>

        <div className="page-heading">
          <h1>Malicious Domain Identifier</h1>
          <p>Triage domains using VirusTotal, age context, and live-site checks to quickly identify risky infrastructure.</p>
        </div>

        <InputSection
          rawInput={rawInput}
          setRawInput={handleRawInputChange}
          validating={validating}
          preview={preview}
          previewError={previewError}
          onRefreshValidation={handleRefreshValidation}
          onClear={handleClear}
          fileRef={fileRef}
          selectedFile={selectedFile}
          onFileChange={handleFileChange}
          onUploadPreview={handleUploadPreview}
          uploadPreviewing={uploadPreviewing}
          onRunJob={handleRunJob}
          submitting={submitting}
          canRunJob={canRunJob}
          onEstimate={handleEstimate}
          estimating={estimating}
        />

        <EstimateSection estimate={estimateResult} error={estimateError} stale={estimateStale} />
        <UploadPreviewResultsSection preview={uploadPreview} error={uploadError} />

        <JobSection
          job={job}
          jobError={jobError}
          jobId={jobId}
          restoredFromSession={restoredFromSession}
          onDismissRestore={() => { setRestoredFromSession(false); setJob(null); setJobId(null) }}
        />
      </main>

      <footer className="footer">
        © {new Date().getFullYear()} Forge Forward — MDI
      </footer>
    </div>
  )
}
