import { describe, expect, it } from 'vitest'
import {
  formatActionSummaryMessage,
  formatRecoveredLastActionMessage,
  getInitialJobLoadingMessage,
  getVtUsageStatusLine,
  isActionPhase,
  phaseLabel,
  shouldShowRecoveredLastAction,
} from './mdiDisplay.js'

const completedRefreshSelected = {
  action: 'refresh',
  scope: 'selected',
  status: 'completed',
  items_completed: 2,
}

describe('phaseLabel', () => {
  it('maps refresh_report default', () => {
    expect(phaseLabel('refresh_report')).toBe('Refreshing report…')
  })

  it('maps refresh_report with selected scope', () => {
    expect(phaseLabel('refresh_report', { scope: 'selected' })).toBe('Refreshing selected report(s)…')
  })

  it('maps request_new_scan with selected scope', () => {
    expect(phaseLabel('request_new_scan', { scope: 'selected' })).toBe('Rescan Selected in progress…')
  })

  it('maps request_new_scan default', () => {
    expect(phaseLabel('request_new_scan')).toBe('Request New Scan in progress…')
  })

  it('maps refresh_pending unchanged', () => {
    expect(phaseLabel('refresh_pending')).toBe('Refresh Pending in progress…')
  })

  it('maps refresh_selected_pending unchanged', () => {
    expect(phaseLabel('refresh_selected_pending')).toBe('Refresh Selected Pending in progress…')
  })

  it('maps checking_virustotal', () => {
    expect(phaseLabel('checking_virustotal')).toBe('Checking VirusTotal…')
  })

  it('returns null for null phase', () => {
    expect(phaseLabel(null)).toBeNull()
  })

  it('returns null for unknown phase', () => {
    expect(phaseLabel('unknown_phase')).toBeNull()
  })
})

describe('isActionPhase', () => {
  it.each([
    'refresh_report',
    'refresh_pending',
    'refresh_selected_pending',
    'request_new_scan',
    'rescan_stale',
  ])('returns true for %s', (phase) => {
    expect(isActionPhase(phase)).toBe(true)
  })

  it('returns false for checking_virustotal', () => {
    expect(isActionPhase('checking_virustotal')).toBe(false)
  })

  it('returns false for null', () => {
    expect(isActionPhase(null)).toBe(false)
  })

  it('returns false for unknown phase', () => {
    expect(isActionPhase('unknown')).toBe(false)
  })
})

describe('getVtUsageStatusLine', () => {
  it('shows Working… during manual refresh_report action', () => {
    expect(getVtUsageStatusLine({
      status: 'done',
      action_in_progress: true,
      current_phase: 'refresh_report',
    })).toBe('Working…')
  })

  it('shows Checking VirusTotal… during initial VT phase without action', () => {
    expect(getVtUsageStatusLine({
      status: 'running',
      action_in_progress: false,
      current_phase: 'checking_virustotal',
    })).toBe('Checking VirusTotal…')
  })

  it('shows phase copy when action_in_progress is true but phase is not an action phase', () => {
    expect(getVtUsageStatusLine({
      status: 'running',
      action_in_progress: true,
      current_phase: 'checking_virustotal',
    })).toBe('Checking VirusTotal…')
  })

  it('shows DONE for terminal done job with no active phase', () => {
    expect(getVtUsageStatusLine({
      status: 'done',
      action_in_progress: false,
      current_phase: null,
    })).toBe('DONE')
  })

  it('returns null for null job', () => {
    expect(getVtUsageStatusLine(null)).toBeNull()
  })
})

describe('shouldShowRecoveredLastAction', () => {
  const baseJob = {
    status: 'done',
    last_action_summary: completedRefreshSelected,
  }

  it('returns true for recovered terminal done job with completed summary', () => {
    expect(shouldShowRecoveredLastAction({
      job: baseJob,
      restoredFromSession: true,
      actionInProgress: false,
      actionMessage: null,
    })).toBe(true)
  })

  it('returns true for recovered terminal error job with completed summary', () => {
    expect(shouldShowRecoveredLastAction({
      job: { ...baseJob, status: 'error' },
      restoredFromSession: true,
      actionInProgress: false,
      actionMessage: null,
    })).toBe(true)
  })

  it('returns false when last_action_summary is null', () => {
    expect(shouldShowRecoveredLastAction({
      job: { status: 'done', last_action_summary: null },
      restoredFromSession: true,
      actionInProgress: false,
      actionMessage: null,
    })).toBe(false)
  })

  it('returns false when action_in_progress is true', () => {
    expect(shouldShowRecoveredLastAction({
      job: { ...baseJob, action_in_progress: true },
      restoredFromSession: true,
      actionInProgress: false,
      actionMessage: null,
    })).toBe(false)
  })

  it('returns false when current_phase is set', () => {
    expect(shouldShowRecoveredLastAction({
      job: { ...baseJob, current_phase: 'refresh_report' },
      restoredFromSession: true,
      actionInProgress: false,
      actionMessage: null,
    })).toBe(false)
  })

  it('returns false when actionMessage is set', () => {
    expect(shouldShowRecoveredLastAction({
      job: baseJob,
      restoredFromSession: true,
      actionInProgress: false,
      actionMessage: 'Refresh complete — 2 completed.',
    })).toBe(false)
  })

  it('returns false when not restored from session', () => {
    expect(shouldShowRecoveredLastAction({
      job: baseJob,
      restoredFromSession: false,
      actionInProgress: false,
      actionMessage: null,
    })).toBe(false)
  })

  it('returns false when status is running', () => {
    expect(shouldShowRecoveredLastAction({
      job: { ...baseJob, status: 'running' },
      restoredFromSession: true,
      actionInProgress: false,
      actionMessage: null,
    })).toBe(false)
  })

  it('returns false for non-completed summary', () => {
    expect(shouldShowRecoveredLastAction({
      job: {
        status: 'done',
        last_action_summary: { ...completedRefreshSelected, status: 'failed' },
      },
      restoredFromSession: true,
      actionInProgress: false,
      actionMessage: null,
    })).toBe(false)
  })
})

describe('formatRecoveredLastActionMessage', () => {
  it('prefixes completed refresh selected summary', () => {
    expect(formatRecoveredLastActionMessage(completedRefreshSelected))
      .toBe('Last action: Refresh complete — 2 completed.')
  })

  it('returns null for null summary', () => {
    expect(formatRecoveredLastActionMessage(null)).toBeNull()
  })

  it('returns null for non-completed summary', () => {
    expect(formatRecoveredLastActionMessage({ ...completedRefreshSelected, status: 'failed' })).toBeNull()
  })
})

describe('formatActionSummaryMessage', () => {
  it('formats refresh selected completed rows', () => {
    expect(formatActionSummaryMessage(completedRefreshSelected))
      .toBe('Refresh complete — 2 completed.')
  })

  it('formats scan completed rows', () => {
    expect(formatActionSummaryMessage({
      action: 'scan',
      status: 'completed',
      items_completed: 3,
    })).toBe('Scan complete — 3 completed.')
  })

  it('formats refresh pending scope', () => {
    expect(formatActionSummaryMessage({
      action: 'refresh',
      scope: 'pending',
      status: 'completed',
      items_completed: 1,
    })).toBe('Refresh Pending complete — 1 completed.')
  })

  it('formats refresh selected pending scope', () => {
    expect(formatActionSummaryMessage({
      action: 'refresh',
      scope: 'selected_pending',
      status: 'completed',
      items_completed: 1,
      items_skipped: 2,
    })).toBe('Refresh Selected Pending complete — 1 completed; 2 selected row(s) skipped.')
  })

  it('includes still pending, failed, and quota-blocked buckets', () => {
    expect(formatActionSummaryMessage({
      action: 'refresh',
      scope: 'selected',
      status: 'completed',
      items_completed: 1,
      items_still_pending: 2,
      items_failed: 1,
      items_quota_blocked: 1,
    })).toBe('Refresh complete — 1 completed; 2 still pending; 1 failed; 1 quota-blocked.')
  })

  it('returns null for null summary', () => {
    expect(formatActionSummaryMessage(null)).toBeNull()
  })

  it('returns null for non-completed summary', () => {
    expect(formatActionSummaryMessage({ action: 'refresh', status: 'failed' })).toBeNull()
  })

  it('falls back to generic action complete wording', () => {
    expect(formatActionSummaryMessage({
      action: 'unknown',
      status: 'completed',
      items_completed: 1,
    })).toBe('Action complete — 1 completed.')
  })
})

describe('getInitialJobLoadingMessage', () => {
  it('shows queued copy for queued running state', () => {
    expect(getInitialJobLoadingMessage(
      { status: 'queued' },
      { isRunning: true, hasResults: false },
    )).toBe('Queued — waiting to start…')
  })

  it('shows phase-aware copy during VT phase with no results', () => {
    expect(getInitialJobLoadingMessage(
      { status: 'running', current_phase: 'checking_virustotal' },
      { isRunning: true, hasResults: false },
    )).toBe('Checking VirusTotal…')
  })

  it('shows generic processing copy for unmapped phase with no results', () => {
    expect(getInitialJobLoadingMessage(
      { status: 'running', current_phase: null },
      { isRunning: true, hasResults: false },
    )).toBe('Processing… results will appear as they complete.')
  })

  it('returns null when results exist', () => {
    expect(getInitialJobLoadingMessage(
      { status: 'done' },
      { isRunning: false, hasResults: true },
    )).toBeNull()
  })

  it('returns null for terminal recovered job with results', () => {
    expect(getInitialJobLoadingMessage(
      { status: 'done', current_phase: null },
      { isRunning: false, hasResults: true },
    )).toBeNull()
  })
})
