import React from 'react'
import {
  formatRecoveredLastActionMessage,
  shouldShowRecoveredLastAction,
} from './mdiDisplay.js'

export default function ResultsJobContextBar({
  job,
  jobError,
  restoredFromSession,
  onStartNewScan,
  actionInProgress,
  actionMessage,
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
  const recoveredLastAction = shouldShowRecoveredLastAction({
    job,
    restoredFromSession,
    actionInProgress,
    actionMessage,
  })
    ? formatRecoveredLastActionMessage(job?.last_action_summary)
    : null

  return (
    <div className={`results-job-context-bar${restoredFromSession ? ' recovered' : ''}`} role="region" aria-label="Results job context">
      <div className="results-job-context-copy">
        <span className="results-job-context-title">{title}</span>
        <span className="results-job-context-helper">
          {isRunning ? 'Wait for this job to finish before starting another scan.' : helper}
        </span>
        {recoveredLastAction && (
          <span className="results-job-context-last-action">{recoveredLastAction}</span>
        )}
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
