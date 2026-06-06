import React from 'react'

// ── Icons (inline SVG — no icon library dependency for shell) ─────────────────

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

// ── Section components ────────────────────────────────────────────────────────

function InputSection() {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Input</span>
      </div>
      <div className="card-body">
        <textarea
          className="input-area"
          disabled
          placeholder="Paste domains, URLs, or IPs — one per line. (Not yet implemented.)"
        />
        <div className="input-row">
          <button className="btn btn-primary" disabled>
            <IconSearch /> Run MDI Check
          </button>
          <button className="btn btn-ghost" disabled>
            Clear
          </button>
        </div>
      </div>
    </div>
  )
}

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
      <div className="card-header">
        <span className="card-label">Triage Summary</span>
      </div>
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
        <button className="btn btn-ghost" disabled style={{ fontSize: 12, padding: '4px 10px' }}>
          Export CSV
        </button>
      </div>
      <div className="card-body">
        <div className="results-placeholder">
          <span>No results — submit domains to begin.</span>
        </div>
      </div>
    </div>
  )
}

function DetailDrawerSection() {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Detail Drawer</span>
      </div>
      <div className="card-body">
        <div className="results-placeholder">
          <span>Select a result row to view details.</span>
        </div>
      </div>
    </div>
  )
}

function SettingsSection() {
  const settings = [
    {
      name: 'Skip clientHold / serverHold domains',
      desc: 'Domains with registry hold status skip VT and live checks. On by default.',
      default: true,
    },
    {
      name: 'Auto-rescan stale results',
      desc: 'Automatically request fresh VT scans for results older than 7 days. Off by default.',
      default: false,
    },
    {
      name: 'Domain report mode',
      desc: 'Use VT domain reports instead of URL reports for bare domains.',
      default: false,
    },
    {
      name: 'Include URL activity check',
      desc: 'Perform a live HEAD request to check if the URL appears active (SSRF-safe).',
      default: true,
    },
  ]
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Settings</span>
      </div>
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
        <button className="btn btn-ghost" disabled style={{ fontSize: 12, padding: '4px 10px' }}>
          Download Usage Report
        </button>
      </div>
      <div className="card-body">
        <div className="dashboard-placeholder">
          Job history and quota usage will appear here.
        </div>
      </div>
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <div className="layout">
      <nav className="nav">
        <a href="/tools" className="nav-back">
          <IconArrowLeft /> All tools
        </a>
        <div className="nav-divider" />
        <span className="nav-title">MDI</span>
        <span className="nav-badge">shell</span>
      </nav>

      <main className="main">
        <div className="shell-notice">
          <IconInfo />
          MDI shell only — functionality not yet implemented.
        </div>

        <div className="page-header">
          <h1 className="page-title">Malicious Domain Identifier</h1>
          <p className="page-subtitle">
            Internal malicious-domain triage tool. Combines domain reputation, WHOIS, and live activity into a single check.
          </p>
        </div>

        <InputSection />
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
