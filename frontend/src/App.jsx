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
function IconShield() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    </svg>
  )
}

// ── Constants ─────────────────────────────────────────────────────────────────

const API_BASE = ''   // same-origin; nginx proxies /api/mdi/ to port 8011
const QUOTA_STALE_MS = 60_000
const MAX_ITEMS = 500

// ── Pure helper functions ─────────────────────────────────────────────────────

function nv(value, fallback = '—') {
  return value == null || value === '' ? fallback : value
}

const LIVE_ACTIVE_SET  = new Set(['active', 'redirect', 'forbidden'])
const LIVE_NO_SET      = new Set(['not_found', 'gone', 'dns_failure', 'connection_refused', 'timeout'])
const RECENT_AGE_SET   = new Set(['very_new', 'new'])
const STALE_FRESH_SET  = new Set(['stale', 'very_stale'])
const FLAGGED_BUCKET_SET = new Set(['malicious', 'suspicious'])

function isRowHeld(r) {
  return r.processing_status === 'hold_skipped' || r.domain_hold?.has_hold === true
}
function isRowStale(r) {
  return STALE_FRESH_SET.has(r.freshness)
}
function canScanRow(r, job) {
  if (isRowHeld(r) || !r.input_normalized) return false
  if (r.input_type === 'url') return true
  return !job?.use_domain_reports
}
function canRefreshRow(r) {
  return !isRowHeld(r) && !!r.input_normalized
}
function countStaleScannable(results, job) {
  return (results || []).filter(r => isRowStale(r) && canScanRow(r, job)).length
}
function countSelectedScannable(results, selectedIds, job) {
  return (results || []).filter(r => selectedIds.has(r.position) && canScanRow(r, job)).length
}

function isFlagged(r)       { return FLAGGED_BUCKET_SET.has(r?.triage_bucket) }
function isLive(r)          { return LIVE_ACTIVE_SET.has(r?.live_status) }
function isNoLive(r)        { return LIVE_NO_SET.has(r?.live_status) }
function isRecentAge(r)     { return RECENT_AGE_SET.has(r?.age_bucket) }
function isStaleFreshness(r){ return STALE_FRESH_SET.has(r?.freshness) }

function getVirtualBucketKey(r) {
  if (!r) return 'unknown'
  const bucket = r.triage_bucket
  if (bucket === 'held') return 'held'
  if (bucket === 'error' || bucket === 'unresolvable' || bucket === 'pending') return 'unknown'
  if (isFlagged(r)) {
    if (isLive(r) && isRecentAge(r)) return 'flr'
    if (isLive(r))                   return 'fl'
    if (isRecentAge(r))              return 'fr'
    if (isStaleFreshness(r))         return 'fs'
    if (isNoLive(r))                 return 'fnl'
    return 'flagged'
  }
  if (bucket === 'clean') return 'clean'
  return 'unknown'
}

const PRIORITY_RANK = {
  held:    1,
  unknown: 2,
  flr:     3,
  fl:      4,
  fr:      5,
  fs:      6,
  fnl:     7,
  flagged: 8,
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

const TRIAGE_CARDS = [
  { key: 'flr',     label: 'Flagged + Live + Recent', color: 'var(--c-flr)', filter: 'flr' },
  { key: 'fl',      label: 'Flagged + Live',           color: 'var(--c-fl)',  filter: 'fl'  },
  { key: 'fr',      label: 'Flagged + Recent',         color: 'var(--c-fr)', filter: 'fr'  },
  { key: 'fs',      label: 'Flagged + Stale',          color: 'var(--c-fs)', filter: 'fs'  },
  { key: 'fnl',     label: 'Flagged + No-Live',        color: 'var(--c-fnl)',filter: 'fnl' },
  { key: 'unknown', label: 'Unknown / Errors',         color: 'var(--c-unk)',filter: 'unknown' },
  { key: 'clean',   label: 'Clean',                    color: 'var(--c-cln)',filter: 'clean' },
]

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

// ── QuotaNavWidget (compact nav display) ─────────────────────────────────────

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
    <div className="quota-nav-widget" title={`VT quota${checkedStr ? ` — Last checked: ${checkedStr}` : ''}`}>
      <span className="quota-label">VT Quota</span>
      <span className="quota-value" style={{ color: valColor }}>
        {used}<span style={{ color: 'var(--text-faint)' }}>/{limit}</span>
      </span>
      <div className="quota-bar-wrap">
        <div className="quota-bar-fill" style={{ width: `${pct}%`, background: barColor }} />
      </div>
      {remaining <= 0
        ? <span style={{ color: 'var(--risk-critical)', fontWeight: 700, fontSize: 10 }}>EXHAUSTED</span>
        : <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{remaining} left</span>
      }
    </div>
  )
}

// ── Settings panel ────────────────────────────────────────────────────────────

function CollapsibleSettingsPanel({
  open, id,
  staleThresholdDays, setStaleThresholdDays,
  autoRescanStale, setAutoRescanStale,
  maxAutoRescans, setMaxAutoRescans,
  locked,
}) {
  if (!open) return null
  const ctrlStyle = locked ? { opacity: 0.55, pointerEvents: 'none' } : {}
  return (
    <div className="settings-panel" id={id} role="region" aria-label="MDI Settings">
      <div className="settings-panel-header">
        <span className="settings-panel-title">Settings</span>
        {locked && <span style={{ fontSize: 9, color: 'var(--status-warning)' }}>Locked</span>}
      </div>
      <div className="settings-panel-body">
        {locked && (
          <p className="settings-panel-locked-msg">
            Settings locked while a job is active or restored. Clear results to change settings.
          </p>
        )}

        <div>
          <p className="settings-section-label">VT Processing</p>
          <div style={{ ...ctrlStyle, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', flex: 1 }}>Stale threshold</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
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
                <span style={{ fontSize: 10, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>days</span>
              </div>
            </div>
            <p style={{ fontSize: 10, color: 'var(--text-faint)', lineHeight: 1.4 }}>
              VT reports older than this are classified Stale. Default: 7 days.
            </p>
          </div>
        </div>

        <div style={{ marginTop: 14 }}>
          <p className="settings-section-label">Advanced VT behavior</p>
          <div style={{ ...ctrlStyle, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label className="settings-checkbox-row">
              <input
                type="checkbox"
                checked={autoRescanStale}
                onChange={e => setAutoRescanStale(e.target.checked)}
                disabled={locked}
              />
              <span>↺ Auto-rescan stale flagged items</span>
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', flex: 1 }}>Max auto-rescans per job</span>
              <input
                type="number" min={0} max={25}
                value={maxAutoRescans}
                onChange={e => {
                  const v = parseInt(e.target.value, 10)
                  if (!isNaN(v) && v >= 0 && v <= 25) setMaxAutoRescans(v)
                }}
                disabled={locked || !autoRescanStale}
                className="settings-number-input"
              />
            </div>
            <p className="settings-auto-rescan-warning">
              Auto-rescan consumes additional VirusTotal quota and may significantly increase runtime.
              It runs only for stale flagged URL-mode items and remains off by default.
            </p>
          </div>
        </div>

        <div>
          <p className="settings-section-label">Coming soon</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
            <span className="settings-placeholder" title="Export options — available in MDI-16">↑ Export options (MDI-16)</span>
            <span className="settings-placeholder" title="URL activity check settings — future">🔗 URL activity check settings</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Inline validation summary ─────────────────────────────────────────────────

function ValidationSummary({ validating, preview, previewError, onRefresh }) {
  const [showRejected, setShowRejected] = useState(false)
  const [showDupes, setShowDupes]       = useState(false)

  if (validating) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: 11, color: 'var(--text-muted)' }}>
        <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block', fontSize: 12 }}>↻</span>
        Validating input…
      </div>
    )
  }
  if (previewError) {
    return (
      <div style={{ fontSize: 11, color: 'var(--risk-critical)', padding: '4px 0' }}>
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', fontSize: 12 }}>
        <span style={{ color: accepted > 0 ? 'var(--risk-clean)' : 'var(--text-muted)', fontWeight: accepted > 0 ? 700 : 400 }}>
          ✓ {accepted} accepted
        </span>
        {rejected > 0 && (
          <span style={{ color: 'var(--risk-critical)', fontWeight: 600 }}>✗ {rejected} rejected</span>
        )}
        {dupes > 0 && (
          <span style={{ color: 'var(--risk-medium)' }}>⊘ {dupes} duplicate{dupes !== 1 ? 's' : ''} removed</span>
        )}
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
      {showRejected && preview.rejected?.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-secondary)', maxHeight: 90, overflowY: 'auto', background: 'var(--bg-input)', border: '1px solid var(--border-soft)', borderRadius: 4, padding: '6px 10px' }}>
          {preview.rejected.map((r, i) => (
            <div key={i}><code style={{ color: 'var(--risk-critical)', fontFamily: 'Menlo,Consolas,monospace' }}>{r.original}</code> — {r.reason}</div>
          ))}
        </div>
      )}
      {showDupes && preview.duplicates?.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', maxHeight: 60, overflowY: 'auto', background: 'var(--bg-input)', border: '1px solid var(--border-soft)', borderRadius: 4, padding: '6px 10px' }}>
          {preview.duplicates.map((d, i) => <div key={i}><code style={{ fontFamily: 'Menlo,Consolas,monospace' }}>{d}</code></div>)}
        </div>
      )}
    </div>
  )
}

// ── Input panel with tabs ─────────────────────────────────────────────────────

function InputTabsPanel({
  activeTab, onTabChange,
  rawInput, setRawInput,
  validating, preview, previewError, onRefreshValidation,
  onClear,
  fileRef, selectedFile, onFileChange, onUploadPreview, uploadPreviewing,
  onRunJob, submitting, canRunJob,
  onEstimate, estimating,
}) {
  const hasInput = rawInput.trim().length > 0
  const lineCount = hasInput ? rawInput.trim().split('\n').filter(l => l.trim()).length : 0

  return (
    <div className="input-panel">
      <div className="input-tabs-nav">
        <button
          className={`input-tab-btn${activeTab === 'paste' ? ' active' : ''}`}
          onClick={() => onTabChange('paste')}
        >
          Paste Domains / URLs
        </button>
        <button
          className={`input-tab-btn${activeTab === 'upload' ? ' active' : ''}`}
          onClick={() => onTabChange('upload')}
        >
          Upload CSV / Excel
        </button>
      </div>

      <div className="input-panel-body">
        {activeTab === 'paste' && (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <textarea
                className="input-area"
                value={rawInput}
                onChange={e => setRawInput(e.target.value)}
                placeholder={"Paste domains or URLs — one per line, comma-separated, or space-separated.\n\nexample.com\nmalicious-example.net\ncdn.update-service[.]xyz"}
                spellCheck={false}
                autoComplete="off"
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                  Up to {MAX_ITEMS.toLocaleString()} items per run
                </span>
                <span className="input-counter">
                  {lineCount} / {MAX_ITEMS}
                </span>
              </div>
              {hasInput && (
                <ValidationSummary
                  validating={validating}
                  preview={preview}
                  previewError={previewError}
                  onRefresh={onRefreshValidation}
                />
              )}
            </div>

            <div className="input-row">
              <button
                className="btn btn-ghost"
                onClick={onEstimate}
                disabled={estimating || !canRunJob}
                title={!canRunJob ? 'Paste input and wait for validation' : undefined}
              >
                <IconCalculator /> {estimating ? 'Estimating…' : 'Estimate Quota & Runtime'}
              </button>

              <button
                className="btn btn-primary"
                onClick={onRunJob}
                disabled={submitting || !canRunJob}
              >
                <IconSearch /> {submitting ? 'Submitting…' : 'Run MDI Check'}
              </button>

              {hasInput && (
                <button className="btn btn-ghost" onClick={onClear} style={{ fontSize: 11 }}>
                  Clear
                </button>
              )}

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
            </div>

            {!canRunJob && !submitting && !validating && hasInput && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {previewError ? 'Fix validation errors above.' : 'No accepted items yet.'}
              </span>
            )}
            {!hasInput && (
              <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
                Validation runs automatically · no quota consumed
              </span>
            )}
          </>
        )}

        {activeTab === 'upload' && (
          <>
            <p className="upload-tab-hint">
              Upload a CSV or XLSX file with a "Domain / DNS Form" column.
            </p>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <label className="btn btn-ghost" style={{ cursor: 'pointer', fontSize: 11, padding: '5px 12px' }}>
                Choose file
                <input ref={fileRef} type="file" accept=".csv,.xlsx,.xlsm" style={{ display: 'none' }} onChange={onFileChange} />
              </label>
              {selectedFile && (
                <span style={{ fontSize: 11, color: 'var(--text-secondary)', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {selectedFile.name}
                </span>
              )}
              <button className="btn btn-ghost" onClick={onUploadPreview} disabled={uploadPreviewing || !selectedFile} style={{ fontSize: 11 }}>
                <IconUpload /> {uploadPreviewing ? 'Validating…' : 'Validate Upload'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── VT Usage & Status panel ───────────────────────────────────────────────────

function VtUsagePanel({ quota, quotaLoading, job }) {
  const used      = quota?.daily_lookups_used ?? 0
  const limit     = quota?.daily_limit ?? 500
  const remaining = quota?.remaining ?? (limit - used)
  const valColor  = remaining <= 0 ? 'var(--risk-critical)' : remaining < 50 ? 'var(--risk-medium)' : 'var(--text-main)'

  const hasJob    = !!job
  const attempted = job?.total ?? 0
  const completed = job?.processed ?? 0
  const queued    = Math.max(0, attempted - completed)
  const pct       = attempted > 0 ? Math.round((completed / attempted) * 100) : 0
  const isRunning = job?.status === 'running' || job?.status === 'queued'
  const progressColor = job?.status === 'error' ? 'var(--risk-critical)' : job?.status === 'done' ? 'var(--risk-clean)' : 'var(--accent-blue)'

  return (
    <div className="vt-usage-panel">
      <div className="panel-label-row">
        <span className="panel-section-label">VT Usage &amp; Status</span>
        {quotaLoading && <span style={{ fontSize: 9, color: 'var(--text-faint)' }}>Refreshing…</span>}
      </div>

      <div className="vt-stat-grid">
        <div className="vt-stat-box">
          <span className="vt-stat-lbl">Run limit</span>
          <span className="vt-stat-val">4<span style={{ fontSize: 10, color: 'var(--text-faint)', fontWeight: 400 }}>/min</span></span>
        </div>
        <div className="vt-stat-box">
          <span className="vt-stat-lbl">Daily quota</span>
          <span className="vt-stat-val">{limit}<span style={{ fontSize: 10, color: 'var(--text-faint)', fontWeight: 400 }}>/day</span></span>
        </div>
        <div className="vt-stat-box">
          <span className="vt-stat-lbl">Used today</span>
          <span className="vt-stat-val" style={{ color: used > 0 ? 'var(--text-main)' : 'var(--text-muted)' }}>{used}</span>
        </div>
        <div className="vt-stat-box">
          <span className="vt-stat-lbl">Remaining</span>
          <span className="vt-stat-val" style={{ color: valColor }}>{remaining}</span>
        </div>
      </div>

      {hasJob && (
        <div className="current-run-section">
          <span className="current-run-label">Current run</span>
          <div className="current-run-stats">
            <div className="cr-stat">
              <span className="cr-stat-val">{attempted}</span>
              <span className="cr-stat-lbl">Attempted</span>
            </div>
            <div className="cr-stat">
              <span className="cr-stat-val">{completed}</span>
              <span className="cr-stat-lbl">Completed</span>
            </div>
            <div className="cr-stat">
              <span className="cr-stat-val">{queued}</span>
              <span className="cr-stat-lbl">Queued</span>
            </div>
            <div className="cr-stat" style={{ flex: 1 }}>
              <span className="cr-stat-val">{pct}<span style={{ fontSize: 10, fontWeight: 400, color: 'var(--text-faint)' }}>%</span></span>
              <span className="cr-stat-lbl">Progress</span>
            </div>
          </div>
          {attempted > 0 && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-faint)', marginBottom: 3 }}>
                <span>{isRunning ? 'Processing…' : job?.status?.toUpperCase()}</span>
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>{completed} / {attempted}</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${pct}%`, background: progressColor }} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Processing Options panel ──────────────────────────────────────────────────

function ProcessingOptions({ useDomainReports, setUseDomainReports, locked }) {
  const ctrlStyle = locked ? { opacity: 0.55, pointerEvents: 'none' } : {}

  return (
    <div className="proc-options-panel">
      <div className="panel-label-row">
        <span className="panel-section-label">Processing Options</span>
        {locked && <span style={{ fontSize: 9, color: 'var(--status-warning)' }}>Locked</span>}
      </div>
      <div className="proc-options-body">
        {locked && (
          <p className="proc-locked-note">
            Locked while a job is active. Clear results to change.
          </p>
        )}
        <div style={ctrlStyle}>
          <div className="proc-opt-row">
            <input
              type="checkbox"
              className="proc-checkbox"
              id="opt-domain-reports"
              checked={useDomainReports}
              onChange={e => setUseDomainReports(e.target.checked)}
              disabled={locked}
            />
            <div className="proc-opt-info">
              <label htmlFor="opt-domain-reports" className="proc-opt-name" style={{ cursor: locked ? 'default' : 'pointer' }}>
                Domain reports for bare domains
              </label>
              <span className="proc-opt-desc">
                Use domain report instead of URL report when enabled.
              </span>
            </div>
          </div>

          <hr className="proc-divider" />

          <div className="proc-opt-row" style={{ opacity: 0.75 }}>
            <span style={{ width: 13, flexShrink: 0, color: 'var(--risk-clean)', fontSize: 11, fontWeight: 700, textAlign: 'center' }}>✓</span>
            <div className="proc-opt-info">
              <span className="proc-opt-name" style={{ color: 'var(--text-secondary)' }}>
                Live checks: flagged items only
              </span>
              <span className="proc-opt-desc">Reduces runtime. Always enabled.</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

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
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>No external calls — no quota consumed</span>
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
                    <td style={{ padding: '4px 8px', color: 'var(--text-faint)' }}>{r.position}</td>
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
        {value}{note && <span style={{ color: 'var(--text-faint)', fontWeight: 400, fontFamily: 'inherit' }}> ({note})</span>}
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
    estimated_vt_calls_min, estimated_vt_calls_max,
    total_estimated_vt_calls_max,
    auto_rescan_estimated_quota_min, auto_rescan_estimated_quota_max,
    auto_rescan_estimated_duration_seconds_max,
    auto_rescan_note,
    quota_remaining_now, will_exceed_quota, quota_headroom,
    estimated_duration_seconds_min, estimated_duration_seconds_max,
    rate_limit_note, job_state_note, live_check_note,
  } = estimate
  const totalVtMax = total_estimated_vt_calls_max ?? estimated_vt_calls_max

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
            <span>Worst-case estimate ({totalVtMax} VT calls) exceeds remaining quota ({quota_remaining_now}). Submission will be blocked.</span>
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
              <Row label="Best case"     value={`${estimated_vt_calls_min} call${estimated_vt_calls_min !== 1 ? 's' : ''}`} />
              <Row label="Worst case"    value={`${estimated_vt_calls_max} call${estimated_vt_calls_max !== 1 ? 's' : ''}`} bold />
              {auto_rescan_estimated_quota_max > 0 && (
                <>
                  <Row label="Auto-rescan (extra)" value={`${auto_rescan_estimated_quota_min}–${auto_rescan_estimated_quota_max} calls`} />
                  <Row label="Total worst case" value={`${totalVtMax} calls`} bold />
                </>
              )}
              <Row label="Quota remaining" value={quota_remaining_now} />
              <Row label="Headroom" value={quota_headroom >= 0 ? `+${quota_headroom}` : String(quota_headroom)} color={quota_headroom >= 0 ? 'var(--ok)' : 'var(--danger)'} />
            </div>
          </div>
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 6, padding: '10px 14px', fontSize: 12 }}>
            <p style={{ color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600 }}>Estimated runtime</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <Row label="Best case"  value={fmtDuration(estimated_duration_seconds_min)} />
              <Row label="Worst case" value={fmtDuration(estimated_duration_seconds_max)} />
              {auto_rescan_estimated_quota_max > 0 && (
                <Row label="Auto-rescan (extra)" value={auto_rescan_estimated_duration_seconds_max > 0 ? `up to ${fmtDuration(auto_rescan_estimated_duration_seconds_max)}` : 'may add time'} />
              )}
              {held_skipped_count > 0 && <Row label="Hold-skipped" value={held_skipped_count} note="0 calls" warn />}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <p style={{ fontSize: 11, color: 'var(--text-muted)' }}><strong style={{ color: 'var(--text-secondary)' }}>Rate limit:</strong> {rate_limit_note}</p>
          <p style={{ fontSize: 11, color: 'var(--status-warning)' }}><strong>Job state:</strong> {job_state_note}</p>
          {live_check_note && <p style={{ fontSize: 11, color: 'var(--text-muted)' }}><strong style={{ color: 'var(--text-secondary)' }}>Live checks:</strong> {live_check_note}</p>}
          {auto_rescan_note && <p style={{ fontSize: 11, color: 'var(--status-warning)' }}><strong>Auto-rescan:</strong> {auto_rescan_note}</p>}
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

// ── Action confirmation modal ─────────────────────────────────────────────────

function ActionConfirmModal({ open, estimate, action, onConfirm, onCancel, confirming }) {
  if (!open || !estimate) return null
  const isScan = action === 'scan'
  const blocked = estimate.will_exceed_quota
  const skipSummary = estimate.skipped_reasons_summary
    ? Object.entries(estimate.skipped_reasons_summary).map(([k, v]) => `${k}: ${v}`).join(', ')
    : null

  return (
    <div className="action-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="action-modal-title">
      <div className="action-modal">
        <h3 id="action-modal-title" className="action-modal-title">
          {isScan ? 'Request New Scan' : 'Refresh VT Report'}
        </h3>
        <p className="action-modal-msg">{estimate.message}</p>
        <div className="action-modal-stats">
          <div><span>Eligible</span><strong>{estimate.eligible_count}</strong></div>
          <div><span>Skipped</span><strong>{estimate.skipped_count}</strong></div>
          <div><span>Quota est.</span><strong>{estimate.estimated_quota_min}–{estimate.estimated_quota_max}</strong></div>
          <div><span>Remaining</span><strong>{estimate.quota_remaining}</strong></div>
        </div>
        {skipSummary && (
          <p className="action-modal-skips">Skipped: {skipSummary}</p>
        )}
        {blocked && (
          <p className="action-modal-warn">⛔ Insufficient quota for worst-case estimate. Action blocked.</p>
        )}
        <div className="action-modal-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={confirming}>Cancel</button>
          {isScan ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={onConfirm}
              disabled={confirming || blocked || estimate.eligible_count === 0}
            >
              {confirming ? 'Starting…' : 'Confirm scan'}
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              onClick={onConfirm}
              disabled={confirming || blocked || estimate.eligible_count === 0}
            >
              {confirming ? 'Starting…' : 'Confirm refresh'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Bulk controls ─────────────────────────────────────────────────────────────

function BulkControls({
  selectedCount,
  canRescanSelected,
  canRescanStale,
  staleCount,
  actionInProgress,
  onRescanSelected,
  onRescanStale,
}) {
  return (
    <div className="bulk-controls">
      <span className="bulk-label">Bulk actions:</span>
      <button className="btn-stub" disabled aria-disabled="true" title="Select rows first">
        Actions {selectedCount > 0 ? `(${selectedCount})` : '▾'}
      </button>
      <button className="btn-stub" disabled aria-disabled="true" title="Export available in MDI-16">
        <IconUpload /> Export Flagged
      </button>
      <button className="btn-stub" disabled aria-disabled="true" title="Export available in MDI-16">
        <IconUpload /> Export All
      </button>
      <button
        className={canRescanSelected && !actionInProgress ? 'btn btn-ghost btn-action-active' : 'btn-stub'}
        disabled={!canRescanSelected || actionInProgress}
        title={canRescanSelected ? 'Request new VT scan for selected rows' : 'Select scannable rows first'}
        onClick={onRescanSelected}
      >
        <IconRefresh /> Rescan Selected
      </button>
      <button
        className={canRescanStale && !actionInProgress ? 'btn btn-ghost btn-action-active' : 'btn-stub'}
        disabled={!canRescanStale || actionInProgress}
        title={canRescanStale ? `Request new VT scan for ${staleCount} stale row(s)` : 'No eligible stale rows'}
        onClick={onRescanStale}
      >
        <IconRefresh /> Rescan Stale{staleCount > 0 ? ` (${staleCount})` : ''}
      </button>
    </div>
  )
}

// ── Operations results table ──────────────────────────────────────────────────

function ResultsTable({ results, selectedIds, onToggleSelect, onToggleAll, selectedItem, onSelectItem }) {
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
            const isSelected     = selectedIds.has(r.position)
            const isDetailActive = selectedItem?.position === r.position
            const bucket         = r.triage_bucket ?? 'pending'
            const hasErrors      = r.errors?.length > 0
            return (
              <tr
                key={r.position}
                className={`${rowTierClass(r)}${isSelected ? ' row-selected' : ''}${isDetailActive ? ' row-detail-active' : ''}`}
                data-bucket={bucket}
                onClick={() => onSelectItem && onSelectItem(r)}
              >
                <td className="accent-cell" style={{ paddingLeft: 8 }}>
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => onToggleSelect(r.position)}
                    onClick={e => e.stopPropagation()}
                    aria-label={`Select ${r.input_normalized}`}
                  />
                </td>
                <td style={{ color: 'var(--text-faint)', textAlign: 'center', fontVariantNumeric: 'tabular-nums' }}>{r.position}</td>
                <td>
                  <code
                    style={{ fontFamily: 'Menlo,Consolas,monospace', fontSize: 11, display: 'block', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-main)' }}
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
                    <details className="triage-reasons" onClick={e => e.stopPropagation()}>
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
                    <span className={`badge ${freshnessBadgeClass(r.freshness)}`}>{r.freshness.replace(/_/g, ' ')}</span>
                  ) : <span style={{ color: 'var(--text-faint)' }}>—</span>}
                </td>
                <td>
                  {r.live_status && r.live_status !== 'not_checked' ? (
                    <span className={`badge ${liveBadgeClass(r.live_status)}`}>{formatLiveStatus(r.live_status)}</span>
                  ) : <span style={{ color: 'var(--text-faint)', fontSize: 10 }}>—</span>}
                </td>
                <td style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{formatDate(r.created_at)}</td>
                <td style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{formatAgeBucket(r.age_bucket)}</td>
                <td>
                  {r.evidence_status ? (
                    <span className={`badge ${evidenceBadgeClass(r.evidence_status)}`}>{r.evidence_status.replace(/_/g, ' ')}</span>
                  ) : <span style={{ color: 'var(--text-faint)' }}>—</span>}
                  {hasErrors && <span style={{ color: 'var(--warn)', marginLeft: 4, fontSize: 10 }} title={r.errors.join('; ')}>⚠</span>}
                </td>
                <td onClick={e => e.stopPropagation()}>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button
                      className={`icon-btn${isDetailActive ? ' active' : ''}`}
                      onClick={() => onSelectItem && onSelectItem(isDetailActive ? null : r)}
                      title={isDetailActive ? 'Close detail panel' : 'View details in panel →'}
                      aria-label={`View details for ${r.input_normalized}`}
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

// ── Triage workspace (replaces JobSection) ────────────────────────────────────

function TriageWorkspace({
  job, jobError, jobId, restoredFromSession, onDismissRestore,
  selectedItem, onSelectItem,
  actionInProgress, actionMessage,
  onRescanSelected, onRescanStale,
}) {
  const [activeFilter, setActiveFilter] = useState('all')
  const [selectedIds, setSelectedIds] = useState(new Set())

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
      <div className="job-status-bar" style={{ borderColor: 'rgba(239,68,68,0.4)' }}>
        <span style={{ color: 'var(--risk-critical)', fontSize: 12, fontWeight: 600 }}>⛔ Submit error: {jobError}</span>
      </div>
    )
  }
  if (!job && !jobId) return null

  const done        = job ? (job.processed ?? 0) : 0
  const total       = job ? (job.total ?? 0) : 0
  const pct         = total > 0 ? Math.round((done / total) * 100) : 0
  const allResults  = job?.results ?? []
  const prioritySorted  = [...allResults].sort(comparePriority)
  const filteredResults = getFilteredResults(prioritySorted, activeFilter)
  const isComplete  = job?.status === 'done' || job?.status === 'error'
  const isRunning   = job?.status === 'running' || job?.status === 'queued'

  const statusColor = {
    queued: 'var(--text-muted)',
    running: 'var(--accent-blue)',
    done: 'var(--risk-clean)',
    error: 'var(--risk-critical)',
  }[job?.status] ?? 'var(--text-muted)'

  const progressColor = job?.status === 'error' ? 'var(--risk-critical)' : job?.status === 'done' ? 'var(--risk-clean)' : 'var(--accent-blue)'

  const lcc  = job?.live_check_count ?? 0
  const lcsk = job?.live_check_skipped_count ?? 0
  const lce  = job?.live_check_error_count ?? 0
  const rdap = job?.rdap_enriched_count ?? 0
  const showCounters = lcc > 0 || lcsk > 0 || lce > 0 || rdap > 0
  const staleScannable = countStaleScannable(allResults, job)
  const selectedScannable = countSelectedScannable(allResults, selectedIds, job)
  const canRescanSelected = isComplete && !actionInProgress && selectedScannable > 0
  const canRescanStale = isComplete && !actionInProgress && staleScannable > 0

  return (
    <>
      {actionMessage && (
        <div className={`action-status-msg${actionInProgress ? ' running' : ''}`}>{actionMessage}</div>
      )}
      {/* Job status bar */}
      <div className="job-status-bar">
        <span className="job-status-badge" style={{ color: statusColor, borderColor: statusColor + '55' }}>
          {job?.status?.toUpperCase() ?? 'LOADING'}
        </span>
        <div className="job-status-bar-meta">
          {total > 0 && (
            <div className="job-status-bar-progress">
              <div className="job-status-bar-progress-label">
                <span>{isRunning ? `Processing… ${done} / ${total}` : `${done} / ${total} processed`}</span>
                <span style={{ fontWeight: 600 }}>{pct}%</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${pct}%`, background: progressColor }} />
              </div>
            </div>
          )}
          <span style={{ fontSize: 10, color: 'var(--text-faint)' }}>
            Job: <code style={{ fontSize: 10 }}>{jobId}</code>
          </span>
          {restoredFromSession && (
            <span style={{ fontSize: 11, color: 'var(--risk-clean)', display: 'flex', alignItems: 'center', gap: 5 }}>
              ↩ Restored
              <button
                onClick={onDismissRestore}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-faint)', fontSize: 11, padding: '0 2px' }}
                title="Dismiss restored job"
              >✕</button>
            </span>
          )}
        </div>
      </div>

      {/* Compact counters row */}
      {isComplete && showCounters && (
        <div className="job-counters-row">
          {rdap > 0 && <span>RDAP enriched: <strong style={{ color: 'var(--text-secondary)' }}>{rdap}</strong></span>}
          {lcc > 0 && <span>Live checks: <strong style={{ color: 'var(--status-info)' }}>{lcc}</strong></span>}
          {lcsk > 0 && <span>Live skipped: <strong style={{ color: 'var(--text-muted)' }}>{lcsk}</strong></span>}
          {lce > 0 && <span>Live errors: <strong style={{ color: 'var(--status-warning)' }}>{lce}</strong></span>}
          {isComplete && <span>VT calls: <strong style={{ color: 'var(--text-secondary)' }}>{job?.lookups_used ?? 0}</strong></span>}
        </div>
      )}

      {/* Triage cards */}
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
        <BulkControls
          selectedCount={selectedIds.size}
          canRescanSelected={canRescanSelected}
          canRescanStale={canRescanStale}
          staleCount={staleScannable}
          actionInProgress={actionInProgress}
          onRescanSelected={() => onRescanSelected && onRescanSelected([...selectedIds])}
          onRescanStale={() => onRescanStale && onRescanStale()}
        />
      )}

      {/* Table meta */}
      {filteredResults.length > 0 && (
        <div className="table-meta">
          <span>
            Showing <strong>{filteredResults.length}</strong>
            {activeFilter !== 'all' ? ` of ${allResults.length}` : ''} result{filteredResults.length !== 1 ? 's' : ''}
            {activeFilter !== 'all' && (
              <span style={{ color: 'var(--accent-blue)', marginLeft: 6 }}>
                — filtered by: {NAMED_FILTERS.find(f => f.key === activeFilter)?.label ?? activeFilter}
              </span>
            )}
          </span>
          <span style={{ color: 'var(--text-faint)' }}>
            Priority sorted · {selectedIds.size > 0 ? `${selectedIds.size} selected` : 'click row to inspect'}
          </span>
        </div>
      )}

      {/* Results table */}
      {filteredResults.length > 0 && (
        <ResultsTable
          results={filteredResults}
          selectedIds={selectedIds}
          onToggleSelect={handleToggleSelect}
          onToggleAll={handleToggleAll}
          selectedItem={selectedItem}
          onSelectItem={onSelectItem}
        />
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

      {/* Loading state */}
      {allResults.length === 0 && isRunning && (
        <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
          {job?.status === 'queued' ? 'Queued — waiting to start…' : 'Processing… results will appear as they complete.'}
        </div>
      )}
    </>
  )
}

// ── Detail drawer (right panel) ───────────────────────────────────────────────

function DetailDrawer({
  selectedItem: r,
  onClose,
  job,
  actionInProgress,
  onRefreshRow,
  onScanRow,
}) {
  if (!r) {
    return (
      <div className="detail-drawer">
        <div className="detail-drawer-topbar">
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--text-faint)' }}>
            Detail Panel
          </span>
        </div>
        <div className="detail-drawer-empty">
          <span className="detail-drawer-empty-icon">
            <IconEye />
          </span>
          <p>Select a result to view details.</p>
          <p className="hint">Click a row or the eye icon to inspect it here.</p>
        </div>
      </div>
    )
  }

  const vbKey      = getVirtualBucketKey(r)
  const vtHits     = r.vt_hits ?? 0
  const vtSusp     = r.vt_suspicious ?? 0
  const vtTotal    = r.vt_total_engines ?? 0
  const vtHarmless = vtTotal > 0 ? Math.max(0, vtTotal - vtHits - vtSusp) : 0
  const vtPct      = vtTotal > 0 ? ((vtHits / vtTotal) * 100).toFixed(1) : '0'
  const scanDate   = r.vt_scan_date ?? r.last_scan_date
  const scanStr    = scanDate ? scanDate.substring(0, 19).replace('T', ' ') + ' UTC' : null
  const cardLabel  = TRIAGE_CARDS.find(c => c.key === vbKey)?.label ?? r.triage_bucket ?? '—'

  return (
    <div className="detail-drawer">
      {/* Topbar */}
      <div className="detail-drawer-topbar">
        <div style={{ minWidth: 0 }}>
          <div className="detail-domain">{r.input_normalized}</div>
          {scanStr && <div className="detail-scan-meta">Scanned: {scanStr} · Source: VirusTotal</div>}
        </div>
        <button className="detail-close-btn" onClick={onClose} title="Close detail panel" aria-label="Close">×</button>
      </div>

      <div className="detail-drawer-body">

        {/* 1. TRIAGE CLASSIFICATION */}
        <div className="detail-section">
          <div className="detail-section-label">1. Triage Classification</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span className={`badge ${virtualBucketBadgeClass(vbKey)}`}>{cardLabel}</span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              Confidence: <span className={confClass(r.triage_confidence)}>
                {r.triage_confidence ? r.triage_confidence.charAt(0).toUpperCase() + r.triage_confidence.slice(1) : '—'}
              </span>
            </span>
          </div>
        </div>

        {/* 2. VT SUMMARY */}
        {vtTotal > 0 && (
          <div className="detail-section">
            <div className="detail-section-label">2. VT Summary</div>
            <div className="vt-mini-grid">
              <div className="vt-mini-stat">
                <span className="vt-mini-val" style={{ color: vtHits > 0 ? 'var(--risk-critical)' : 'var(--text-main)' }}>{vtHits}</span>
                <span className="vt-mini-lbl">Malicious</span>
              </div>
              <div className="vt-mini-stat">
                <span className="vt-mini-val" style={{ color: vtSusp > 0 ? 'var(--risk-medium)' : 'var(--text-main)' }}>{vtSusp}</span>
                <span className="vt-mini-lbl">Suspicious</span>
              </div>
              <div className="vt-mini-stat">
                <span className="vt-mini-val" style={{ color: 'var(--risk-clean)' }}>{vtHarmless}</span>
                <span className="vt-mini-lbl">Harmless</span>
              </div>
              <div className="vt-mini-stat">
                <span className="vt-mini-val">{vtTotal}</span>
                <span className="vt-mini-lbl">Total</span>
              </div>
            </div>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                <span style={{ fontWeight: 700, color: vtHits > 0 ? 'var(--risk-critical)' : 'var(--risk-clean)' }}>{vtPct}%</span>
                <span style={{ color: 'var(--text-muted)' }}>{vtHits} / {vtTotal}</span>
              </div>
              <div style={{ height: 6, background: 'var(--bg-elevated)', borderRadius: 3, overflow: 'hidden', border: '1px solid var(--border-soft)' }}>
                <div style={{ height: '100%', width: `${vtPct}%`, background: vtHits > 0 ? 'var(--risk-critical)' : 'var(--risk-clean)', borderRadius: 3, transition: 'width 0.4s' }} />
              </div>
              {scanStr && <div style={{ fontSize: 10, color: 'var(--text-faint)', marginTop: 5 }}>Last scanned: {scanStr}</div>}
            </div>
          </div>
        )}

        {/* 3. VT HIT DETAILS (MDI-14) */}
        <div className="detail-section">
          <div className="detail-section-label">3. VT Hit Details</div>
          {r.vt_engine_results === null || r.vt_engine_results === undefined ? (
            <p className="detail-empty-note">Engine-level details not available for this job.</p>
          ) : r.vt_engine_results.length === 0 ? (
            <p className="detail-empty-note">No malicious or suspicious engines flagged this item.</p>
          ) : (
            <div className="vt-engine-table-wrap">
              <table className="vt-engine-table">
                <thead>
                  <tr>
                    <th>Engine</th>
                    <th>Category</th>
                    <th>Result</th>
                    <th>Method</th>
                  </tr>
                </thead>
                <tbody>
                  {r.vt_engine_results.map((det, i) => (
                    <tr key={i}>
                      <td className="vt-eng-name">{det.engine_name}</td>
                      <td><span className={`vt-cat-badge vt-cat-${det.category}`}>{det.category}</span></td>
                      <td className="vt-eng-result">{det.result || '—'}</td>
                      <td className="vt-eng-method">{det.method || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* 4. DOMAIN AGE CONTEXT */}
        <div className="detail-section">
          <div className="detail-section-label">4. Domain Age Context</div>
          <div className="detail-kv-grid">
            <span>Created</span><span>{formatDate(r.created_at)}</span>
            <span>Age</span>
            <span>
              {r.age_days != null ? `${r.age_days} days` : formatAgeBucket(r.age_bucket)}
            </span>
            <span>Age bucket</span><span>{formatAgeBucket(r.age_bucket)}</span>
            {r.registrar && (
              <>
                <span>Registrar</span>
                <span title={r.registrar} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {r.registrar.length > 32 ? r.registrar.substring(0, 30) + '…' : r.registrar}
                </span>
              </>
            )}
            {r.epp_status?.length > 0 && (
              <>
                <span>EPP status</span>
                <span style={{ fontSize: 10 }}>{r.epp_status.join(', ')}</span>
              </>
            )}
            {r.nameservers?.length > 0 && (
              <>
                <span>Nameservers</span>
                <span style={{ fontSize: 10 }}>{r.nameservers.slice(0, 2).join(', ')}{r.nameservers.length > 2 ? ` +${r.nameservers.length - 2}` : ''}</span>
              </>
            )}
          </div>
        </div>

        {/* 5. LIVE ACTIVITY CONTEXT */}
        <div className="detail-section">
          <div className="detail-section-label">5. Live Activity Context</div>
          <div className="detail-kv-grid">
            <span>Live status</span>
            <span>
              {r.live_status && r.live_status !== 'not_checked' ? (
                <span className={`badge ${liveBadgeClass(r.live_status)}`}>{formatLiveStatus(r.live_status)}</span>
              ) : '—'}
            </span>
            {r.http_status_code != null && (
              <><span>HTTP status</span><span style={{ fontFamily: 'Menlo,Consolas,monospace', fontSize: 11 }}>{r.http_status_code}</span></>
            )}
            {r.redirect_count > 0 && (
              <><span>Redirects</span><span>{r.redirect_count}</span></>
            )}
          </div>
          {!r.live_status || r.live_status === 'not_checked' ? (
            <p className="detail-empty-note">Live check not performed for this item.</p>
          ) : null}
        </div>

        {/* 6. TRIAGE REASONS */}
        {r.triage_reason?.length > 0 && (
          <div className="detail-section">
            <div className="detail-section-label">6. Triage Reasons</div>
            <ul className="detail-reasons-list">
              {r.triage_reason.map((t, i) => <li key={i}>{t}</li>)}
            </ul>
          </div>
        )}

        {/* 6. EVIDENCE */}
        {r.evidence_status && (
          <div className="detail-section">
            <div className="detail-section-label">7. Evidence</div>
            <span className={`badge ${evidenceBadgeClass(r.evidence_status)}`}>{r.evidence_status.replace(/_/g, ' ')}</span>
            {r.freshness && (
              <span className={`badge ${freshnessBadgeClass(r.freshness)}`} style={{ marginLeft: 6 }}>{r.freshness.replace(/_/g, ' ')}</span>
            )}
            {r.errors?.length > 0 && (
              <div style={{ marginTop: 8, fontSize: 10, color: 'var(--status-warning)' }}>
                {r.errors.map((e, i) => <div key={i}>⚠ {e}</div>)}
              </div>
            )}
          </div>
        )}

        {/* 8. ACTIONS */}
        <div className="detail-section">
          <div className="detail-section-label">8. Actions</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <button className="btn-stub" disabled title="Export evidence — available in MDI-16">↑ Export evidence (JSON) — MDI-16</button>
            <button className="btn-stub" disabled title="Open in VirusTotal — coming soon">↗ Open in VirusTotal</button>
            <button
              className={canRefreshRow(r) && !actionInProgress ? 'btn btn-ghost btn-action-active' : 'btn-stub'}
              disabled={!canRefreshRow(r) || actionInProgress || !job}
              title={canRefreshRow(r) ? 'Refresh existing VT report (1 quota unit)' : 'Row not eligible for refresh'}
              onClick={() => onRefreshRow && onRefreshRow(r)}
            >
              ↻ Refresh report
            </button>
            <button
              className={canScanRow(r, job) && !actionInProgress ? 'btn btn-ghost btn-action-active' : 'btn-stub'}
              disabled={!canScanRow(r, job) || actionInProgress || !job}
              title={
                !canScanRow(r, job) && job?.use_domain_reports && r.input_type === 'domain'
                  ? 'New scan not supported in domain-report mode'
                  : canScanRow(r, job) ? 'Request new VT scan' : 'Row not eligible for scan'
              }
              onClick={() => onScanRow && onScanRow(r)}
            >
              ↺ Request new scan
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  // Shared VT quota state
  const [quotaState, setQuotaState]     = useState(null)
  const [quotaLoading, setQuotaLoading] = useState(false)
  const [quotaError, setQuotaError]     = useState(null)

  // Settings visibility
  const [settingsOpen, setSettingsOpen] = useState(false)
  const settingsPanelId = 'mdi-settings-panel'

  // Detail drawer — client-side only, no external calls
  const [selectedItem, setSelectedItem] = useState(null)

  // Input tabs
  const [activeInputTab, setActiveInputTab] = useState('paste')

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
  const [validating, setValidating]     = useState(false)
  const [preview, setPreview]           = useState(null)
  const [previewError, setPreviewError] = useState(null)
  const debounceRef                     = useRef(null)

  // Estimate state
  const [estimating, setEstimating]         = useState(false)
  const [estimateResult, setEstimateResult] = useState(null)
  const [estimateError, setEstimateError]   = useState(null)
  const [estimateStale, setEstimateStale]   = useState(false)

  // Upload state
  const fileRef = useRef(null)
  const [selectedFile, setSelectedFile]       = useState(null)
  const [uploadPreviewing, setUploadPreviewing] = useState(false)
  const [uploadPreview, setUploadPreview]     = useState(null)
  const [uploadError, setUploadError]         = useState(null)

  // Settings state
  const [useDomainReports, setUseDomainReports]     = useState(false)
  const [staleThresholdDays, setStaleThresholdDays] = useState(7)
  const [autoRescanStale, setAutoRescanStale]       = useState(false)
  const [maxAutoRescans, setMaxAutoRescans]         = useState(3)

  // VT job state
  const [submitting, setSubmitting]                 = useState(false)
  const [jobId, setJobId]                           = useState(null)
  const [job, setJob]                               = useState(null)
  const [jobError, setJobError]                     = useState(null)
  const [restoredFromSession, setRestoredFromSession] = useState(false)
  const pollRef = useRef(null)

  const [actionInProgress, setActionInProgress] = useState(false)
  const [actionMessage, setActionMessage]     = useState(null)
  const [actionModal, setActionModal]         = useState(null)
  const [actionConfirming, setActionConfirming] = useState(false)

  const canRunJob = !!(preview && preview.accepted_count > 0)
  const settingsLocked = !!(
    restoredFromSession ||
    (job && (job.status === 'queued' || job.status === 'running')) ||
    actionInProgress ||
    job?.action_in_progress
  )
  const settingsPayload = {
    default_scheme: 'http', max_items: MAX_ITEMS,
    use_domain_reports: useDomainReports,
    stale_threshold_days: staleThresholdDays,
    auto_rescan_stale: autoRescanStale,
    max_auto_rescans: maxAutoRescans,
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

  async function autoParseInput(input) {
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/parse-preview`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_input: input, default_scheme: 'http', max_items: MAX_ITEMS }),
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
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!val.trim()) {
      setPreview(null); setPreviewError(null); setValidating(false)
      return
    }
    setValidating(true)
    debounceRef.current = setTimeout(() => autoParseInput(val), 500)
  }

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
      form.append('file', selectedFile); form.append('default_scheme', 'http'); form.append('max_items', String(MAX_ITEMS))
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
      if (selectedItem) {
        const updated = (data.results || []).find(r => r.position === selectedItem.position)
        if (updated) setSelectedItem(updated)
      }
      const actionDone = !data.action_in_progress
      if (actionDone) setActionInProgress(false)
      if ((data.status === 'done' || data.status === 'error') && actionDone) {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
        refreshQuota()
        if (actionMessage && actionMessage.includes('…')) {
          setActionMessage('VT action completed. Results updated.')
        }
      }
    } catch (_) { /* ignore poll errors */ }
  }, [selectedItem, actionMessage])  // eslint-disable-line react-hooks/exhaustive-deps

  async function fetchActionEstimate(action, scope, positions) {
    const resp = await fetch(`${API_BASE}/api/mdi/jobs/${jobId}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope, positions, estimate_only: true, confirm: false }),
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      const msg = data?.detail?.message || data?.detail || `HTTP ${resp.status}`
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
    }
    return resp.json()
  }

  async function startAction(action, scope, positions) {
    const resp = await fetch(`${API_BASE}/api/mdi/jobs/${jobId}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scope,
        positions,
        estimate_only: false,
        confirm: action === 'scan',
      }),
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      const msg = data?.detail?.message || data?.detail || `HTTP ${resp.status}`
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
    }
    return resp.json()
  }

  async function openActionModal(action, scope, positions) {
    if (!jobId) return
    setActionMessage(null)
    try {
      const estimate = await fetchActionEstimate(action, scope, positions)
      setActionModal({ action, scope, positions, estimate })
    } catch (err) {
      setActionMessage(`Action estimate failed: ${err.message}`)
    }
  }

  async function confirmActionModal() {
    if (!actionModal) return
    setActionConfirming(true)
    try {
      await startAction(actionModal.action, actionModal.scope, actionModal.positions)
      setActionInProgress(true)
      setActionMessage(`${actionModal.action === 'scan' ? 'Scan' : 'Refresh'} in progress…`)
      setActionModal(null)
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(() => pollJob(jobId), 2000)
      await pollJob(jobId)
    } catch (err) {
      setActionMessage(`Action failed: ${err.message}`)
    } finally {
      setActionConfirming(false)
    }
  }

  function handleRescanSelected(positions) {
    openActionModal('scan', 'selected', positions)
  }

  function handleRescanStale() {
    openActionModal('scan', 'stale', null)
  }

  function handleDrawerRefresh(row) {
    openActionModal('refresh', 'selected', [row.position])
  }

  function handleDrawerScan(row) {
    openActionModal('scan', 'selected', [row.position])
  }

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
    setSelectedItem(null)
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
  }, [useDomainReports, staleThresholdDays, autoRescanStale, maxAutoRescans])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { refreshQuota() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Restore latest completed job on mount
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
        if (data.stale_threshold_days != null) setStaleThresholdDays(data.stale_threshold_days)
        if (data.use_domain_reports != null) setUseDomainReports(data.use_domain_reports)
        if (data.auto_rescan_stale != null) setAutoRescanStale(data.auto_rescan_stale)
        if (data.max_auto_rescans != null) setMaxAutoRescans(data.max_auto_rescans)
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

  // Close settings panel on outside click
  useEffect(() => {
    if (!settingsOpen) return
    function handleClick(e) {
      const anchor = document.querySelector('.nav-settings-anchor')
      if (anchor && !anchor.contains(e.target)) setSettingsOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [settingsOpen])

  return (
    <div className="console-shell">

      {/* ── Nav ── */}
      <nav className="console-nav">
        <a href="/tools" className="nav-back"><IconArrowLeft /> Tools</a>
        <div className="nav-divider" />
        <nav className="nav-breadcrumb" aria-label="breadcrumb">
          <span className="bc-item">Tools</span>
          <span className="bc-sep">›</span>
          <span className="bc-current">MDI</span>
        </nav>

        <div className="nav-spacer" />

        <QuotaNavWidget quota={quotaState} loading={quotaLoading} error={quotaError} />

        <div className="nav-settings-anchor">
          <button
            className="settings-gear-btn"
            onClick={() => setSettingsOpen(v => !v)}
            aria-expanded={settingsOpen}
            aria-controls={settingsPanelId}
            title="Advanced settings"
          >
            <IconGear /> Settings
          </button>
          <CollapsibleSettingsPanel
            open={settingsOpen}
            id={settingsPanelId}
            staleThresholdDays={staleThresholdDays}
            setStaleThresholdDays={setStaleThresholdDays}
            autoRescanStale={autoRescanStale}
            setAutoRescanStale={setAutoRescanStale}
            maxAutoRescans={maxAutoRescans}
            setMaxAutoRescans={setMaxAutoRescans}
            locked={settingsLocked}
          />
        </div>
      </nav>

      {/* ── Console workspace: left + right ── */}
      <div className="console-workspace">

        {/* LEFT COLUMN */}
        <div className="console-left">

          {/* Page heading */}
          <div className="mdi-page-heading">
            <div className="mdi-brand-row">
              <span className="mdi-shield"><IconShield /></span>
              <div className="mdi-title-block">
                <span className="mdi-title">MDI</span>
                <span className="mdi-subtitle">Malicious Domain Identifier</span>
              </div>
            </div>
            <p className="mdi-desc">
              Triage domains using VirusTotal, age context, and live-site checks to quickly identify risky infrastructure.
            </p>
          </div>

          {/* Top workspace: input + sidebar */}
          <div className="top-workspace">
            <InputTabsPanel
              activeTab={activeInputTab}
              onTabChange={setActiveInputTab}
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

            <div className="options-sidebar">
              <VtUsagePanel quota={quotaState} quotaLoading={quotaLoading} job={job} />
              <ProcessingOptions
                useDomainReports={useDomainReports}
                setUseDomainReports={setUseDomainReports}
                locked={settingsLocked}
              />
            </div>
          </div>

          {/* Estimate section */}
          <EstimateSection estimate={estimateResult} error={estimateError} stale={estimateStale} />

          {/* Upload validation results */}
          <UploadPreviewResultsSection preview={uploadPreview} error={uploadError} />

          {/* Job + triage workspace */}
          {(job || jobError || jobId) && (
            <TriageWorkspace
              job={job}
              jobError={jobError}
              jobId={jobId}
              restoredFromSession={restoredFromSession}
              onDismissRestore={() => {
                setRestoredFromSession(false)
                setJob(null)
                setJobId(null)
                setSelectedItem(null)
              }}
              selectedItem={selectedItem}
              onSelectItem={setSelectedItem}
              actionInProgress={actionInProgress || !!job?.action_in_progress}
              actionMessage={actionMessage}
              onRescanSelected={handleRescanSelected}
              onRescanStale={handleRescanStale}
            />
          )}

          <ActionConfirmModal
            open={!!actionModal}
            estimate={actionModal?.estimate}
            action={actionModal?.action}
            onConfirm={confirmActionModal}
            onCancel={() => setActionModal(null)}
            confirming={actionConfirming}
          />

          {/* Footer in scroll area */}
          <footer className="footer" style={{ marginTop: 'auto', borderRadius: 'var(--radius)' }}>
            © {new Date().getFullYear()} Forge Forward — MDI
          </footer>
        </div>

        {/* RIGHT COLUMN: detail drawer */}
        <div className="console-right">
          <DetailDrawer
            selectedItem={selectedItem}
            onClose={() => setSelectedItem(null)}
            job={job}
            actionInProgress={actionInProgress || !!job?.action_in_progress}
            onRefreshRow={handleDrawerRefresh}
            onScanRow={handleDrawerScan}
          />
        </div>
      </div>
    </div>
  )
}
