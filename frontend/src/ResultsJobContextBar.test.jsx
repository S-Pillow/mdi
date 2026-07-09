import { describe, expect, it, vi, afterEach } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import ResultsJobContextBar from './ResultsJobContextBar.jsx'

afterEach(() => {
  cleanup()
})

describe('ResultsJobContextBar', () => {
  it('renders recovered last-action line for completed summary', () => {
    globalThis.fetch = vi.fn(() => {
      throw new Error('fetch must not be called in unit tests')
    })

    render(
      <ResultsJobContextBar
        job={{
          status: 'done',
          results: [{ position: 1 }, { position: 2 }],
          lookups_used: 8,
          last_action_summary: {
            action: 'refresh',
            scope: 'selected',
            status: 'completed',
            items_completed: 2,
          },
        }}
        restoredFromSession
        onStartNewScan={() => {}}
        actionInProgress={false}
        actionMessage={null}
      />,
    )

    expect(screen.getByText('↩ Recovered previous job')).toBeInTheDocument()
    expect(screen.getByText('Last action: Refresh complete — 2 completed.')).toBeInTheDocument()
  })

  it('renders recovery banner without last-action line when summary is null', () => {
    render(
      <ResultsJobContextBar
        job={{
          status: 'done',
          results: [{ position: 1 }],
          lookups_used: 1,
          last_action_summary: null,
        }}
        restoredFromSession
        onStartNewScan={() => {}}
        actionInProgress={false}
        actionMessage={null}
      />,
    )

    expect(screen.getByText('↩ Recovered previous job')).toBeInTheDocument()
    expect(screen.queryByText(/^Last action:/)).not.toBeInTheDocument()
  })

  it('does not render recovered last-action line when actionMessage is active', () => {
    render(
      <ResultsJobContextBar
        job={{
          status: 'done',
          results: [{ position: 1 }, { position: 2 }],
          lookups_used: 8,
          last_action_summary: {
            action: 'refresh',
            scope: 'selected',
            status: 'completed',
            items_completed: 2,
          },
        }}
        restoredFromSession
        onStartNewScan={() => {}}
        actionInProgress={false}
        actionMessage="Refresh complete — 2 completed."
      />,
    )

    expect(screen.getByText('↩ Recovered previous job')).toBeInTheDocument()
    expect(screen.queryByText(/^Last action:/)).not.toBeInTheDocument()
  })
})
