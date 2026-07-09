// Pure display helpers for MDI phase labels, action summaries, and status copy.
// MDI-59 / MDI-59B / MDI-65 / MDI-66 — no side effects, no network, no runtime I/O.

export const PHASE_LABELS = {
  enriching: 'Enriching domain data…',
  checking_virustotal: 'Checking VirusTotal…',
  checking_live_site: 'Checking live site status…',
  checking_cloudflare_rank: 'Checking Cloudflare rank…',
  finalizing: 'Finalizing results…',
  refresh_report: 'Refreshing report…',
  refresh_pending: 'Refresh Pending in progress…',
  refresh_selected_pending: 'Refresh Selected Pending in progress…',
  request_new_scan: 'Request New Scan in progress…',
  rescan_stale: 'Rescan Stale in progress…',
}

export function phaseLabel(phase, context = null) {
  if (!phase) return null
  if (phase === 'refresh_report' && context?.scope === 'selected') {
    return 'Refreshing selected report(s)…'
  }
  if (phase === 'request_new_scan' && context?.scope === 'selected') {
    return 'Rescan Selected in progress…'
  }
  return PHASE_LABELS[phase] || null
}

export function isActionPhase(phase) {
  return (
    phase === 'refresh_report'
    || phase === 'refresh_pending'
    || phase === 'refresh_selected_pending'
    || phase === 'request_new_scan'
    || phase === 'rescan_stale'
  )
}

export function formatActionSummaryParts(summary) {
  if (!summary) return null
  const parts = []
  if (summary.items_completed > 0) parts.push(`${summary.items_completed} completed`)
  if (summary.items_still_pending > 0) parts.push(`${summary.items_still_pending} still pending`)
  if (summary.items_failed > 0) parts.push(`${summary.items_failed} failed`)
  if (summary.items_skipped > 0 && summary.scope === 'selected_pending') {
    parts.push(`${summary.items_skipped} selected row(s) skipped`)
  }
  if (summary.items_quota_blocked > 0) parts.push(`${summary.items_quota_blocked} quota-blocked`)
  return parts
}

export function formatActionSummaryMessage(summary) {
  if (!summary || summary.status !== 'completed') return null
  const parts = formatActionSummaryParts(summary)
  const detail = parts.length ? parts.join('; ') : 'no row outcomes recorded'
  if (summary.action === 'refresh' && summary.scope === 'pending') {
    return `Refresh Pending complete — ${detail}.`
  }
  if (summary.action === 'refresh' && summary.scope === 'selected_pending') {
    return `Refresh Selected Pending complete — ${detail}.`
  }
  if (summary.action === 'refresh') {
    return `Refresh complete — ${detail}.`
  }
  if (summary.action === 'scan') {
    return `Scan complete — ${detail}.`
  }
  return `Action complete — ${detail}.`
}

export function formatRecoveredLastActionMessage(summary) {
  const message = formatActionSummaryMessage(summary)
  return message ? `Last action: ${message}` : null
}

export function shouldShowRecoveredLastAction({ job, restoredFromSession, actionInProgress, actionMessage }) {
  if (!restoredFromSession) return false
  if (actionInProgress || job?.action_in_progress) return false
  if (job?.current_phase) return false
  if (actionMessage) return false
  if (job?.status !== 'done' && job?.status !== 'error') return false
  return !!formatActionSummaryMessage(job?.last_action_summary)
}

export function getVtUsageStatusLine(job) {
  if (!job) return null
  const isRunning = job.status === 'running' || job.status === 'queued'
  const phase = job.current_phase || null
  const manualActionPhase = !!job.action_in_progress && isActionPhase(phase)
  const showActivePhase = !!phase && (isRunning || !!job.action_in_progress)
  const phaseCopy = showActivePhase && !manualActionPhase ? phaseLabel(phase) : null
  if (manualActionPhase) return 'Working…'
  return phaseCopy || (isRunning ? 'Processing…' : job.status?.toUpperCase() ?? null)
}

export function getInitialJobLoadingMessage(job, { isRunning, hasResults }) {
  if (hasResults || !isRunning) return null
  if (job?.status === 'queued') return 'Queued — waiting to start…'
  return phaseLabel(job?.current_phase) || 'Processing… results will appear as they complete.'
}
