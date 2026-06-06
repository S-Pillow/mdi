import React, { useState } from 'react'

// ── Icons (inline SVG — no external icon library) ────────────────────────────

function IconArrowLeft() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>
    </svg>
  )
}

function IconInfo() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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

function IconEye() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>
    </svg>
  )
}

function IconX() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
    </svg>
  )
}

// ── Constants ─────────────────────────────────────────────────────────────────

const API_BASE = ''   // same-origin; nginx proxies /api/mdi/ to port 8011

// ── Input section ─────────────────────────────────────────────────────────────

function InputSection({ rawInput, setRawInput, onPreview, previewing, onClear }) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Input</span>
      </div>
      <div className="card-body">
        <textarea
          className="input-area"
          style={{ cursor: 'text', color: 'var(--text)' }}
          value={rawInput}
          onChange={e => setRawInput(e.target.value)}
          placeholder="Paste domains, URLs, or IPs — one per line, comma-separated, or space-separated."
          spellCheck={false}
          autoComplete="off"
        />
        <div className="input-row">
          <button
            className="btn btn-primary"
            onClick={onPreview}
            disabled={previewing || !rawInput.trim()}
          >
            <IconEye /> {previewing ? 'Parsing…' : 'Parse Preview'}
          </button>
          <button
            className="btn btn-ghost"
            onClick={onClear}
            disabled={!rawInput && !previewing}
          >
            Clear
          </button>
          <button className="btn btn-ghost" disabled style={{ marginLeft: 'auto', opacity: 0.4 }}>
            <IconSearch /> Run MDI Check — not yet implemented
          </button>
        </div>
        <p style={{ marginTop: 8, fontSize: 12, color: 'var(--text-muted)' }}>
          Parse preview only — no VT, WHOIS, DNS, or live checks are run.
        </p>
      </div>
    </div>
  )
}

// ── Preview results ───────────────────────────────────────────────────────────

function PreviewResultsSection({ preview, error }) {
  const [showRejected, setShowRejected] = useState(false)
  const [showDupes, setShowDupes] = useState(false)

  if (error) {
    return (
      <div className="card">
        <div className="card-header"><span className="card-label">Parse Preview</span></div>
        <div className="card-body">
          <p style={{ color: 'var(--danger)', fontSize: 13 }}>
            Parse error: {error}
          </p>
        </div>
      </div>
    )
  }

  if (!preview) return null

  const { accepted_count, rejected_count, duplicate_count, items, rejected, duplicates } = preview

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Parse Preview</span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          No external calls — no quota consumed
        </span>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

        {/* Counts */}
        <div className="summary-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
          <div className="summary-tile">
            <span className="tile-label">Accepted</span>
            <span className="tile-value" style={{ color: accepted_count > 0 ? 'var(--ok)' : 'var(--text-muted)' }}>
              {accepted_count}
            </span>
          </div>
          <div className="summary-tile">
            <span className="tile-label">Rejected</span>
            <span className="tile-value" style={{ color: rejected_count > 0 ? 'var(--danger)' : 'var(--text-muted)' }}>
              {rejected_count}
            </span>
          </div>
          <div className="summary-tile">
            <span className="tile-label">Duplicates</span>
            <span className="tile-value" style={{ color: duplicate_count > 0 ? 'var(--warn)' : 'var(--text-muted)' }}>
              {duplicate_count}
            </span>
          </div>
        </div>

        {/* Accepted items table */}
        {items.length > 0 && (
          <div>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
              Accepted items ({items.length})
            </p>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>
                    {['#', 'Type', 'Original', 'Normalized'].map(h => (
                      <th key={h} style={{
                        textAlign: 'left', padding: '6px 10px',
                        borderBottom: '1px solid var(--border)',
                        color: 'var(--text-muted)', fontWeight: 600,
                        whiteSpace: 'nowrap',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map(item => (
                    <tr key={item.position} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '5px 10px', color: 'var(--text-dim)' }}>{item.position}</td>
                      <td style={{ padding: '5px 10px' }}>
                        <span style={{
                          fontSize: 11, fontWeight: 600, letterSpacing: '0.04em',
                          color: item.input_type === 'domain' ? 'var(--ok)' : 'var(--accent)',
                          textTransform: 'uppercase',
                        }}>{item.input_type}</span>
                      </td>
                      <td style={{ padding: '5px 10px', fontFamily: 'monospace', color: 'var(--text-muted)' }}>
                        {item.input_original}
                      </td>
                      <td style={{ padding: '5px 10px', fontFamily: 'monospace', color: 'var(--text)' }}>
                        {item.input_normalized}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Rejected items */}
        {rejected.length > 0 && (
          <div>
            <button
              className="btn btn-ghost"
              style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={() => setShowRejected(v => !v)}
            >
              {showRejected ? '▲' : '▼'} {rejected.length} rejected item{rejected.length !== 1 ? 's' : ''}
            </button>
            {showRejected && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {rejected.map((r, i) => (
                  <div key={i} style={{
                    display: 'flex', gap: 10, alignItems: 'flex-start',
                    padding: '6px 10px', background: 'var(--bg-elevated)',
                    borderRadius: 6, borderLeft: '3px solid var(--danger)',
                    fontSize: 12,
                  }}>
                    <span style={{ color: 'var(--text-dim)', minWidth: 20 }}>#{r.position}</span>
                    <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)' }}>{r.input_original}</span>
                    <span style={{ color: 'var(--danger)', marginLeft: 'auto' }}>{r.error.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Duplicates */}
        {duplicates.length > 0 && (
          <div>
            <button
              className="btn btn-ghost"
              style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={() => setShowDupes(v => !v)}
            >
              {showDupes ? '▲' : '▼'} {duplicates.length} duplicate{duplicates.length !== 1 ? 's' : ''} skipped
            </button>
            {showDupes && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {duplicates.map((d, i) => (
                  <div key={i} style={{
                    display: 'flex', gap: 10, alignItems: 'center',
                    padding: '6px 10px', background: 'var(--bg-elevated)',
                    borderRadius: 6, borderLeft: '3px solid var(--warn)',
                    fontSize: 12,
                  }}>
                    <span style={{ color: 'var(--text-dim)', minWidth: 20 }}>#{d.position}</span>
                    <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)' }}>{d.input_original}</span>
                    <span style={{ color: 'var(--warn)', marginLeft: 'auto', fontSize: 11 }}>
                      dup of {d.duplicate_of}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {accepted_count === 0 && rejected_count === 0 && duplicate_count === 0 && (
          <p style={{ fontSize: 13, color: 'var(--text-dim)', textAlign: 'center' }}>
            No items found in input.
          </p>
        )}

      </div>
    </div>
  )
}

// ── Placeholder sections (unchanged from shell) ───────────────────────────────

function TriageSummarySection() {
  const tiles = [
    { label: 'Total',      value: '—' },
    { label: 'Malicious',  value: '—' },
    { label: 'Suspicious', value: '—' },
    { label: 'Held/Skip',  value: '—' },
    { label: 'Clean',      value: '—' },
    { label: 'Error',      value: '—' },
  ]
  return (
    <div className="card">
      <div className="card-header"><span className="card-label">Triage Summary</span></div>
      <div className="card-body">
        <div className="summary-grid">
          {tiles.map(t => (
            <div key={t.label} className="summary-tile">
              <span className="tile-label">{t.label}</span>
              <span className="tile-value">{t.value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function ResultsSection() {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Results</span>
        <button className="btn btn-ghost" disabled style={{ fontSize: 12, padding: '4px 10px' }}>Export CSV</button>
      </div>
      <div className="card-body">
        <div className="results-placeholder"><span>No results — submit a job to begin.</span></div>
      </div>
    </div>
  )
}

function DetailDrawerSection() {
  return (
    <div className="card">
      <div className="card-header"><span className="card-label">Detail Drawer</span></div>
      <div className="card-body">
        <div className="results-placeholder"><span>Select a result row to view details.</span></div>
      </div>
    </div>
  )
}

function SettingsSection() {
  const settings = [
    { name: 'Skip clientHold / serverHold domains', desc: 'Domains with registry hold status skip VT and live checks. On by default.', },
    { name: 'Auto-rescan stale results', desc: 'Auto-request fresh VT scans for results older than 7 days. Off by default.', },
    { name: 'Domain report mode', desc: 'Use VT domain reports instead of URL reports for bare domains.', },
    { name: 'Include URL activity check', desc: 'Perform a live HEAD request to check if the URL appears active (SSRF-safe).', },
  ]
  return (
    <div className="card">
      <div className="card-header"><span className="card-label">Settings</span></div>
      <div className="card-body">
        <div className="settings-list">
          {settings.map(s => (
            <div key={s.name} className="setting-row">
              <div className="setting-info">
                <span className="setting-name">{s.name}</span>
                <span className="setting-desc">{s.desc}</span>
              </div>
              <div className="toggle-placeholder" title="Not yet implemented" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function DashboardSection() {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Dashboard</span>
        <button className="btn btn-ghost" disabled style={{ fontSize: 12, padding: '4px 10px' }}>Download Usage Report</button>
      </div>
      <div className="card-body">
        <div className="dashboard-placeholder">Job history and quota usage will appear here.</div>
      </div>
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [rawInput, setRawInput] = useState('')
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState(null)
  const [previewError, setPreviewError] = useState(null)

  async function handlePreview() {
    if (!rawInput.trim()) return
    setPreviewing(true)
    setPreview(null)
    setPreviewError(null)
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/parse-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_input: rawInput, default_scheme: 'http', max_items: 500 }),
      })
      if (!resp.ok) {
        const text = await resp.text()
        setPreviewError(`HTTP ${resp.status}: ${text}`)
        return
      }
      const data = await resp.json()
      setPreview(data)
    } catch (err) {
      setPreviewError(err.message || 'Network error')
    } finally {
      setPreviewing(false)
    }
  }

  function handleClear() {
    setRawInput('')
    setPreview(null)
    setPreviewError(null)
  }

  return (
    <div className="layout">
      <nav className="nav">
        <a href="/tools" className="nav-back"><IconArrowLeft /> All tools</a>
        <div className="nav-divider" />
        <span className="nav-title">MDI</span>
        <span className="nav-badge">shell</span>
      </nav>

      <main className="main">
        <div className="shell-notice">
          <IconInfo />
          MDI shell — parse preview active. VT, WHOIS, DNS, and live checks not yet implemented.
        </div>

        <div className="page-header">
          <h1 className="page-title">Malicious Domain Identifier</h1>
          <p className="page-subtitle">
            Internal malicious-domain triage tool. Combines domain reputation, WHOIS, and live activity into a single check.
          </p>
        </div>

        <InputSection
          rawInput={rawInput}
          setRawInput={setRawInput}
          onPreview={handlePreview}
          previewing={previewing}
          onClear={handleClear}
        />

        <PreviewResultsSection preview={preview} error={previewError} />

        <TriageSummarySection />
        <ResultsSection />
        <DetailDrawerSection />
        <SettingsSection />
        <DashboardSection />
      </main>

      <footer className="footer">
        © {new Date().getFullYear()} Forge Forward — MDI shell
      </footer>
    </div>
  )
}
