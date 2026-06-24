import React, { useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'

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
function IconBarChart() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>
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

/** Editable next-run settings defaults (must match useState initial values). */
const DEFAULT_SETTINGS = {
  use_domain_reports: false,
  stale_threshold_days: 7,
  auto_rescan_stale: false,
  max_auto_rescans: 3,
  cloudflare_rank_lookup_enabled: false,
}

function resetSettingsToDefaults(setters) {
  setters.setUseDomainReports(DEFAULT_SETTINGS.use_domain_reports)
  setters.setStaleThresholdDays(DEFAULT_SETTINGS.stale_threshold_days)
  setters.setAutoRescanStale(DEFAULT_SETTINGS.auto_rescan_stale)
  setters.setMaxAutoRescans(DEFAULT_SETTINGS.max_auto_rescans)
  setters.setCloudflareRankLookupEnabled(DEFAULT_SETTINGS.cloudflare_rank_lookup_enabled)
}

function formatJobOptionOnOff(value) {
  return value ? 'ON' : 'OFF'
}

function formatJobRanWithSummary(job) {
  if (!job) return null
  return [
    `Domain reports ${formatJobOptionOnOff(job.use_domain_reports)}`,
    `Auto-rescan ${formatJobOptionOnOff(job.auto_rescan_stale)}`,
    `Max auto-rescans ${job.max_auto_rescans ?? DEFAULT_SETTINGS.max_auto_rescans}`,
    `Stale after ${job.stale_threshold_days ?? DEFAULT_SETTINGS.stale_threshold_days} days`,
    `CF rank ${formatJobOptionOnOff(job.cloudflare_rank_lookup_enabled)}`,
  ].join(' · ')
}

// ── Pure helper functions ─────────────────────────────────────────────────────

function nv(value, fallback = '—') {
  return value == null || value === '' ? fallback : value
}

const RECOMMENDED_ACTION_LABELS = {
  investigate_hold: 'Investigate / Hold Review',
  action_already_taken: 'Action Already Taken',
  retry_lookup: 'Retry Lookup',
  verify_investigate: 'Verify / Investigate',
  request_new_scan: 'Request New Scan',
  no_action_based_on_vt: 'No Action Based on VT',
  review_for_action: 'Review for Action',
  refresh_report: 'Refresh Report',
}

function formatRecommendedAction(value) {
  if (!value) return '—'
  const key = String(value).toLowerCase()
  if (RECOMMENDED_ACTION_LABELS[key]) return RECOMMENDED_ACTION_LABELS[key]
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const CLOUDFLARE_INEQUALITY_BUCKET_RE = /^\s*>\s*\d+\s*$/

function formatCloudflareRank(row) {
  const bucket = row?.cloudflare_rank_bucket
  const rawBucket = row?.cloudflare_rank_raw_bucket

  if (
    bucket === 'UNRANKED'
    && rawBucket
    && CLOUDFLARE_INEQUALITY_BUCKET_RE.test(String(rawBucket))
  ) {
    return `${String(rawBucket).trim()} / UNRANKED`
  }

  if (row?.cloudflare_rank_available && bucket) {
    const label = String(bucket).replace(/_/g, ' ')
    if (row.cloudflare_rank != null && row.cloudflare_rank <= 100) {
      return `${label} (rank ${row.cloudflare_rank})`
    }
    if (rawBucket) {
      return `${label} (bucket ${rawBucket})`
    }
    return label
  }
  if (bucket === 'UNRANKED') return 'UNRANKED'
  if (row?.cloudflare_rank_error) return `Unavailable (${row.cloudflare_rank_error})`
  return '—'
}

function formatHoldImpactLevel(level) {
  if (!level) return 'Unknown'
  return String(level).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const HOLD_IMPACT_UNKNOWN_REASON =
  'Cloudflare Radar rank impact is unavailable or unknown; do not use rank as hold-impact evidence.'

const BUCKET_TO_HOLD_IMPACT_LEVEL = {
  TOP_100: 'critical',
  TOP_1K: 'critical',
  TOP_5K: 'high',
  TOP_10K: 'high',
  TOP_100K: 'medium',
  TOP_1M: 'low',
  UNRANKED: 'none',
  UNKNOWN: 'unknown',
}

const HOLD_IMPACT_REASON_BY_LEVEL = {
  critical:
    'Domain is highly ranked by Cloudflare Radar popularity data; review potential blast radius before any hold action.',
  high:
    'Domain is within a high-popularity Cloudflare Radar bucket; escalate or review blast radius before any hold action.',
  medium:
    'Domain has measurable Cloudflare Radar popularity; consider business or customer impact before hold action.',
  low:
    'Domain appears in a lower Cloudflare Radar popularity bucket; hold-impact risk appears lower but still requires analyst review.',
  none:
    'Domain is not ranked in the Cloudflare Radar popularity bucket used by MDI; no rank-based hold-impact warning.',
  unknown: HOLD_IMPACT_UNKNOWN_REASON,
}

/** Display-only hold-impact resolution for table/drawer (MDI-50C-A). */
function resolveHoldImpact(row) {
  let level = row?.hold_impact_level ?? null
  let reason = row?.hold_impact_reason ?? null

  if (!level && row?.cloudflare_rank_bucket) {
    level = BUCKET_TO_HOLD_IMPACT_LEVEL[row.cloudflare_rank_bucket] ?? 'unknown'
  }
  if (!level) {
    level = 'unknown'
  }
  if (!reason) {
    reason = HOLD_IMPACT_REASON_BY_LEVEL[level] ?? HOLD_IMPACT_UNKNOWN_REASON
  }
  return { level, reason }
}

function holdImpactBadgeClass(level) {
  return {
    critical: 'badge-hi-critical',
    high: 'badge-hi-high',
    medium: 'badge-hi-medium',
    low: 'badge-hi-low',
    none: 'badge-hi-none',
    unknown: 'badge-hi-unknown',
  }[level] ?? 'badge-hi-unknown'
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
  return r.input_type === 'url' || r.input_type === 'domain'
}
function scanRowTitle(r, job, actionInProgress) {
  if (!r || !job) return 'Select a row first'
  if (actionInProgress) return 'A refresh/scan action is already in progress'
  if (isRowHeld(r)) return 'Row is on hold — scan not available'
  if (!r.input_normalized) return 'Row not eligible for scan'
  if (!canScanRow(r, job)) return 'Row not eligible for scan'
  if (r.input_type === 'domain') return 'Requests VT domain reanalysis.'
  if (r.input_type === 'url') return 'Submits URL for VT scan.'
  return 'Row not eligible for scan'
}
function canRefreshRow(r) {
  return !isRowHeld(r) && !!r.input_normalized
}
function vtReportUrlForRow(r) {
  return r?.vt_report_url ?? null
}
function canOpenVtRow(r) {
  return !!vtReportUrlForRow(r)
}
function openVtRowTitle(r) {
  return canOpenVtRow(r)
    ? 'Open VirusTotal report in a new tab (no quota consumed)'
    : 'VirusTotal link unavailable for this result.'
}
function refreshRowTitle(r, job, actionInProgress) {
  if (!r || !job) return 'Job required for refresh'
  if (actionInProgress) return 'A refresh/scan action is already in progress'
  if (!canRefreshRow(r)) return 'Row not eligible for refresh'
  return 'Refresh existing VT report (1 quota unit)'
}
function exportEvidenceRowTitle(r, actionInProgress) {
  if (!r) return 'Select a row first'
  if (actionInProgress) return 'An action is already in progress'
  return 'Download evidence JSON for this row (no quota consumed)'
}
function handleOpenVtRow(r) {
  const url = vtReportUrlForRow(r)
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}
function countStaleScannable(results, job) {
  return (results || []).filter(r => isRowStale(r) && canScanRow(r, job)).length
}
function countSelectedScannable(results, selectedIds, job) {
  return (results || []).filter(r => selectedIds.has(r.position) && canScanRow(r, job)).length
}

function isFlagged(r)       { return FLAGGED_BUCKET_SET.has(r?.triage_bucket) }
function isExportFlagged(r) {
  if (isRowHeld(r)) return false
  if (FLAGGED_BUCKET_SET.has(r?.triage_bucket)) return true
  return (r?.vt_hits ?? 0) > 0 || (r?.vt_suspicious ?? 0) > 0
}

// ── MDI error display helpers (MDI-22B) ───────────────────────────────────────

const ERROR_SEVERITIES = new Set(['error', 'warning', 'skip', 'info'])

const CODE_SKIP = new Set([
  'quota_exhausted', 'quota_blocked', 'scan_not_supported', 'vt_scan_not_supported',
  'no_flagged_rows', 'no_rows',
])

function inferClientSeverity(code, source) {
  if (!code) return 'error'
  if (code === 'quota_lock_timeout' || code === 'no_api_key' || code === 'auth_error') return 'error'
  if (code.startsWith('vt_') || (code.startsWith('vt') && code !== 'vt_scan_not_supported' && code !== 'vt_scan_pending')) {
    return 'error'
  }
  if (CODE_SKIP.has(code)) return 'skip'
  if (code === 'whois_failed' || code === 'enrichment_error') return 'warning'
  if (code.startsWith('live_check_') || ['dns_failed', 'redirect_blocked', 'blocked', 'tls_error'].includes(code)) {
    return 'warning'
  }
  if (code.startsWith('auto_rescan_')) {
    if (code.includes('quota_blocked') || code.includes('lock')) return 'warning'
    return 'info'
  }
  if (code === 'vt_scan_pending') return 'warning'
  return 'error'
}

function inferClientCategory(code, source) {
  if (source && source !== 'unknown') {
    if (source === 'input_parser') return 'input_validation'
    if (source === 'upload_parser') return 'upload_parse'
    if (source === 'domain_enrichment') return 'rdap_whois'
    if (source === 'live_check') return 'live_check'
    if (source === 'vt_service' || source === 'vt') return 'vt_lookup'
    if (source === 'auto_rescan') return 'auto_rescan'
    if (source === 'export_service') return 'export'
  }
  if (!code) return 'unknown'
  if (code.startsWith('invalid_') || code === 'parse_error' || code === 'unsupported_scheme') return 'input_validation'
  if (code.startsWith('live_check_')) return 'live_check'
  if (code.startsWith('auto_rescan_')) return 'auto_rescan'
  if (code.startsWith('vt_') || ['timeout', 'rate_limited', 'connection_error', 'server_error', 'not_found'].includes(code)) {
    return 'vt_lookup'
  }
  if (['quota_exhausted', 'quota_blocked', 'quota_lock_timeout'].includes(code)) return 'quota'
  return 'unknown'
}

const ENRICHMENT_LOOKUP_ERROR_CODES = new Set(['whois_failed', 'enrichment_error', 'rdap_failed'])

function hasPreservedEnrichmentMetadata(row) {
  if (!row) return false
  if (row.created_at) return true
  if (row.registrar) return true
  if (row.nameservers?.length > 0) return true
  if (row.epp_status?.length > 0) return true
  if (row.domain_hold?.source === 'uploaded_file') return true
  return false
}

function isEnrichmentLookupError(error) {
  const n = normalizeMdiError(error)
  if (!n) return false
  return n.source === 'domain_enrichment' || ENRICHMENT_LOOKUP_ERROR_CODES.has(n.code)
}

function enrichmentErrorDisplayMessage(error, row) {
  const n = normalizeMdiError(error)
  if (!n) return ''
  if (!isEnrichmentLookupError(error) || !ENRICHMENT_LOOKUP_ERROR_CODES.has(n.code)) {
    return n.message
  }
  if (hasPreservedEnrichmentMetadata(row)) {
    return 'Live RDAP/WHOIS lookup unavailable; preserved metadata is still shown where available.'
  }
  if (n.code === 'enrichment_error') {
    return 'Live RDAP/WHOIS enrichment lookup unavailable for this domain.'
  }
  return 'RDAP and WHOIS lookup unavailable for this domain.'
}

function normalizeMdiError(error) {
  if (error == null) return null
  if (typeof error === 'string') {
    return {
      code: 'unknown',
      message: error,
      source: 'unknown',
      retriable: false,
      category: 'unknown',
      severity: 'error',
      blocks_triage: true,
    }
  }
  const code = error.code || 'unknown'
  const category = error.category || inferClientCategory(code, error.source)
  const severity = error.severity && ERROR_SEVERITIES.has(error.severity)
    ? error.severity
    : inferClientSeverity(code, error.source)
  const blocks_triage = error.blocks_triage != null
    ? Boolean(error.blocks_triage)
    : severity === 'error'
  return {
    code,
    message: error.message || String(code),
    source: error.source || 'unknown',
    retriable: Boolean(error.retriable),
    category,
    severity,
    blocks_triage,
  }
}

function getErrorSeverity(error) {
  return normalizeMdiError(error)?.severity ?? 'error'
}

function errorSeverityLabel(severity) {
  return { error: 'ERROR', warning: 'WARNING', skip: 'SKIPPED', info: 'INFO' }[severity] ?? 'ERROR'
}

function getErrorSeverityClass(severity) {
  return {
    error: 'error-notice-row--error',
    warning: 'error-notice-row--warning',
    skip: 'error-notice-row--skip',
    info: 'error-notice-row--info',
  }[severity] ?? 'error-notice-row--error'
}

function severityBadgeClass(severity) {
  return {
    error: 'badge-error',
    warning: 'badge-warning',
    skip: 'badge-skip',
    info: 'badge-info',
  }[severity] ?? 'badge-error'
}

function formatMdiError(error, options = {}) {
  const n = normalizeMdiError(error)
  if (!n) return ''
  const { short = true, includeMeta = false, row = null } = options
  const message = row != null ? enrichmentErrorDisplayMessage(error, row) : n.message
  const label = errorSeverityLabel(n.severity).toLowerCase()
  if (short) {
    return `[${label}] ${n.code}: ${message}`
  }
  const lines = [`${n.code}: ${message}`]
  if (includeMeta) {
    const meta = []
    if (n.source && n.source !== 'unknown') meta.push(`source: ${n.source}`)
    if (n.category && n.category !== 'unknown') meta.push(`category: ${n.category}`)
    meta.push(`retriable: ${n.retriable ? 'yes' : 'no'}`)
    if (meta.length) lines.push(meta.join(' · '))
  }
  return lines.join('\n')
}

function formatMdiErrorList(errors, row = null) {
  if (!errors?.length) return ''
  return errors.map(e => formatMdiError(e, { short: true, row })).filter(Boolean).join('; ')
}

function formatApiErrorDetail(detail, prefix) {
  if (detail == null || detail === '') {
    return prefix || ''
  }
  if (typeof detail === 'string') {
    return prefix ? `${prefix}: ${detail}` : detail
  }
  const code = detail.code
  const msg = detail.message || detail.error
  if (code && msg) {
    const text = `[${code}] ${msg}`
    return prefix ? `${prefix}: ${text}` : text
  }
  if (msg) return prefix ? `${prefix}: ${msg}` : msg
  if (code) return prefix ? `${prefix}: [${code}]` : `[${code}]`
  try {
    const fallback = JSON.stringify(detail)
    return prefix ? `${prefix}: ${fallback}` : fallback
  } catch {
    return prefix ? `${prefix}: Request failed` : 'Request failed'
  }
}

function hasBlockingErrors(errors) {
  return (errors || []).some(e => normalizeMdiError(e)?.blocks_triage)
}

function hasWarningsOnly(errors) {
  const list = (errors || []).map(normalizeMdiError).filter(Boolean)
  if (!list.length) return false
  return list.every(e => e.severity === 'warning')
}

function hasSkipsOnly(errors) {
  const list = (errors || []).map(normalizeMdiError).filter(Boolean)
  if (!list.length) return false
  return list.every(e => e.severity === 'skip' || e.severity === 'info')
}

function dashboardSeverityHint(code) {
  return inferClientSeverity(code)
}

function formatDuplicateDisplay(d) {
  if (d == null) return '—'
  if (typeof d === 'object') {
    return d.input_original ?? d.duplicate_of ?? d.input_normalized ?? '—'
  }
  return String(d)
}

function ErrorNoticeList({ errors, row = null }) {
  if (!errors?.length) return null
  return (
    <div className="error-notice-list">
      {errors.map((e, i) => {
        const n = normalizeMdiError(e)
        if (!n) return null
        const message = row != null ? enrichmentErrorDisplayMessage(e, row) : n.message
        const meta = []
        if (n.source && n.source !== 'unknown') meta.push(n.source)
        if (n.category && n.category !== 'unknown') meta.push(n.category)
        meta.push(`retriable: ${n.retriable ? 'yes' : 'no'}`)
        return (
          <div key={i} className={`error-notice-row ${getErrorSeverityClass(n.severity)}`}>
            <span className={`badge ${severityBadgeClass(n.severity)}`}>{errorSeverityLabel(n.severity)}</span>
            <code className="error-code">{n.code}</code>
            <span className="error-message">{message}</span>
            {meta.length > 0 && <span className="error-meta">{meta.join(' · ')}</span>}
          </div>
        )
      })}
    </div>
  )
}

function RejectedItemRow({ item }) {
  const original = item.input_original ?? item.original ?? '—'
  const err = normalizeMdiError(
    item.error ?? (item.reason ? { code: 'invalid_input', message: item.reason, source: 'input_parser' } : null)
  )
  const rowClass = err ? getErrorSeverityClass(err.severity) : 'error-notice-row--error'
  return (
    <div className={`error-notice-row ${rowClass}`}>
      <code className="error-code">{original}</code>
      {err && (
        <>
          <span className={`badge ${severityBadgeClass(err.severity)}`}>{errorSeverityLabel(err.severity)}</span>
          <code className="error-code">{err.code}</code>
          <span className="error-message">{err.message}</span>
        </>
      )}
    </div>
  )
}

function EvidenceErrorIndicator({ errors, evidenceStatus, row = null }) {
  if (!errors?.length) return null
  const title = formatMdiErrorList(errors, row)
  const blocking = hasBlockingErrors(errors)
  const warningsOnly = hasWarningsOnly(errors)
  const skipsOnly = hasSkipsOnly(errors)
  if (skipsOnly && !blocking && !warningsOnly) {
    if (evidenceStatus === 'skipped_hold' || evidenceStatus === 'none') {
      return <span className="evidence-err-icon evidence-err-icon--skip" title={title}>SKIP</span>
    }
    return <span className="evidence-err-icon evidence-err-icon--skip" title={title}>⊘</span>
  }
  if (blocking) {
    return <span className="evidence-err-icon evidence-err-icon--error" title={title}>⚠</span>
  }
  if (warningsOnly) {
    return <span className="evidence-err-icon evidence-err-icon--warning" title={title}>⚠</span>
  }
  return <span className="evidence-err-icon evidence-err-icon--warning" title={title}>⚠</span>
}

async function downloadJobExport(jobId, { format, scope, positions }) {
  const resp = await fetch(`${API_BASE}/api/mdi/jobs/${jobId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ format, scope, positions: positions ?? null }),
  })
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}))
    throw new Error(formatApiErrorDetail(data?.detail, 'Export failed') || `Export failed: HTTP ${resp.status}`)
  }
  const blob = await resp.blob()
  const cd = resp.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="([^"]+)"/)
  const fallbackTs = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 15)
  const ext = format === 'json' ? 'json' : 'csv'
  const prefix = format === 'json' ? 'mdi_evidence' : 'mdi_export'
  const filename = match ? match[1] : `${prefix}_${scope}_${fallbackTs}.${ext}`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
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
function parseCreatedDate(val) {
  if (!val) return null
  const time = Date.parse(val)
  if (!Number.isNaN(time)) return new Date(time)
  const s = String(val).substring(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(`${s}T00:00:00Z`) : null
}
function formatCalculatedAge(createdAt, now = new Date()) {
  const created = parseCreatedDate(createdAt)
  if (!created) return 'Unknown'
  const diffMs = now.getTime() - created.getTime()
  if (!Number.isFinite(diffMs) || diffMs < 0) return 'Unknown'
  const days = Math.floor(diffMs / 86400000)
  if (days < 1) return '<1d'
  if (days < 30) return `${days}d`
  const totalMonths = Math.floor(days / 30.4375)
  if (totalMonths < 12) return `${Math.max(1, totalMonths)}mo`
  const years = Math.floor(totalMonths / 12)
  const months = totalMonths % 12
  return months > 0 ? `${years}y ${months}m` : `${years}y`
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
  { key: 'all',     label: 'All',                     color: 'var(--c-all)', filter: 'all' },
  { key: 'held',    label: 'Domain On Hold',          color: 'var(--c-held)', filter: 'held' },
  { key: 'flr',     label: 'Flagged + Live + Recent', color: 'var(--c-flr)', filter: 'flr' },
  { key: 'fl',      label: 'Flagged + Live',          color: 'var(--c-fl)',  filter: 'fl'  },
  { key: 'fr',      label: 'Flagged + Recent',        color: 'var(--c-fr)',  filter: 'fr'  },
  { key: 'fs',      label: 'Flagged + Stale',         color: 'var(--c-fs)',  filter: 'fs'  },
  { key: 'fnl',     label: 'Flagged + No-Live',       color: 'var(--c-fnl)', filter: 'fnl' },
  { key: 'unknown', label: 'Unknown / Errors',        color: 'var(--c-unk)', filter: 'unknown' },
  { key: 'clean',   label: 'Clean',                   color: 'var(--c-cln)', filter: 'clean' },
]

function filterLabelForKey(key) {
  return TRIAGE_CARDS.find(c => c.filter === key)?.label ?? key
}

function formatJobIdDisplay(id) {
  if (!id) return ''
  if (id.length <= 22) return id
  return `${id.slice(0, 8)}…${id.slice(-4)}`
}

function parseJobUtcDateString(job) {
  if (!job) return null
  const raw = job.completed_at ?? job.submitted_at ?? job.started_at ?? job.finished_at
  if (raw == null) return null
  try {
    if (typeof raw === 'number') {
      return new Date(raw * 1000).toISOString().slice(0, 10)
    }
    const s = String(raw).trim()
    if (/^\d+(\.\d+)?$/.test(s)) {
      return new Date(parseFloat(s) * 1000).toISOString().slice(0, 10)
    }
    if (s.length >= 10 && /^\d{4}-\d{2}-\d{2}/.test(s)) {
      return s.slice(0, 10)
    }
  } catch { /* fall through */ }
  return null
}

function isPreviousUtcQuotaDayJob(job, quotaDateUtc) {
  if (!job || !quotaDateUtc) return false
  if (job.status === 'running' || job.status === 'queued') return false
  const jobDate = parseJobUtcDateString(job)
  if (!jobDate) return false
  return jobDate < quotaDateUtc
}

function formatRecoveredJobQuotaNote(job, attempted, completed) {
  const lookups = job?.lookups_used
  if (lookups != null && lookups >= 0) {
    return `Completed previous UTC day · ${lookups} VT lookup${lookups !== 1 ? 's' : ''} on this job`
  }
  if (attempted > 0 || completed > 0) {
    return `Completed previous UTC day · ${completed} / ${attempted} processed`
  }
  return 'Completed previous UTC day'
}

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

// ── Dashboard panel (MDI-17) ────────────────────────────────────────────────

const DASHBOARD_WINDOWS = [
  { key: 'current', label: 'Current' },
  { key: 'last_7_days', label: '7 Days' },
  { key: 'last_30_days', label: '30 Days' },
  { key: 'all_time', label: 'All Time' },
]

const DASHBOARD_SOURCE_FILTERS = [
  { key: 'mdi', label: 'MDI' },
  { key: 'all', label: 'All VT Tools' },
  { key: 'vt_bulk_check', label: 'VT Bulk Check' },
]

const DASHBOARD_SOURCE_HELP = {
  mdi: 'MDI jobs only — shared operational metrics and MDI triage/enrichment for the selected time window.',
  all: 'Shared VT operational metrics across MDI and VT Bulk Check. MDI triage and enrichment remain MDI-only.',
  vt_bulk_check: 'VT Bulk Check jobs only — shared operational metrics for that source. MDI triage is not applicable.',
}

const DASHBOARD_WINDOW_HELP = {
  current: 'Metrics for the current in-memory or recovered MDI job.',
  last_7_days: 'Aggregated metrics from usage history for the last 7 UTC days.',
  last_30_days: 'Aggregated metrics from usage history for the last 30 UTC days.',
  all_time: 'Aggregated metrics from all available usage history.',
}

function dashboardSourceLabel(key) {
  return DASHBOARD_SOURCE_FILTERS.find(f => f.key === key)?.label || key
}

function formatRecordsBySource(recordsBySource) {
  if (!recordsBySource) return null
  const parts = []
  if (recordsBySource.mdi) parts.push(`MDI ${recordsBySource.mdi}`)
  if (recordsBySource.vt_bulk_check) parts.push(`VT Bulk ${recordsBySource.vt_bulk_check}`)
  if (recordsBySource.legacy) parts.push(`Legacy / Unattributed ${recordsBySource.legacy}`)
  return parts.length ? parts.join(' · ') : null
}

function DashboardQuotaSection({ liveQuota, quotaTrend }) {
  const rows = quotaTrend?.available ? (quotaTrend.last_7_days || []) : []
  const todayUtc = new Date().toISOString().slice(0, 10)

  return (
    <section className="dashboard-metric-section" aria-label="Shared VT quota visibility">
      <div className="dashboard-section-label">Shared VT quota</div>
      <p className="dashboard-metric-scope">
        Live counter reflects combined MDI + VT Bulk Check usage today. Daily trend uses
        unified daily-history totals; per-tool columns appear when schema v2 data exists.
      </p>
      {liveQuota?.available && (
        <div className="dashboard-cards dashboard-cards-quota-live">
          <div className="dashboard-card">
            <span className="dashboard-card-label">Live used today</span>
            <span className="dashboard-card-value">{dashFmt(liveQuota.daily_lookups_used)}</span>
          </div>
          <div className="dashboard-card">
            <span className="dashboard-card-label">Remaining</span>
            <span className="dashboard-card-value">{dashFmt(liveQuota.remaining)}</span>
          </div>
          <div className="dashboard-card">
            <span className="dashboard-card-label">Daily limit</span>
            <span className="dashboard-card-value">{dashFmt(liveQuota.daily_limit)}</span>
          </div>
        </div>
      )}
      {!liveQuota?.available && liveQuota?.error && (
        <p className="dashboard-quality-note">Live quota counter unavailable ({liveQuota.error}).</p>
      )}
      {rows.length > 0 ? (
        <div className="dashboard-table-section">
          <div className="dashboard-section-label dashboard-section-label-inline">7-day daily-history trend</div>
          <table className="dashboard-table dashboard-quota-trend-table">
            <colgroup>
              <col className="dashboard-quota-trend-col-date" />
              <col className="dashboard-quota-trend-col-num" />
              <col className="dashboard-quota-trend-col-num" />
              <col className="dashboard-quota-trend-col-num" />
              <col className="dashboard-quota-trend-col-num" />
            </colgroup>
            <thead>
              <tr>
                <th>Date (UTC)</th>
                <th>Total</th>
                <th>MDI</th>
                <th>VT Bulk</th>
                <th>Legacy</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.date} className={row.date === todayUtc ? 'dashboard-quota-trend-today' : undefined}>
                  <td>{row.date}{row.date === todayUtc ? ' (today)' : ''}</td>
                  <td>{dashFmt(row.quota_units)}</td>
                  <td>{dashFmt(row.mdi_quota_units)}</td>
                  <td>{dashFmt(row.vt_bulk_check_quota_units)}</td>
                  <td>{dashFmt(row.legacy_quota_units)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="dashboard-empty-msg">Daily quota trend unavailable.</p>
      )}
    </section>
  )
}

function dashFmt(value, suffix = '') {
  if (value == null || value === '') return '—'
  return `${value}${suffix}`
}

function formatDashboardRuntime(seconds) {
  if (seconds == null || seconds === '') return '—'
  const s = Number(seconds)
  if (!Number.isFinite(s) || s < 0) return '—'

  if (s >= 3600) {
    const h = Math.floor(s / 3600)
    const rem = s % 3600
    const m = Math.floor(rem / 60)
    const sec = Math.round(rem % 60)
    if (m > 0 && sec > 0) return `${h}h ${m}m ${sec}s`
    if (m > 0) return `${h}h ${m}m`
    return sec > 0 ? `${h}h ${sec}s` : `${h}h`
  }

  if (s >= 60) {
    const m = Math.floor(s / 60)
    const sec = Math.round(s % 60)
    return sec > 0 ? `${m}m ${sec}s` : `${m}m`
  }

  if (s >= 10) return `${Math.round(s)} sec`

  return `${(Math.round(s * 10) / 10).toFixed(1)} sec`
}

function dashPct(value) {
  if (value == null) return '—'
  return `${value}%`
}

function DashboardPanel({ open, id, data, loading, error, activeWindow, onWindowChange, sourceFilter, onSourceFilterChange, onRefresh, onClose }) {
  if (!open) return null
  const win = data?.windows?.[activeWindow] ?? {}
  const isCurrent = activeWindow === 'current'
  const sourceHelp = DASHBOARD_SOURCE_HELP[sourceFilter] || ''
  const windowHelp = DASHBOARD_WINDOW_HELP[activeWindow] || ''
  const recordsSummary = formatRecordsBySource(data?.data_quality?.records_by_source)
  const mdiTriageApplicable = win.triage_metrics_applicable !== false
  const triageRows = mdiTriageApplicable && win.triage_bucket_counts
    ? Object.entries(win.triage_bucket_counts).sort((a, b) => b[1] - a[1])
    : []
  const opRows = mdiTriageApplicable && win.operation_counts
    ? Object.entries(win.operation_counts).sort((a, b) => b[1] - a[1])
    : []
  const errRows = mdiTriageApplicable && win.error_code_counts
    ? Object.entries(win.error_code_counts).sort((a, b) => b[1] - a[1])
    : []
  const mdiTriageLabel = win.triage_metrics_label || (sourceFilter === 'all' ? 'MDI only' : null)

  return (
    <div className="dashboard-panel" id={id} role="region" aria-label="MDI Operational Dashboard">
      <div className="dashboard-panel-header">
        <span className="dashboard-panel-title">Operational Dashboard</span>
        <div className="dashboard-panel-header-actions">
          <button type="button" className="btn btn-ghost dashboard-refresh-btn" onClick={onRefresh} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
          <button type="button" className="dashboard-close-btn" onClick={onClose} aria-label="Close dashboard">×</button>
        </div>
      </div>
      <div className="dashboard-panel-body">
        <div className="dashboard-window-tabs dashboard-source-tabs" role="tablist" aria-label="Dashboard source filter">
          {DASHBOARD_SOURCE_FILTERS.map(f => (
            <button
              key={f.key}
              type="button"
              role="tab"
              aria-selected={sourceFilter === f.key}
              className={`dashboard-window-tab${sourceFilter === f.key ? ' active' : ''}`}
              onClick={() => onSourceFilterChange(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="dashboard-source-banner">
          <div className="dashboard-source-banner-title">
            Viewing: <strong>{dashboardSourceLabel(sourceFilter)}</strong>
            <span className="dashboard-source-banner-window"> · {DASHBOARD_WINDOWS.find(w => w.key === activeWindow)?.label}</span>
          </div>
          <p className="dashboard-source-banner-help">{sourceHelp}</p>
          {windowHelp && <p className="dashboard-source-banner-help dashboard-source-banner-window-help">{windowHelp}</p>}
          {recordsSummary && (
            <p className="dashboard-source-banner-records">Usage history records on disk: {recordsSummary}</p>
          )}
        </div>
        <div className="dashboard-window-tabs">
          {DASHBOARD_WINDOWS.map(w => (
            <button
              key={w.key}
              type="button"
              className={`dashboard-window-tab${activeWindow === w.key ? ' active' : ''}`}
              onClick={() => onWindowChange(w.key)}
            >
              {w.label}
            </button>
          ))}
        </div>

        {error && <p className="dashboard-error-msg">{error}</p>}
        {loading && !data && <p className="dashboard-empty-msg">Loading dashboard…</p>}

        {data && (
          <>
            <DashboardQuotaSection liveQuota={data.live_quota} quotaTrend={data.quota_trend} />

            {isCurrent && !win.available && (
              <p className="dashboard-empty-msg">No current job available.</p>
            )}
            {(!isCurrent || win.available) && (
              <>
                <section className="dashboard-metric-section" aria-label="Shared VT metrics">
                  <div className="dashboard-section-label">
                    Shared VT metrics
                    <span className="dashboard-section-scope"> ({dashboardSourceLabel(sourceFilter)} · {DASHBOARD_WINDOWS.find(w => w.key === activeWindow)?.label})</span>
                  </div>
                  <div className="dashboard-cards dashboard-cards-shared">
                    <div className="dashboard-card"><span className="dashboard-card-label">Jobs</span><span className="dashboard-card-value">{dashFmt(isCurrent ? (win.available ? 1 : 0) : win.jobs_run)}</span></div>
                    <div className="dashboard-card"><span className="dashboard-card-label">Items processed</span><span className="dashboard-card-value">{dashFmt(win.processed ?? win.items_completed)}</span></div>
                    <div className="dashboard-card"><span className="dashboard-card-label">VT quota used</span><span className="dashboard-card-value">{dashFmt(win.lookups_used ?? win.quota_units_consumed)}</span></div>
                    <div className="dashboard-card"><span className="dashboard-card-label">Quota blocked</span><span className="dashboard-card-value">{dashFmt(win.quota_blocked_count)}</span></div>
                    <div className="dashboard-card"><span className="dashboard-card-label">Avg runtime</span><span className="dashboard-card-value">{formatDashboardRuntime(win.job_duration_seconds ?? win.avg_runtime_seconds)}</span></div>
                    <div className="dashboard-card"><span className="dashboard-card-label">Avg items/job</span><span className="dashboard-card-value">{dashFmt(win.avg_items_per_job)}</span></div>
                    <div className="dashboard-card"><span className="dashboard-card-label">VT scans requested</span><span className="dashboard-card-value">{dashFmt(win.scan_requested_count)}</span></div>
                  </div>
                </section>

                {mdiTriageApplicable ? (
                  <section className="dashboard-metric-section" aria-label="MDI triage and enrichment metrics">
                    {mdiTriageLabel && !isCurrent && (
                      <p className="dashboard-metric-scope">{mdiTriageLabel} — triage and enrichment metrics</p>
                    )}
                    {isCurrent && sourceFilter === 'all' && (
                      <p className="dashboard-metric-scope">MDI only — current job triage metrics</p>
                    )}
                    <div className="dashboard-section-label">MDI triage &amp; enrichment</div>
                    <div className="dashboard-cards dashboard-cards-triage">
                      <div className="dashboard-card"><span className="dashboard-card-label">Flagged %</span><span className="dashboard-card-value">{dashPct(win.flagged_percent)}</span></div>
                      <div className="dashboard-card"><span className="dashboard-card-label">Clean %</span><span className="dashboard-card-value">{dashPct(win.clean_percent)}</span></div>
                      <div className="dashboard-card"><span className="dashboard-card-label">Unknown/Error %</span><span className="dashboard-card-value">{dashPct(win.unknown_error_percent)}</span></div>
                      <div className="dashboard-card"><span className="dashboard-card-label">Held %</span><span className="dashboard-card-value">{dashPct(win.held_percent)}</span></div>
                      <div className="dashboard-card"><span className="dashboard-card-label">Live checks</span><span className="dashboard-card-value">{dashFmt(win.live_check_count)}</span></div>
                      <div className="dashboard-card"><span className="dashboard-card-label">RDAP/WHOIS</span><span className="dashboard-card-value">{dashFmt((win.rdap_enriched_count ?? 0) + (win.whois_fallback_count ?? 0))}</span></div>
                      <div className="dashboard-card"><span className="dashboard-card-label">Auto-rescan attempts</span><span className="dashboard-card-value">{dashFmt(win.auto_rescan_attempted_count)}</span></div>
                    </div>
                  </section>
                ) : (
                  <p className="dashboard-quality-note dashboard-na-note">
                    <strong>MDI triage &amp; enrichment: Not Applicable</strong> for the VT Bulk Check source
                    filter. Shared operational metrics above still reflect VT Bulk Check jobs only.
                  </p>
                )}

                {triageRows.length > 0 && (
                  <div className="dashboard-table-section">
                    <div className="dashboard-section-label">Triage bucket breakdown</div>
                    <table className="dashboard-table">
                      <tbody>
                        {triageRows.map(([k, v]) => (
                          <tr key={k}><td>{k}</td><td>{v}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {opRows.length > 0 && (
                  <div className="dashboard-table-section">
                    <div className="dashboard-section-label">Operation breakdown</div>
                    <table className="dashboard-table">
                      <tbody>
                        {opRows.map(([k, v]) => (
                          <tr key={k}><td>{k}</td><td>{v}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {errRows.length > 0 && (
                  <div className="dashboard-table-section">
                    <div className="dashboard-section-label">Error code breakdown</div>
                    <table className="dashboard-table">
                      <tbody>
                        {errRows.map(([k, v]) => (
                          <tr key={k}>
                            <td>{k} <span className="error-meta">({dashboardSeverityHint(k)})</span></td>
                            <td>{v}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {win.triage_metrics_available === false && mdiTriageApplicable && !isCurrent && (
                  <p className="dashboard-quality-note">MDI triage percentages unavailable for older history records.</p>
                )}
              </>
            )}

            {data.data_quality?.notes?.length > 0 && (
              <div className="dashboard-quality-note">
                {data.data_quality.notes.map((n, i) => <div key={i}>{n}</div>)}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Settings panel ────────────────────────────────────────────────────────────

function CollapsibleSettingsPanel({
  open, id,
  staleThresholdDays, setStaleThresholdDays,
  autoRescanStale, setAutoRescanStale,
  maxAutoRescans, setMaxAutoRescans,
  cloudflareRankLookupEnabled, setCloudflareRankLookupEnabled,
  locked,
}) {
  if (!open) return null
  const ctrlStyle = locked ? { opacity: 0.55, pointerEvents: 'none' } : {}
  return (
    <div className="settings-panel" id={id} role="region" aria-label="Advanced Settings">
      <div className="settings-panel-header">
        <span className="settings-panel-title">Advanced Settings</span>
        {locked && <span style={{ fontSize: 9, color: 'var(--status-warning)' }}>Locked</span>}
      </div>
      <div className="settings-panel-body">
        <p className="settings-info-note">
          These options apply to your next Estimate or Run MDI Check. Values are saved with the job at submit time.
          Domain report mode is configured under Run Options in the sidebar.
        </p>
        {locked && (
          <p className="settings-panel-locked-msg">
            Settings are locked while reviewing results. Saved options for this job are shown above.
            Editable settings below apply to your next run.
          </p>
        )}

        <div>
          <p className="settings-section-label">VT freshness</p>
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
                  aria-label="Stale threshold in days"
                />
                <span style={{ fontSize: 10, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>days</span>
              </div>
            </div>
            <p style={{ fontSize: 10, color: 'var(--text-faint)', lineHeight: 1.4 }}>
              VT reports older than this are classified Stale. Default: 7 days. No quota consumed by this setting alone.
            </p>
          </div>
        </div>

        <div style={{ marginTop: 14 }}>
          <p className="settings-section-label">Auto-rescan (initial job only)</p>
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
                aria-label="Maximum auto-rescans per job"
              />
            </div>
            <p className="settings-auto-rescan-warning">
              Available and off by default. When enabled, auto-rescan runs only during initial job submission
              (not on recovered jobs) and may consume additional VirusTotal quota — use cautiously on large batches.
              It may request URL scans and domain reanalysis for stale flagged items.
            </p>
          </div>
        </div>

        <div style={{ marginTop: 14 }}>
          <p className="settings-section-label">Cloudflare Radar (experimental)</p>
          <div style={{ ...ctrlStyle, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label className="settings-checkbox-row">
              <input
                type="checkbox"
                checked={cloudflareRankLookupEnabled}
                onChange={e => setCloudflareRankLookupEnabled(e.target.checked)}
                disabled={locked}
              />
              <span>Cloudflare Radar rank lookup</span>
            </label>
            <p style={{ fontSize: 10, color: 'var(--text-faint)', lineHeight: 1.4 }}>
              Popularity / blast-radius context from Cloudflare 1.1.1.1 DNS data only.
              Does not change VT verdict or triage. Does not consume VT quota. Default off.
              Hold-impact guidance is planned for a later release (MDI-50C).
            </p>
          </div>
        </div>

        <div style={{ marginTop: 14 }}>
          <p className="settings-section-label">Exports and live checks</p>
          <div className="settings-info-block">
            <p className="settings-info-heading">Exports</p>
            <p className="settings-info-text">
              Exports are available from Results bulk actions, row More Actions, and the detail drawer.
              CSV (all, flagged, selected) and JSON evidence per row require a completed job. No export consumes VT quota.
              Additional export scopes may be reviewed in a future ticket.
            </p>
          </div>
          <div className="settings-info-block" style={{ marginTop: 8 }}>
            <p className="settings-info-heading">Live checks</p>
            <p className="settings-info-text">
              Live checks currently run for eligible flagged items during job processing. Scope is fixed today —
              custom live-check controls are deferred (future backlog). See Run Options in the sidebar for the current rule.
            </p>
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
        <div className="error-notice-list" style={{ maxHeight: 90, overflowY: 'auto', background: 'var(--bg-input)', border: '1px solid var(--border-soft)', borderRadius: 4, padding: '6px 10px' }}>
          {preview.rejected.map((r, i) => <RejectedItemRow key={i} item={r} />)}
        </div>
      )}
      {showDupes && preview.duplicates?.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', maxHeight: 60, overflowY: 'auto', background: 'var(--bg-input)', border: '1px solid var(--border-soft)', borderRadius: 4, padding: '6px 10px' }}>
          {preview.duplicates.map((d, i) => (
            <div key={i}><code className="error-code">{formatDuplicateDisplay(d)}</code></div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Setup workflow guidance (MDI-48) ─────────────────────────────────────────

function InputActionGuidance() {
  return (
    <div className="input-action-guidance" role="note" aria-label="Estimate and run actions">
      <p>
        <span className="input-action-guidance-label">Estimate Quota &amp; Runtime</span>
        <span className="input-action-guidance-desc">
          {' '}— checks your input and previews VT quota impact and runtime before starting a job. No VT quota consumed.
        </span>
      </p>
      <p>
        <span className="input-action-guidance-label">Run MDI Check</span>
        <span className="input-action-guidance-desc">
          {' '}— starts triage and may consume VT quota for eligible domains/URLs.
        </span>
      </p>
    </div>
  )
}

function SetupWorkflowGuidance() {
  return (
    <>
      <div className="setup-workflow-guidance" role="region" aria-label="Setup workflow">
        <p className="setup-workflow-heading">Workflow</p>
        <ol className="setup-workflow-steps">
          <li><span className="setup-step-num" aria-hidden="true">1</span> Add domains or URLs</li>
          <li><span className="setup-step-num" aria-hidden="true">2</span> Estimate quota</li>
          <li><span className="setup-step-num" aria-hidden="true">3</span> Run MDI Check</li>
          <li><span className="setup-step-num" aria-hidden="true">4</span> Review triage results</li>
        </ol>
      </div>
      <div className="setup-results-placeholder">
        <p className="setup-placeholder-lead">
          After you run MDI Check, this setup view will switch to the results workspace.
        </p>
        <p className="setup-placeholder-detail">
          Paste or upload domains, estimate quota, then run MDI Check. When the job finishes,
          MDI will switch to the results workspace for triage review.
        </p>
      </div>
    </>
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
  estimate, estimateError, estimateStale,
  hasActiveResults,
  restoredFromSession, onDismissRestore,
}) {
  const hasInput = rawInput.trim().length > 0
  const lineCount = hasInput ? rawInput.trim().split('\n').filter(l => l.trim()).length : 0

  return (
    <div className={`input-panel${hasActiveResults ? ' input-panel-compact' : ''}`}>
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
        {restoredFromSession && (
          <div className="input-restored-notice" role="status">
            <span>↩ Restored previous job input</span>
            <button
              type="button"
              className="restored-dismiss-btn"
              onClick={onDismissRestore}
              title="Dismiss restored job"
              aria-label="Dismiss restored job"
            >✕</button>
          </div>
        )}
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
              <span className="input-paste-hint">
                Input is validated as you paste — no VT quota consumed.
              </span>
            )}

            {!hasActiveResults && <InputActionGuidance />}

            <EstimatePanel
              estimate={estimate}
              error={estimateError}
              stale={estimateStale}
              minimized={hasActiveResults}
            />
          </>
        )}

        {activeTab === 'upload' && (
          <>
            <div className="upload-guidance">
              <p className="upload-tab-hint">
                Upload a CSV or XLSX file (legacy .xls not supported). MDI detects the header row automatically,
                including files with leading comment rows. Validate first — no quota consumed.
              </p>
              <p className="upload-tab-hint" style={{ marginTop: 6 }}>
                <strong>Domain column</strong> (required): DNS Form, Domain, Domain Name, Hostname, Host, URL, Target, Indicator
              </p>
              <p className="upload-tab-hint" style={{ marginTop: 4 }}>
                <strong>Optional metadata</strong>: Create Date, EPP Status, Domain State, Registrar Name, Assigned Nameservers
              </p>
            </div>
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

            <div className="input-row" style={{ marginTop: 10 }}>
              <button
                className="btn btn-ghost"
                onClick={onEstimate}
                disabled={estimating || !canRunJob}
                title={!canRunJob ? 'Validate upload and wait for accepted items' : undefined}
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
            </div>
            {!canRunJob && !uploadPreviewing && selectedFile && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Validate upload to review accepted items before estimating or running.
              </span>
            )}

            {!hasActiveResults && <InputActionGuidance />}

            <EstimatePanel
              estimate={estimate}
              error={estimateError}
              stale={estimateStale}
              minimized={hasActiveResults}
            />
          </>
        )}
      </div>
    </div>
  )
}

// ── VT Usage & Status panel ───────────────────────────────────────────────────

function VtUsagePanel({ quota, quotaLoading, job, jobId }) {
  const used      = quota?.daily_lookups_used ?? 0
  const limit     = quota?.daily_limit ?? 500
  const remaining = quota?.remaining ?? (limit - used)
  const valColor  = remaining <= 0 ? 'var(--risk-critical)' : remaining < 50 ? 'var(--risk-medium)' : 'var(--text-main)'
  const quotaDateUtc = quota?.date_utc ?? null

  const hasJob    = !!job
  const attempted = job?.total ?? 0
  const completed = job?.processed ?? 0
  const queued    = Math.max(0, attempted - completed)
  const pct       = attempted > 0 ? Math.round((completed / attempted) * 100) : 0
  const isRunning = job?.status === 'running' || job?.status === 'queued'
  const isRecoveredPreviousDay = isPreviousUtcQuotaDayJob(job, quotaDateUtc)
  const runSectionLabel = isRecoveredPreviousDay ? 'Recovered job' : 'Current run'
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
          <span className="vt-stat-lbl">Used today (UTC)</span>
          <span className="vt-stat-val" style={{ color: used > 0 ? 'var(--text-main)' : 'var(--text-muted)' }}>{used}</span>
        </div>
        <div className="vt-stat-box">
          <span className="vt-stat-lbl">Remaining</span>
          <span className="vt-stat-val" style={{ color: valColor }}>{remaining}</span>
        </div>
      </div>
      <p className="vt-quota-reset-note">Daily quota resets at UTC midnight.</p>

      {hasJob && (
        <div className="current-run-section">
          <span className="current-run-label">{runSectionLabel}</span>
          {isRecoveredPreviousDay && (
            <p className="vt-recovered-job-note">{formatRecoveredJobQuotaNote(job, attempted, completed)}</p>
          )}
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
      {jobId && (
        <div className="vt-job-id-section">
          <span className="vt-job-id-label">Job ID</span>
          <code className="vt-job-id-value" title={jobId}>{formatJobIdDisplay(jobId)}</code>
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
        <span className="panel-section-label">Run Options</span>
        {locked && <span style={{ fontSize: 9, color: 'var(--status-warning)' }}>Locked</span>}
      </div>
      <div className="proc-options-body">
        <p className="proc-run-options-note">
          Options here apply to your next Estimate or Run MDI Check and are saved with the job at submit time.
          Stale threshold and auto-rescan are under Advanced Settings (gear menu).
        </p>
        {locked && (
          <p className="proc-locked-note">
            Locked while reviewing results. Saved job options are shown above; settings here apply to your next run.
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
                When enabled, bare domains use VT domain reports (typically fewer calls). When off, URL report mode is used.
              </span>
            </div>
          </div>

          <hr className="proc-divider" />

          <div className="proc-opt-row proc-opt-readonly">
            <span className="proc-opt-status-icon" aria-hidden="true">✓</span>
            <div className="proc-opt-info">
              <span className="proc-opt-name">Live checks: flagged items only</span>
              <span className="proc-opt-desc">
                Live checks run for eligible flagged items during processing. Not user-configurable today — future backlog.
              </span>
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

  const colLabels = {
    domain: 'Domain',
    created_at: 'Create Date',
    epp_status: 'EPP Status',
    domain_state: 'Domain State',
    registrar: 'Registrar',
    nameservers: 'Nameservers',
  }

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

  const heldSkippedCount = preview.held_skipped_count ?? preview.held_count ?? 0

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
            { label: 'Hold-skipped', value: heldSkippedCount, color: '#818cf8' },
          ].map(t => (
            <div key={t.label} className="summary-tile">
              <span className="tile-label">{t.label}</span>
              <span className="tile-value" style={{ color: t.color, fontSize: 18 }}>{t.value}</span>
            </div>
          ))}
        </div>
        {(preview.header_row || preview.source_sheet || preview.columns_detected) && (
          <div className="upload-columns-detected" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {preview.header_row && (
              <div>Header row detected: <strong>row {preview.header_row}</strong>
                {preview.source_sheet ? ` · sheet "${preview.source_sheet}"` : ''}
              </div>
            )}
            {preview.columns_detected && (
              <div style={{ marginTop: 4 }}>
                Columns matched:{' '}
                {Object.entries(preview.columns_detected)
                  .filter(([, v]) => v)
                  .map(([k, v]) => `${colLabels[k] || k}: "${v}"`)
                  .join(' · ') || '—'}
              </div>
            )}
            {preview.missing_optional_columns?.length > 0 && (
              <div style={{ marginTop: 4, color: 'var(--text-faint)' }}>
                Optional columns not found: {preview.missing_optional_columns.map(c => colLabels[c] || c).join(', ')}
              </div>
            )}
          </div>
        )}
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
          {heldSkippedCount > 0 && (
            <button className="btn btn-ghost" style={{ fontSize: 11 }} onClick={() => setShowHeld(v => !v)}>
              {showHeld ? 'Hide' : 'Show'} held ({heldSkippedCount})
            </button>
          )}
        </div>
        {showRejected && preview.rejected?.length > 0 && (
          <div className="error-notice-list" style={{ maxHeight: 120, overflowY: 'auto', background: 'var(--bg-input)', border: '1px solid var(--border-soft)', borderRadius: 4, padding: '6px 10px' }}>
            {preview.rejected.map((r, i) => <RejectedItemRow key={i} item={r} />)}
          </div>
        )}
        {showDupes && preview.duplicates?.length > 0 && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', maxHeight: 80, overflowY: 'auto', background: 'var(--bg-input)', border: '1px solid var(--border-soft)', borderRadius: 4, padding: '6px 10px' }}>
            {preview.duplicates.map((d, i) => (
              <div key={i}><code className="error-code">{formatDuplicateDisplay(d)}</code></div>
            ))}
          </div>
        )}
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
                    <td style={{ padding: '4px 8px', color: 'var(--text-muted)' }}>{formatRecommendedAction(r.recommended_action)}</td>
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

// ── Estimate panel (compact, input-adjacent) ──────────────────────────────────

function EstimatePanel({ estimate, error, stale, minimized }) {
  if (error) {
    return (
      <div className="estimate-panel estimate-panel-error" role="alert">
        <span className="estimate-panel-label">Estimate error</span>
        <span>{error}</span>
      </div>
    )
  }
  if (!estimate) return null

  const {
    accepted_count, eligible_vt_count,
    estimated_vt_calls_min, estimated_vt_calls_max,
    total_estimated_vt_calls_max,
    auto_rescan_estimated_quota_max,
    estimated_duration_seconds_min, estimated_duration_seconds_max,
    quota_remaining_now, will_exceed_quota,
    held_skipped_count,
  } = estimate
  const totalVtMax = total_estimated_vt_calls_max ?? estimated_vt_calls_max

  if (minimized) {
    return (
      <div className="estimate-panel estimate-panel-minimal" role="status">
        <span className="estimate-panel-label">Last estimate</span>
        <span className="estimate-minimal-summary">
          {accepted_count} items
          {held_skipped_count > 0 ? ` · ${held_skipped_count} on hold` : ''}
          {' '}· {eligible_vt_count} eligible VT · {estimated_vt_calls_min}–{estimated_vt_calls_max} VT calls · {fmtDuration(estimated_duration_seconds_min)}–{fmtDuration(estimated_duration_seconds_max)}
        </span>
        {stale && <span className="estimate-stale-tag">Outdated</span>}
        <span className="estimate-no-quota-note">No quota consumed</span>
      </div>
    )
  }

  return (
    <div className={`estimate-panel${will_exceed_quota ? ' estimate-panel-warn' : ''}${stale ? ' estimate-panel-stale' : ''}`}>
      <div className="estimate-panel-head">
        <span className="estimate-panel-label">Quota &amp; Runtime Estimate</span>
        <span className="estimate-no-quota-note">Estimate only — no VT calls, no quota consumed</span>
        {stale && <span className="estimate-stale-tag">Input changed — outdated</span>}
      </div>
      {will_exceed_quota && (
        <div className="estimate-quota-warn" role="alert">
          Worst-case ({totalVtMax} VT calls) exceeds remaining quota ({quota_remaining_now}). Submission blocked.
        </div>
      )}
      <div className="estimate-compact-grid">
        <div className="estimate-stat">
          <span className="estimate-stat-val">{accepted_count}</span>
          <span className="estimate-stat-lbl">Items</span>
        </div>
        {held_skipped_count > 0 && (
          <div className="estimate-stat">
            <span className="estimate-stat-val">{held_skipped_count}</span>
            <span className="estimate-stat-lbl">On hold / skipped</span>
          </div>
        )}
        <div className="estimate-stat">
          <span className="estimate-stat-val">{eligible_vt_count}</span>
          <span className="estimate-stat-lbl">Eligible VT</span>
        </div>
        <div className="estimate-stat">
          <span className="estimate-stat-val">{estimated_vt_calls_min}–{estimated_vt_calls_max}</span>
          <span className="estimate-stat-lbl">VT calls</span>
        </div>
        <div className="estimate-stat">
          <span className="estimate-stat-val">{fmtDuration(estimated_duration_seconds_min)}–{fmtDuration(estimated_duration_seconds_max)}</span>
          <span className="estimate-stat-lbl">Runtime</span>
        </div>
        {auto_rescan_estimated_quota_max > 0 && (
          <div className="estimate-stat">
            <span className="estimate-stat-val">+{auto_rescan_estimated_quota_max}</span>
            <span className="estimate-stat-lbl">Auto-rescan max</span>
          </div>
        )}
      </div>
      {held_skipped_count > 0 && (
        <p className="estimate-held-note">
          {held_skipped_count} domain{held_skipped_count === 1 ? '' : 's'} on hold from uploaded metadata — excluded from VT estimate and quota blocking.
        </p>
      )}
    </div>
  )
}

// ── Triage summary cards ──────────────────────────────────────────────────────

function TriageSummaryCards({ results, activeFilter, onFilterChange }) {
  const counts = getTriageCardCounts(results)
  const total = results.length

  return (
    <div className="triage-cards-row" role="group" aria-label="Result filters — click to filter">
      {TRIAGE_CARDS.map(card => {
        const count = card.key === 'all' ? total : (counts[card.key] ?? 0)
        const isActive = activeFilter === card.filter
        const isMuted = count === 0 && !isActive && card.key !== 'all'
        return (
          <button
            key={card.key}
            data-key={card.key}
            className={`triage-card${isActive ? ' active' : ''}${isMuted ? ' muted' : ''}`}
            style={{ borderLeftColor: card.color }}
            onClick={() => onFilterChange(isActive ? 'all' : card.filter)}
            aria-pressed={isActive}
            aria-current={isActive ? 'true' : undefined}
            title={`Filter by: ${card.label} (${count} item${count !== 1 ? 's' : ''})`}
          >
            <span className="tc-label">{card.label}</span>
            <span className="tc-count" style={{ color: count > 0 || card.key === 'all' ? card.color : 'var(--text-faint)' }}>{count}</span>
            <span className="tc-pct">{formatPercent(count, total)}</span>
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
        {isScan && (estimate.url_scan_eligible_count > 0 || estimate.domain_rescan_eligible_count > 0) && (
          <p className="action-modal-skips">
            {estimate.url_scan_eligible_count > 0 && `${estimate.url_scan_eligible_count} URL scan(s)`}
            {estimate.url_scan_eligible_count > 0 && estimate.domain_rescan_eligible_count > 0 && '; '}
            {estimate.domain_rescan_eligible_count > 0 && `${estimate.domain_rescan_eligible_count} domain rescan(s)`}
          </p>
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

// ── Row action buttons (drawer + row menu) ────────────────────────────────────

function RowActionButtons({
  r,
  job,
  actionInProgress,
  onExportEvidence,
  onRefreshRow,
  onScanRow,
  onAfterAction,
  className = '',
}) {
  if (!r) return null

  const canExport = !actionInProgress
  const canVt = canOpenVtRow(r)
  const canRefresh = canRefreshRow(r) && !actionInProgress && !!job
  const canScan = canScanRow(r, job) && !actionInProgress && !!job

  function runAction(handler) {
    if (!handler) return
    handler(r)
    onAfterAction?.()
  }

  return (
    <div
      className={`row-action-buttons${className ? ` ${className}` : ''}`}
      onMouseDown={e => e.stopPropagation()}
      onPointerDown={e => e.stopPropagation()}
      onClick={e => e.stopPropagation()}
    >
      <button
        type="button"
        className={canExport ? 'row-action-btn row-action-btn-active' : 'row-action-btn row-action-btn-disabled'}
        disabled={!canExport}
        aria-disabled={!canExport ? 'true' : undefined}
        title={exportEvidenceRowTitle(r, actionInProgress)}
        onClick={() => canExport && runAction(onExportEvidence)}
      >
        ↑ Export evidence (JSON)
      </button>
      <button
        type="button"
        className={canVt ? 'row-action-btn row-action-btn-active' : 'row-action-btn row-action-btn-disabled'}
        disabled={!canVt}
        aria-disabled={!canVt ? 'true' : undefined}
        title={openVtRowTitle(r)}
        onClick={() => canVt && runAction(handleOpenVtRow)}
      >
        ↗ Open in VirusTotal
      </button>
      <button
        type="button"
        className={canRefresh ? 'row-action-btn row-action-btn-active' : 'row-action-btn row-action-btn-disabled'}
        disabled={!canRefresh}
        aria-disabled={!canRefresh ? 'true' : undefined}
        title={refreshRowTitle(r, job, actionInProgress)}
        onClick={() => canRefresh && runAction(onRefreshRow)}
      >
        ↻ Refresh report
      </button>
      <button
        type="button"
        className={canScan ? 'row-action-btn row-action-btn-active' : 'row-action-btn row-action-btn-disabled'}
        disabled={!canScan}
        aria-disabled={!canScan ? 'true' : undefined}
        title={scanRowTitle(r, job, actionInProgress)}
        onClick={() => canScan && runAction(onScanRow)}
      >
        ↺ Request new scan
      </button>
    </div>
  )
}

function computeRowActionsMenuPosition(triggerEl, menuEl) {
  const rect = triggerEl.getBoundingClientRect()
  const menuWidth = 220
  const gap = 4
  const pad = 8
  const menuHeight = menuEl?.offsetHeight ?? 160
  let left = rect.right - menuWidth
  let top = rect.bottom + gap
  if (left < pad) left = pad
  if (left + menuWidth > window.innerWidth - pad) {
    left = Math.max(pad, window.innerWidth - menuWidth - pad)
  }
  if (top + menuHeight > window.innerHeight - pad) {
    top = Math.max(pad, rect.top - menuHeight - gap)
  }
  return { top, left, minWidth: menuWidth }
}

function RowActionsMenu({
  row,
  job,
  actionInProgress,
  menuId,
  open,
  onToggle,
  onClose,
  onCloseDashboard,
  onExportEvidence,
  onRefreshRow,
  onScanRow,
}) {
  const triggerRef = useRef(null)
  const menuRef = useRef(null)
  const [menuStyle, setMenuStyle] = useState(null)

  useLayoutEffect(() => {
    if (!open) {
      setMenuStyle(null)
      return undefined
    }
    const trigger = triggerRef.current
    if (!trigger) return undefined
    let frame = 0
    const updatePosition = () => {
      if (!triggerRef.current) return
      setMenuStyle(computeRowActionsMenuPosition(triggerRef.current, menuRef.current))
      if ((!menuRef.current?.offsetHeight) && frame < 2) {
        frame += 1
        requestAnimationFrame(updatePosition)
      }
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    return () => window.removeEventListener('resize', updatePosition)
  }, [open, row.position])

  const menuPanel = open ? (
    <div
      ref={menuRef}
      className="row-actions-menu row-actions-menu-portal"
      id={menuId}
      role="menu"
      aria-label={`Actions for ${row.input_normalized}`}
      style={menuStyle ?? { position: 'fixed', top: -9999, left: -9999, visibility: 'hidden', minWidth: 220 }}
      onMouseDown={e => e.stopPropagation()}
      onPointerDown={e => e.stopPropagation()}
      onClick={e => e.stopPropagation()}
    >
      <div className="row-actions-menu-label">Actions</div>
      <RowActionButtons
        r={row}
        job={job}
        actionInProgress={actionInProgress}
        onExportEvidence={onExportEvidence}
        onRefreshRow={onRefreshRow}
        onScanRow={onScanRow}
        onAfterAction={onClose}
        className="row-action-buttons-menu"
      />
    </div>
  ) : null

  return (
    <div
      className="row-actions-wrap"
      onMouseDown={e => e.stopPropagation()}
      onPointerDown={e => e.stopPropagation()}
      onClick={e => e.stopPropagation()}
    >
      <button
        ref={triggerRef}
        type="button"
        className={`icon-btn row-more-btn${open ? ' active' : ''}`}
        aria-label={`More actions for ${row.input_normalized}`}
        aria-expanded={open}
        aria-controls={menuId}
        aria-haspopup="menu"
        title={`More actions for ${row.input_normalized}`}
        onMouseDown={e => {
          onCloseDashboard?.()
          e.stopPropagation()
        }}
        onPointerDown={e => e.stopPropagation()}
        onClick={e => {
          e.stopPropagation()
          onToggle()
        }}
      >
        <IconMoreVertical />
      </button>
      {menuPanel && createPortal(menuPanel, document.body)}
    </div>
  )
}

// ── Bulk controls ─────────────────────────────────────────────────────────────

function BulkControls({
  canExportAll,
  canExportFlagged,
  canExportSelected,
  canRescanSelected,
  canRescanStale,
  staleCount,
  actionInProgress,
  onExportAll,
  onExportFlagged,
  onExportSelected,
  onRescanSelected,
  onRescanStale,
}) {
  return (
    <div className="bulk-controls">
      <span className="bulk-label">Bulk actions:</span>
      <button
        className={canExportFlagged && !actionInProgress ? 'btn btn-ghost btn-action-active' : 'btn-stub'}
        disabled={!canExportFlagged || actionInProgress}
        title={canExportFlagged ? 'Download flagged rows as CSV' : 'No flagged rows to export'}
        onClick={onExportFlagged}
      >
        <IconUpload /> Export Flagged
      </button>
      <button
        className={canExportAll && !actionInProgress ? 'btn btn-ghost btn-action-active' : 'btn-stub'}
        disabled={!canExportAll || actionInProgress}
        title={canExportAll ? 'Download all rows as CSV' : 'No results to export'}
        onClick={onExportAll}
      >
        <IconUpload /> Export All
      </button>
      <button
        className={canExportSelected && !actionInProgress ? 'btn btn-ghost btn-action-active' : 'btn-stub'}
        disabled={!canExportSelected || actionInProgress}
        title={canExportSelected ? 'Download selected rows as CSV' : 'Select rows first'}
        onClick={onExportSelected}
      >
        <IconUpload /> Export Selected
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

function ResultsTable({
  results,
  selectedIds,
  onToggleSelect,
  onToggleAll,
  selectedItem,
  onSelectItem,
  job,
  actionInProgress,
  onExportEvidence,
  onRefreshRow,
  onScanRow,
  onCloseDashboard,
}) {
  const allSelected = results.length > 0 && results.every(r => selectedIds.has(r.position))
  const [openMenuPosition, setOpenMenuPosition] = useState(null)

  useEffect(() => {
    if (openMenuPosition == null) return undefined
    function handlePointerDown(e) {
      if (e.target.closest?.('.row-actions-wrap')) return
      if (e.target.closest?.('.row-actions-menu')) return
      setOpenMenuPosition(null)
    }
    function handleKeyDown(e) {
      if (e.key === 'Escape') setOpenMenuPosition(null)
    }
    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [openMenuPosition])

  useEffect(() => {
    setOpenMenuPosition(null)
  }, [results])

  function handleRowActivate(e, r) {
    if (e.target.closest?.(
      '.ops-table-actions-cell, .row-actions-wrap, .row-actions-menu, button, input, textarea, select, a, details, summary'
    )) {
      return
    }
    onCloseDashboard?.()
    onSelectItem?.(r)
  }

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
            <th scope="col" style={{ minWidth: 88 }}>Hold Impact</th>
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
                onClick={e => handleRowActivate(e, r)}
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
                  {formatRecommendedAction(r.recommended_action)}
                </td>
                <td>
                  {(() => {
                    const hi = resolveHoldImpact(r)
                    return (
                      <span
                        className={`badge ${holdImpactBadgeClass(hi.level)}`}
                        title="Popularity-based hold-impact guidance only"
                      >
                        {formatHoldImpactLevel(hi.level)}
                      </span>
                    )
                  })()}
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
                <td className="age-cell" title={`Age bucket: ${formatAgeBucket(r.age_bucket)}`}>
                  <span className="age-cell-primary">{formatCalculatedAge(r.created_at)}</span>
                  {r.age_bucket && (
                    <span className="age-cell-secondary">{formatAgeBucket(r.age_bucket)}</span>
                  )}
                </td>
                <td>
                  {r.evidence_status ? (
                    <span className={`badge ${evidenceBadgeClass(r.evidence_status)}`}>{r.evidence_status.replace(/_/g, ' ')}</span>
                  ) : <span style={{ color: 'var(--text-faint)' }}>—</span>}
                  {hasErrors && <EvidenceErrorIndicator errors={r.errors} evidenceStatus={r.evidence_status} row={r} />}
                </td>
                <td
                  className="ops-table-actions-cell"
                  onMouseDown={e => e.stopPropagation()}
                  onPointerDown={e => e.stopPropagation()}
                  onClick={e => e.stopPropagation()}
                >
                  <div className="ops-table-actions-inner">
                    <button
                      type="button"
                      className={`icon-btn${isDetailActive ? ' active' : ''}`}
                      onMouseDown={e => e.stopPropagation()}
                      onPointerDown={e => e.stopPropagation()}
                      onClick={e => {
                        e.stopPropagation()
                        onCloseDashboard?.()
                        onSelectItem?.(isDetailActive ? null : r)
                      }}
                      title={isDetailActive ? 'Close detail panel' : 'View details in panel →'}
                      aria-label={`View details for ${r.input_normalized}`}
                    >
                      <IconEye />
                    </button>
                    <RowActionsMenu
                      row={r}
                      job={job}
                      actionInProgress={actionInProgress}
                      menuId={`row-actions-menu-${r.position}`}
                      open={openMenuPosition === r.position}
                      onToggle={() => setOpenMenuPosition(prev => (prev === r.position ? null : r.position))}
                      onClose={() => setOpenMenuPosition(null)}
                      onCloseDashboard={onCloseDashboard}
                      onExportEvidence={onExportEvidence}
                      onRefreshRow={onRefreshRow}
                      onScanRow={onScanRow}
                    />
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

function ResultsJobContextBar({
  job,
  jobError,
  restoredFromSession,
  onStartNewScan,
  actionInProgress,
}) {
  const resultCount = job?.results?.length ?? 0
  const lookupCount = job?.lookups_used ?? 0
  const isRunning = job?.status === 'queued' || job?.status === 'running' || actionInProgress
  const title = restoredFromSession ? '↩ Recovered previous job' : jobError ? 'Run error' : 'Results ready'
  const helper = restoredFromSession
    ? `${resultCount.toLocaleString()} result${resultCount !== 1 ? 's' : ''} · Completed previous UTC day · ${lookupCount.toLocaleString()} VT lookup${lookupCount !== 1 ? 's' : ''} on this job`
    : jobError
      ? 'Clear this error and return to input.'
      : `${resultCount.toLocaleString()} result${resultCount !== 1 ? 's' : ''}`

  return (
    <div className={`results-job-context-bar${restoredFromSession ? ' recovered' : ''}`} role="region" aria-label="Results job context">
      <div className="results-job-context-copy">
        <span className="results-job-context-title">{title}</span>
        <span className="results-job-context-helper">
          {isRunning ? 'Wait for this job to finish before starting another scan.' : helper}
        </span>
      </div>
      <button
        type="button"
        className="btn btn-primary results-start-new-btn"
        onClick={onStartNewScan}
        disabled={isRunning}
        aria-label="Start a new MDI scan"
        title={isRunning ? 'Wait for this job to finish before starting another scan.' : 'Clear displayed results and return to input'}
      >
        Start New Scan
      </button>
    </div>
  )
}

// ── Triage workspace (replaces JobSection) ────────────────────────────────────

function TriageWorkspace({
  job, jobError, jobId,
  selectedItem, onSelectItem,
  actionInProgress, actionMessage, exportMessage,
  onRescanSelected, onRescanStale,
  onExportAll, onExportFlagged, onExportSelected,
  onExportEvidence, onRefreshRow, onScanRow,
  onCloseDashboard,
  restoredFromSession,
  onStartNewScan,
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
      <>
        <ResultsJobContextBar
          job={job}
          jobError={jobError}
          restoredFromSession={false}
          onStartNewScan={onStartNewScan}
          actionInProgress={actionInProgress}
        />
        <div className="submit-error-banner" role="alert">
          <span style={{ color: 'var(--risk-critical)', fontSize: 12, fontWeight: 600 }}>⛔ Submit error: {jobError}</span>
        </div>
      </>
    )
  }
  if (!job && !jobId) return null

  const allResults  = job?.results ?? []
  const prioritySorted  = [...allResults].sort(comparePriority)
  const filteredResults = getFilteredResults(prioritySorted, activeFilter)
  const isComplete  = job?.status === 'done' || job?.status === 'error'
  const isRunning = job?.status === 'queued' || job?.status === 'running'

  const lcc  = job?.live_check_count ?? 0
  const lcsk = job?.live_check_skipped_count ?? 0
  const lce  = job?.live_check_error_count ?? 0
  const rdap = job?.rdap_enriched_count ?? 0
  const showCounters = lcc > 0 || lcsk > 0 || lce > 0 || rdap > 0
  const staleScannable = countStaleScannable(allResults, job)
  const selectedScannable = countSelectedScannable(allResults, selectedIds, job)
  const canRescanSelected = isComplete && !actionInProgress && selectedScannable > 0
  const canRescanStale = isComplete && !actionInProgress && staleScannable > 0
  const flaggedCount = allResults.filter(isExportFlagged).length
  const canExportAll = isComplete && !actionInProgress && allResults.length > 0
  const canExportFlagged = isComplete && !actionInProgress && flaggedCount > 0
  const canExportSelected = isComplete && !actionInProgress && selectedIds.size > 0

  return (
    <>
      {actionMessage && (
        <div className={`action-status-msg${actionInProgress ? ' running' : ''}`}>{actionMessage}</div>
      )}
      {exportMessage && (
        <div className="export-status-msg">{exportMessage}</div>
      )}

      <ResultsJobContextBar
        job={job}
        restoredFromSession={restoredFromSession}
        onStartNewScan={onStartNewScan}
        actionInProgress={actionInProgress}
      />

      {job && formatJobRanWithSummary(job) && (
        <div className="job-ran-with-summary" aria-label="Saved job options">
          <span className="job-ran-with-label">Job ran with:</span>
          <span className="job-ran-with-values">{formatJobRanWithSummary(job)}</span>
        </div>
      )}

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

      {/* Bulk controls */}
      {allResults.length > 0 && (
        <BulkControls
          canExportAll={canExportAll}
          canExportFlagged={canExportFlagged}
          canExportSelected={canExportSelected}
          canRescanSelected={canRescanSelected}
          canRescanStale={canRescanStale}
          staleCount={staleScannable}
          actionInProgress={actionInProgress}
          onExportAll={onExportAll}
          onExportFlagged={onExportFlagged}
          onExportSelected={() => onExportSelected && onExportSelected([...selectedIds])}
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
                — filtered by: {filterLabelForKey(activeFilter)}
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
          job={job}
          actionInProgress={actionInProgress}
          onExportEvidence={onExportEvidence}
          onRefreshRow={onRefreshRow}
          onScanRow={onScanRow}
          onCloseDashboard={onCloseDashboard}
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
  onExportEvidence,
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
            <span
              className="age-cell"
              title={r.created_at
                ? `Created: ${formatDate(r.created_at)} · Bucket: ${formatAgeBucket(r.age_bucket)}`
                : `Age bucket: ${formatAgeBucket(r.age_bucket)}`}
            >
              <span className="age-cell-primary">{formatCalculatedAge(r.created_at)}</span>
              {r.age_bucket && (
                <span className="age-cell-secondary">{formatAgeBucket(r.age_bucket)}</span>
              )}
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

        {/* 5b. CLOUDFLARE RADAR RANK */}
        <div className="detail-section">
          <div className="detail-section-label">Cloudflare Radar Rank</div>
          <div className="detail-kv-grid">
            <span>Popularity bucket</span>
            <span>{formatCloudflareRank(r)}</span>
            {r.cloudflare_rank_source && (
              <><span>Source</span><span>{r.cloudflare_rank_source}</span></>
            )}
            {r.cloudflare_rank_checked_at && (
              <><span>Checked</span><span>{formatDate(r.cloudflare_rank_checked_at)}</span></>
            )}
          </div>
          <p className="detail-empty-note">
            DNS popularity context only — not maliciousness evidence. Does not change triage.
          </p>
        </div>

        {/* 5c. HOLD IMPACT GUIDANCE */}
        <div className="detail-section">
          <div className="detail-section-label">Hold Impact Guidance</div>
          {(() => {
            const hi = resolveHoldImpact(r)
            return (
              <div className="detail-kv-grid">
                <span>Level</span>
                <span>
                  <span className={`badge ${holdImpactBadgeClass(hi.level)}`}>
                    {formatHoldImpactLevel(hi.level)}
                  </span>
                </span>
                <span>Guidance</span>
                <span>{hi.reason}</span>
              </div>
            )
          })()}
          <p className="detail-empty-note">
            Hold impact guidance is based on Cloudflare Radar popularity context only.
            It does not change VT verdicts and does not perform enforcement.
          </p>
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

        {/* 7. EVIDENCE */}
        {(r.evidence_status || r.errors?.length > 0) && (
          <div className="detail-section">
            <div className="detail-section-label">7. Evidence</div>
            {r.evidence_status && (
              <span className={`badge ${evidenceBadgeClass(r.evidence_status)}`}>{r.evidence_status.replace(/_/g, ' ')}</span>
            )}
            {r.freshness && (
              <span className={`badge ${freshnessBadgeClass(r.freshness)}`} style={{ marginLeft: 6 }}>{r.freshness.replace(/_/g, ' ')}</span>
            )}
            <ErrorNoticeList errors={r.errors} row={r} />
          </div>
        )}

        {/* 8. ACTIONS */}
        <div className="detail-section">
          <div className="detail-section-label">8. Actions</div>
          <RowActionButtons
            r={r}
            job={job}
            actionInProgress={actionInProgress}
            onExportEvidence={onExportEvidence}
            onRefreshRow={onRefreshRow}
            onScanRow={onScanRow}
          />
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
  const [dashboardOpen, setDashboardOpen] = useState(false)
  const dashboardPanelId = 'mdi-dashboard-panel'
  const [dashboardData, setDashboardData] = useState(null)
  const [dashboardLoading, setDashboardLoading] = useState(false)
  const [dashboardError, setDashboardError] = useState(null)
  const [dashboardWindow, setDashboardWindow] = useState('current')
  const [dashboardSourceFilter, setDashboardSourceFilter] = useState('mdi')

  // Detail drawer — client-side only, no external calls
  const [selectedItem, setSelectedItem] = useState(null)
  const inputPanelRef = useRef(null)

  // Input tabs
  const [activeInputTab, setActiveInputTab] = useState('paste')

  async function fetchDashboard(source = dashboardSourceFilter) {
    setDashboardLoading(true)
    setDashboardError(null)
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/dashboard?source=${encodeURIComponent(source)}`)
      if (!resp.ok) {
        const t = await resp.text()
        setDashboardError(`HTTP ${resp.status}: ${t}`)
        return
      }
      setDashboardData(await resp.json())
    } catch (err) {
      setDashboardError(err.message || 'Network error')
    } finally {
      setDashboardLoading(false)
    }
  }

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
  const [useDomainReports, setUseDomainReports]     = useState(DEFAULT_SETTINGS.use_domain_reports)
  const [staleThresholdDays, setStaleThresholdDays] = useState(DEFAULT_SETTINGS.stale_threshold_days)
  const [autoRescanStale, setAutoRescanStale]       = useState(DEFAULT_SETTINGS.auto_rescan_stale)
  const [maxAutoRescans, setMaxAutoRescans]         = useState(DEFAULT_SETTINGS.max_auto_rescans)
  const [cloudflareRankLookupEnabled, setCloudflareRankLookupEnabled] = useState(DEFAULT_SETTINGS.cloudflare_rank_lookup_enabled)

  // VT job state
  const [submitting, setSubmitting]                 = useState(false)
  const [jobId, setJobId]                           = useState(null)
  const [job, setJob]                               = useState(null)
  const [jobError, setJobError]                     = useState(null)
  const [restoredFromSession, setRestoredFromSession] = useState(false)
  const pollRef = useRef(null)
  const pollJobRef = useRef(null)
  const rowActionPendingRef = useRef(false)

  const [actionInProgress, setActionInProgress] = useState(false)
  const [actionMessage, setActionMessage]     = useState(null)
  const [exportMessage, setExportMessage]     = useState(null)
  const [actionModal, setActionModal]         = useState(null)
  const [actionConfirming, setActionConfirming] = useState(false)

  const canRunJob = activeInputTab === 'upload'
    ? !!(uploadPreview && uploadPreview.accepted_count > 0)
    : !!(preview && preview.accepted_count > 0)
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
    cloudflare_rank_lookup_enabled: cloudflareRankLookupEnabled,
  }

  async function handleEstimate() {
    const isUpload = activeInputTab === 'upload'
    if (isUpload) {
      if (!uploadPreview?.items?.length) return
    } else if (!rawInput.trim()) {
      return
    }
    if (isQuotaStale()) await refreshQuota()
    setEstimating(true)
    setEstimateResult(null)
    setEstimateError(null)
    setEstimateStale(false)
    try {
      const body = isUpload
        ? { items: uploadPreview.items, input_mode: 'upload', ...settingsPayload }
        : { raw_input: rawInput, input_mode: 'paste', ...settingsPayload }
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/estimate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) {
        const text = await resp.text().catch(() => 'Request failed')
        let parsed
        try { parsed = JSON.parse(text) } catch { /* plain text */ }
        const detail = parsed?.detail ?? text
        setEstimateError(formatApiErrorDetail(detail, `HTTP ${resp.status}`))
        return
      }
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

  function dismissDisplayedJob() {
    setRestoredFromSession(false)
    setJob(null)
    setJobId(null)
    setSelectedItem(null)
    resetSettingsToDefaults({
      setUseDomainReports,
      setStaleThresholdDays,
      setAutoRescanStale,
      setMaxAutoRescans,
      setCloudflareRankLookupEnabled,
    })
  }

  function focusInputPanel() {
    window.requestAnimationFrame(() => {
      const panel = inputPanelRef.current
      if (!panel) return
      panel.scrollIntoView({ block: 'start', behavior: 'smooth' })
      const target = activeInputTab === 'paste'
        ? panel.querySelector('.input-area')
        : panel.querySelector('.input-tab-btn.active')
      target?.focus?.({ preventScroll: true })
    })
  }

  function handleStartNewScan() {
    if (job?.status === 'queued' || job?.status === 'running' || actionInProgress || job?.action_in_progress) return
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    rowActionPendingRef.current = false
    dismissDisplayedJob()
    setDashboardOpen(false)
    setSettingsOpen(false)
    setActionMessage(null)
    setExportMessage(null)
    setActionModal(null)
    setActionConfirming(false)
    setActionInProgress(false)
    focusInputPanel()
  }

  function handleClear() {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (job || jobId) dismissDisplayedJob()
    setRawInput(''); setPreview(null); setPreviewError(null); setValidating(false)
    setEstimateResult(null); setEstimateError(null); setEstimateStale(false)
  }

  function handleFileChange(e) {
    const f = e.target.files?.[0] || null
    setSelectedFile(f)
    setUploadPreview(null)
    setUploadError(null)
    if (estimateResult) setEstimateStale(true)
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
      setEstimateResult(null)
      setEstimateError(null)
      setEstimateStale(false)
    } catch (err) { setUploadError(err.message || 'Network error') }
    finally { setUploadPreviewing(false) }
  }

  function handleInputTabChange(tab) {
    setActiveInputTab(tab)
    setEstimateResult(null)
    setEstimateError(null)
    setEstimateStale(false)
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
        if (rowActionPendingRef.current) {
          rowActionPendingRef.current = false
          setActionMessage('VT action completed. Results updated.')
        }
      }
    } catch (_) { /* ignore poll errors */ }
  }, [selectedItem])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    pollJobRef.current = pollJob
  }, [pollJob])

  function scheduleJobPoll(id) {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(() => pollJobRef.current?.(id), 2000)
  }

  async function fetchActionEstimate(action, scope, positions) {
    const resp = await fetch(`${API_BASE}/api/mdi/jobs/${jobId}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope, positions, estimate_only: true, confirm: false }),
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      throw new Error(formatApiErrorDetail(data?.detail, 'Action estimate failed') || `Action estimate failed: HTTP ${resp.status}`)
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
      throw new Error(formatApiErrorDetail(data?.detail, 'Action failed') || `Action failed: HTTP ${resp.status}`)
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
      rowActionPendingRef.current = true
      setActionInProgress(true)
      setActionMessage(`${actionModal.action === 'scan' ? 'Scan' : 'Refresh'} in progress…`)
      setActionModal(null)
      scheduleJobPoll(jobId)
      await pollJob(jobId)
    } catch (err) {
      rowActionPendingRef.current = false
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

  async function runExport({ format, scope, positions }) {
    if (!jobId) return
    setExportMessage(null)
    try {
      await downloadJobExport(jobId, { format, scope, positions })
      setExportMessage(
        format === 'json'
          ? 'Evidence JSON download started.'
          : `CSV export (${scope}) download started.`
      )
    } catch (err) {
      setExportMessage(`Export failed: ${err.message}`)
    }
  }

  function handleExportAll() {
    runExport({ format: 'csv', scope: 'all' })
  }

  function handleExportFlagged() {
    runExport({ format: 'csv', scope: 'flagged' })
  }

  function handleExportSelected(positions) {
    runExport({ format: 'csv', scope: 'selected', positions })
  }

  function handleExportEvidence(row) {
    runExport({ format: 'json', scope: 'selected', positions: [row.position] })
  }

  async function handleRunJob() {
    const isUpload = activeInputTab === 'upload'
    if (isUpload) {
      if (!uploadPreview?.items?.length || submitting) return
    } else if (!rawInput.trim() || submitting) {
      return
    }
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
      const body = isUpload
        ? { items: uploadPreview.items, input_mode: 'upload', ...settingsPayload }
        : { raw_input: rawInput, input_mode: 'paste', ...settingsPayload }
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/submit`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        setJobError(formatApiErrorDetail(data?.detail, `HTTP ${resp.status}`))
        return
      }
      const data = await resp.json()
      const id = data.job_id
      setJobId(id)
      scheduleJobPoll(id)
      await pollJob(id)
    } catch (err) { setJobError(err.message || 'Network error') }
    finally { setSubmitting(false) }
  }

  useEffect(() => {
    if (estimateResult) setEstimateStale(true)
  }, [useDomainReports, staleThresholdDays, autoRescanStale, maxAutoRescans, cloudflareRankLookupEnabled, uploadPreview])  // eslint-disable-line react-hooks/exhaustive-deps

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
        if (data.status === 'queued' || data.status === 'running') {
          scheduleJobPoll(data.job_id)
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

  useEffect(() => {
    if (dashboardOpen) fetchDashboard(dashboardSourceFilter)
  }, [dashboardOpen, dashboardSourceFilter])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!dashboardOpen) return undefined
    function handleEscape(e) {
      if (e.key === 'Escape') setDashboardOpen(false)
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [dashboardOpen])

  function closeDashboard() {
    setDashboardOpen(false)
  }

  function handleSelectItem(item) {
    closeDashboard()
    setSelectedItem(item)
  }

  // Close settings/dashboard panels on outside click (capture so table action stopPropagation does not block)
  useEffect(() => {
    if (!settingsOpen && !dashboardOpen) return
    function handleClick(e) {
      const settingsAnchor = document.querySelector('.nav-settings-anchor')
      const dashAnchor = document.querySelector('.nav-dashboard-anchor')
      if (settingsOpen && settingsAnchor && !settingsAnchor.contains(e.target)) setSettingsOpen(false)
      if (dashboardOpen && dashAnchor && !dashAnchor.contains(e.target)) setDashboardOpen(false)
    }
    document.addEventListener('mousedown', handleClick, true)
    return () => document.removeEventListener('mousedown', handleClick, true)
  }, [settingsOpen, dashboardOpen])

  const hasActiveResults = !!(job?.results?.length > 0)

  return (
    <div className={`console-shell${hasActiveResults ? ' has-active-results' : ''}`}>

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

        <div className="nav-dashboard-anchor">
          <button
            className="settings-gear-btn"
            onClick={() => { setDashboardOpen(v => !v); setSettingsOpen(false) }}
            aria-expanded={dashboardOpen}
            aria-controls={dashboardPanelId}
            title="Operational dashboard"
          >
            <IconBarChart /> Dashboard
          </button>
          <DashboardPanel
            open={dashboardOpen}
            id={dashboardPanelId}
            data={dashboardData}
            loading={dashboardLoading}
            error={dashboardError}
            activeWindow={dashboardWindow}
            onWindowChange={setDashboardWindow}
            sourceFilter={dashboardSourceFilter}
            onSourceFilterChange={setDashboardSourceFilter}
            onRefresh={() => fetchDashboard(dashboardSourceFilter)}
            onClose={closeDashboard}
          />
        </div>

        <div className="nav-settings-anchor">
          <button
            className="settings-gear-btn"
            onClick={() => { setSettingsOpen(v => !v); setDashboardOpen(false) }}
            aria-expanded={settingsOpen}
            aria-controls={settingsPanelId}
            title="Advanced Settings — stale threshold, auto-rescan, and reference info"
          >
            <IconGear /> Advanced
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
            cloudflareRankLookupEnabled={cloudflareRankLookupEnabled}
            setCloudflareRankLookupEnabled={setCloudflareRankLookupEnabled}
            locked={settingsLocked}
          />
        </div>
      </nav>

      {/* ── Console workspace: left + right ── */}
      <div className="console-workspace">

        {/* LEFT COLUMN */}
        <div className={`console-left${hasActiveResults ? ' has-results' : ''}`}>

          <div className="pre-results-block" ref={inputPanelRef}>
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
          <div className={`top-workspace${hasActiveResults ? ' top-workspace-compact' : ''}`}>
            <InputTabsPanel
              activeTab={activeInputTab}
              onTabChange={handleInputTabChange}
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
              estimate={estimateResult}
              estimateError={estimateError}
              estimateStale={estimateStale}
              hasActiveResults={hasActiveResults}
              restoredFromSession={restoredFromSession}
              onDismissRestore={dismissDisplayedJob}
            />

            <div className="options-sidebar">
              <VtUsagePanel quota={quotaState} quotaLoading={quotaLoading} job={job} jobId={jobId} />
              <ProcessingOptions
                useDomainReports={useDomainReports}
                setUseDomainReports={setUseDomainReports}
                locked={settingsLocked}
              />
            </div>
          </div>

          {/* Upload validation results */}
          <UploadPreviewResultsSection preview={uploadPreview} error={uploadError} />

          {/* Setup-only workflow guidance and placeholder (MDI-48) */}
          {!(job || jobError || jobId) && <SetupWorkflowGuidance />}
          </div>

          {/* Job + triage workspace */}
          {(job || jobError || jobId) && (
            <div className="results-primary-block">
            <TriageWorkspace
              job={job}
              jobError={jobError}
              jobId={jobId}
              selectedItem={selectedItem}
              onSelectItem={handleSelectItem}
              actionInProgress={actionInProgress || !!job?.action_in_progress}
              actionMessage={actionMessage}
              exportMessage={exportMessage}
              onRescanSelected={handleRescanSelected}
              onRescanStale={handleRescanStale}
              onExportAll={handleExportAll}
              onExportFlagged={handleExportFlagged}
              onExportSelected={handleExportSelected}
              onExportEvidence={handleExportEvidence}
              onRefreshRow={handleDrawerRefresh}
              onScanRow={handleDrawerScan}
              onCloseDashboard={closeDashboard}
              restoredFromSession={restoredFromSession}
              onStartNewScan={handleStartNewScan}
            />
            </div>
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

        {/* RIGHT COLUMN: detail drawer — hidden in fresh setup mode (no job/results context) */}
        {(job || jobError || jobId) && (
          <div className="console-right">
            <DetailDrawer
              selectedItem={selectedItem}
              onClose={() => setSelectedItem(null)}
              job={job}
              actionInProgress={actionInProgress || !!job?.action_in_progress}
              onRefreshRow={handleDrawerRefresh}
              onScanRow={handleDrawerScan}
              onExportEvidence={handleExportEvidence}
            />
          </div>
        )}
      </div>
    </div>
  )
}
