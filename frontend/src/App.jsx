import React, { useState, useEffect, useRef, useCallback } from 'react'

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

function IconCalculator() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="6" x2="16" y2="6"/>
      <line x1="8" y1="10" x2="16" y2="10"/><line x1="8" y1="14" x2="12" y2="14"/>
      <line x1="8" y1="18" x2="12" y2="18"/>
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

function InputSection({
  rawInput, setRawInput, onPreview, previewing, onClear,
  fileRef, selectedFile, onFileChange, onUploadPreview, uploadPreviewing,
  onRunJob, submitting, canRunJob,
  onEstimate, estimating,
}) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Input</span>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

        {/* ── Paste section ── */}
        <div>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
            Paste domains or URLs
          </p>
          <textarea
            className="input-area"
            style={{ cursor: 'text', color: 'var(--text)' }}
            value={rawInput}
            onChange={e => handleRawInputChange(e.target.value)}
            placeholder="One per line, comma-separated, or space-separated."
            spellCheck={false}
            autoComplete="off"
          />
          <div className="input-row" style={{ marginTop: 8 }}>
            <button
              className="btn btn-primary"
              onClick={onPreview}
              disabled={previewing || !rawInput.trim()}
            >
              <IconEye /> {previewing ? 'Parsing…' : 'Parse Preview'}
            </button>
            <button
              className="btn btn-primary"
              onClick={onEstimate}
              disabled={estimating || !rawInput.trim()}
              style={{ background: 'var(--bg-elevated)', color: 'var(--text)', border: '1px solid var(--border)' }}
            >
              <IconCalculator /> {estimating ? 'Estimating…' : 'Estimate Quota & Runtime'}
            </button>
            <button
              className="btn btn-ghost"
              onClick={onClear}
              disabled={!rawInput.trim() && !previewing}
            >
              Clear
            </button>
          </div>
        </div>

        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 14 }}>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
            Or upload a CSV or XLSX file (Domain / DNS Form column required)
          </p>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <label className="btn btn-ghost" style={{ cursor: 'pointer', fontSize: 12, padding: '5px 12px' }}>
              Choose file
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.xlsx,.xlsm"
                style={{ display: 'none' }}
                onChange={onFileChange}
              />
            </label>
            {selectedFile && (
              <span style={{ fontSize: 12, color: 'var(--text-muted)', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {selectedFile.name}
              </span>
            )}
            <button
              className="btn btn-primary"
              onClick={onUploadPreview}
              disabled={uploadPreviewing || !selectedFile}
              style={{ marginLeft: selectedFile ? 0 : 'auto' }}
            >
              <IconEye /> {uploadPreviewing ? 'Parsing…' : 'Upload Preview'}
            </button>
          </div>
        </div>

        <p style={{ fontSize: 12, color: 'var(--text-muted)', borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          Parse preview only — no VT calls. Use "Run MDI Check" to submit a full VT job.
        </p>

        <button
          className="btn btn-primary"
          onClick={onRunJob}
          disabled={submitting || !canRunJob}
          style={{ alignSelf: 'flex-start', fontSize: 12 }}
        >
          <IconSearch /> {submitting ? 'Submitting…' : 'Run MDI Check'}
        </button>
        {!canRunJob && !submitting && (
          <p style={{ fontSize: 11, color: 'var(--text-dim)' }}>
            Run Parse Preview first to generate accepted items.
          </p>
        )}
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

// ── Estimate section ──────────────────────────────────────────────────────────

function fmtDuration(secs) {
  if (secs < 60) return `${Math.round(secs)}s`
  const m = Math.floor(secs / 60)
  const s = Math.round(secs % 60)
  return s > 0 ? `${m}m ${s}s` : `${m}m`
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
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Estimate only — no VT calls, no job created, no quota consumed
        </span>
        {stale && (
          <span style={{ fontSize: 11, color: 'var(--warn)', fontWeight: 600 }}>
            ⚠ Input changed — estimate may be outdated
          </span>
        )}
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

        {will_exceed_quota && (
          <div style={{
            padding: '10px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
            background: 'rgba(239,68,68,0.1)', border: '1px solid var(--danger)',
            color: 'var(--danger)', display: 'flex', gap: 8, alignItems: 'center',
          }}>
            <span>⛔</span>
            <span>
              Worst-case estimate ({estimated_vt_calls_max} VT calls) exceeds remaining quota
              ({quota_remaining_now}). Submission will be blocked. Reduce input or wait until UTC midnight.
            </span>
          </div>
        )}

        {/* Parse counts */}
        <div className="summary-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
          {[
            { label: 'Accepted',   value: accepted_count,   color: accepted_count > 0 ? 'var(--ok)' : 'var(--text-muted)' },
            { label: 'Eligible VT',value: eligible_vt_count, color: eligible_vt_count > 0 ? 'var(--ok)' : 'var(--text-muted)' },
            { label: 'Rejected',   value: rejected_count,   color: rejected_count > 0 ? 'var(--danger)' : 'var(--text-muted)' },
            { label: 'Duplicates', value: duplicate_count,  color: duplicate_count > 0 ? 'var(--warn)' : 'var(--text-muted)' },
          ].map(t => (
            <div key={t.label} className="summary-tile">
              <span className="tile-label">{t.label}</span>
              <span className="tile-value" style={{ color: t.color }}>{t.value}</span>
            </div>
          ))}
        </div>

        {/* Type breakdown */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div style={{ background: 'var(--bg-elevated)', borderRadius: 6, padding: '10px 14px', fontSize: 12 }}>
            <p style={{ color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600 }}>Input type breakdown</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <Row label="Bare domains" value={domain_count} />
              <Row label="Full URLs" value={url_count} />
              <Row label="Domain-report mode" value={domain_report_mode_count} note="1 call max" />
              <Row label="URL-report mode" value={url_report_mode_count} note="up to 3 calls" />
              {held_skipped_count > 0 && <Row label="Hold-skipped" value={held_skipped_count} note="0 calls" warn />}
            </div>
          </div>

          <div style={{ background: 'var(--bg-elevated)', borderRadius: 6, padding: '10px 14px', fontSize: 12 }}>
            <p style={{ color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600 }}>VT call estimate</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <Row label="Best case (all cached)" value={`${estimated_vt_calls_min} call${estimated_vt_calls_min !== 1 ? 's' : ''}`} />
              <Row label="Worst case (none cached)" value={`${estimated_vt_calls_max} call${estimated_vt_calls_max !== 1 ? 's' : ''}`} bold />
              <Row label="Quota remaining" value={quota_remaining_now} />
              <Row
                label="Headroom (worst case)"
                value={quota_headroom >= 0 ? `+${quota_headroom}` : String(quota_headroom)}
                color={quota_headroom >= 0 ? 'var(--ok)' : 'var(--danger)'}
              />
            </div>
          </div>
        </div>

        {/* Runtime estimate */}
        <div style={{ background: 'var(--bg-elevated)', borderRadius: 6, padding: '10px 14px', fontSize: 12 }}>
          <p style={{ color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600 }}>
            Estimated runtime <span style={{ fontWeight: 400, fontSize: 11 }}>(approximate)</span>
          </p>
          <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Best case: </span>
              <span style={{ fontFamily: 'monospace', color: 'var(--ok)' }}>
                {fmtDuration(estimated_duration_seconds_min)}
              </span>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Worst case: </span>
              <span style={{ fontFamily: 'monospace', color: will_exceed_quota ? 'var(--danger)' : 'var(--text)' }}>
                {fmtDuration(estimated_duration_seconds_max)}
              </span>
            </div>
          </div>
        </div>

        {/* Notes */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <p style={{ fontSize: 11, color: 'var(--text-dim)' }}>
            <strong style={{ color: 'var(--text-muted)' }}>Rate limit:</strong> {rate_limit_note}
          </p>
          <p style={{ fontSize: 11, color: 'var(--warn)' }}>
            <strong>Job state:</strong> {job_state_note}
          </p>
          {live_check_note && (
            <p style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              <strong style={{ color: 'var(--text-muted)' }}>Live checks:</strong> {live_check_note}
            </p>
          )}
        </div>

      </div>
    </div>
  )
}

function Row({ label, value, note, bold, color, warn }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span style={{
        fontFamily: 'monospace',
        fontWeight: bold ? 700 : 400,
        color: color || (warn ? 'var(--warn)' : 'var(--text)'),
      }}>
        {value}{note && <span style={{ fontSize: 10, color: 'var(--text-dim)', marginLeft: 4 }}>{note}</span>}
      </span>
    </div>
  )
}


// ── Upload preview results ────────────────────────────────────────────────────

function HoldBadge() {
  return (
    <span style={{
      display: 'inline-block', fontSize: 10, fontWeight: 700,
      letterSpacing: '0.06em', padding: '2px 6px', borderRadius: 4,
      background: 'var(--warn)', color: '#000', textTransform: 'uppercase',
    }}>On Hold</span>
  )
}

function UploadPreviewResultsSection({ preview, error }) {
  const [showRejected, setShowRejected] = useState(false)
  const [showDupes, setShowDupes] = useState(false)
  const [showHeld, setShowHeld] = useState(true)

  if (error) {
    return (
      <div className="card">
        <div className="card-header"><span className="card-label">Upload Preview</span></div>
        <div className="card-body">
          <p style={{ color: 'var(--danger)', fontSize: 13 }}>Upload error: {error}</p>
        </div>
      </div>
    )
  }
  if (!preview) return null

  const { accepted_count, rejected_count, duplicate_count, held_count,
          items, rejected, duplicates, held_items, columns_detected,
          missing_optional_columns } = preview

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Upload Preview</span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No external calls — no quota consumed</span>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

        {/* Counts */}
        <div className="summary-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
          {[
            { label: 'Accepted', value: accepted_count, color: accepted_count > 0 ? 'var(--ok)' : 'var(--text-muted)' },
            { label: 'Held',     value: held_count,     color: held_count > 0 ? 'var(--warn)' : 'var(--text-muted)' },
            { label: 'Rejected', value: rejected_count, color: rejected_count > 0 ? 'var(--danger)' : 'var(--text-muted)' },
            { label: 'Dupes',    value: duplicate_count, color: duplicate_count > 0 ? 'var(--accent)' : 'var(--text-muted)' },
          ].map(t => (
            <div key={t.label} className="summary-tile">
              <span className="tile-label">{t.label}</span>
              <span className="tile-value" style={{ color: t.color }}>{t.value}</span>
            </div>
          ))}
        </div>

        {/* Columns detected */}
        {columns_detected && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            <span style={{ color: 'var(--text)', marginRight: 6 }}>Columns mapped:</span>
            {Object.entries(columns_detected).filter(([,v]) => v).map(([k, v]) => (
              <span key={k} style={{
                marginRight: 8, padding: '1px 6px', borderRadius: 4,
                background: 'var(--bg-elevated)', fontFamily: 'monospace',
              }}>{k} → {v}</span>
            ))}
            {missing_optional_columns?.length > 0 && (
              <span style={{ color: 'var(--text-dim)' }}>
                (missing optional: {missing_optional_columns.join(', ')})
              </span>
            )}
          </div>
        )}

        {/* Held items — shown first */}
        {held_items?.length > 0 && (
          <div>
            <button
              className="btn btn-ghost"
              style={{ fontSize: 12, padding: '4px 10px', marginBottom: 8 }}
              onClick={() => setShowHeld(v => !v)}
            >
              {showHeld ? '▲' : '▼'} {held_items.length} held domain{held_items.length !== 1 ? 's' : ''} (clientHold/serverHold)
            </button>
            {showHeld && (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr>
                      {['#', 'Domain', 'Hold Type', 'Registrar', 'Created', 'Action'].map(h => (
                        <th key={h} style={{
                          textAlign: 'left', padding: '6px 10px',
                          borderBottom: '1px solid var(--border)',
                          color: 'var(--text-muted)', fontWeight: 600, whiteSpace: 'nowrap',
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {held_items.map(item => {
                      const holdTypes = item.domain_hold?.hold_types || []
                      const holdLabel = holdTypes.filter(t => t !== 'none').join(' + ')
                      return (
                        <tr key={item.position} style={{ borderBottom: '1px solid var(--border)', background: 'rgba(250,173,20,0.04)' }}>
                          <td style={{ padding: '5px 10px', color: 'var(--text-dim)' }}>{item.position}</td>
                          <td style={{ padding: '5px 10px', fontFamily: 'monospace' }}>
                            {item.input_normalized} <HoldBadge />
                          </td>
                          <td style={{ padding: '5px 10px', color: 'var(--warn)', fontSize: 11, fontWeight: 600 }}>
                            {holdLabel || '—'}
                          </td>
                          <td style={{ padding: '5px 10px', color: 'var(--text-muted)' }}>{item.registrar || '—'}</td>
                          <td style={{ padding: '5px 10px', color: 'var(--text-muted)' }}>{item.created_at || '—'}</td>
                          <td style={{ padding: '5px 10px', fontSize: 11, color: 'var(--warn)' }}>Skip (hold)</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* All accepted items */}
        {items.length > 0 && (
          <div>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
              All accepted items ({items.length})
            </p>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>
                    {['#', 'Type', 'Normalized', 'Hold', 'Registrar', 'Created', 'Age', 'Action'].map(h => (
                      <th key={h} style={{
                        textAlign: 'left', padding: '6px 10px',
                        borderBottom: '1px solid var(--border)',
                        color: 'var(--text-muted)', fontWeight: 600, whiteSpace: 'nowrap',
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
                          fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em',
                          color: item.input_type === 'domain' ? 'var(--ok)' : 'var(--accent)',
                        }}>{item.input_type}</span>
                      </td>
                      <td style={{ padding: '5px 10px', fontFamily: 'monospace', color: 'var(--text)' }}>
                        {item.input_normalized}
                        {item.domain_hold?.has_hold && <> <HoldBadge /></>}
                      </td>
                      <td style={{ padding: '5px 10px', color: item.domain_hold?.has_hold ? 'var(--warn)' : 'var(--text-dim)', fontSize: 11 }}>
                        {item.domain_hold?.has_hold
                          ? (item.domain_hold.hold_types || []).filter(t => t !== 'none').join('+')
                          : item.domain_hold?.source === 'not_checked' ? 'unk' : 'none'}
                      </td>
                      <td style={{ padding: '5px 10px', color: 'var(--text-muted)' }}>{item.registrar || '—'}</td>
                      <td style={{ padding: '5px 10px', color: 'var(--text-muted)' }}>{item.created_at || '—'}</td>
                      <td style={{ padding: '5px 10px', color: 'var(--text-muted)', fontSize: 11 }}>{item.age_bucket}</td>
                      <td style={{ padding: '5px 10px', fontSize: 11,
                        color: item.recommended_action === 'skip' ? 'var(--warn)' : 'var(--text-dim)' }}>
                        {item.recommended_action === 'skip' ? 'Skip (hold)' : 'Pending'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Rejected rows */}
        {rejected?.length > 0 && (
          <div>
            <button className="btn btn-ghost" style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={() => setShowRejected(v => !v)}>
              {showRejected ? '▲' : '▼'} {rejected.length} rejected row{rejected.length !== 1 ? 's' : ''}
            </button>
            {showRejected && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {rejected.map((r, i) => (
                  <div key={i} style={{
                    display: 'flex', gap: 10, padding: '6px 10px',
                    background: 'var(--bg-elevated)', borderRadius: 6,
                    borderLeft: '3px solid var(--danger)', fontSize: 12,
                  }}>
                    <span style={{ color: 'var(--text-dim)', minWidth: 20 }}>#{r.position}</span>
                    <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)' }}>{r.input_original}</span>
                    <span style={{ color: 'var(--danger)', marginLeft: 'auto' }}>{r.error?.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Duplicates */}
        {duplicates?.length > 0 && (
          <div>
            <button className="btn btn-ghost" style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={() => setShowDupes(v => !v)}>
              {showDupes ? '▲' : '▼'} {duplicates.length} duplicate{duplicates.length !== 1 ? 's' : ''} skipped
            </button>
            {showDupes && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {duplicates.map((d, i) => (
                  <div key={i} style={{
                    display: 'flex', gap: 10, padding: '6px 10px',
                    background: 'var(--bg-elevated)', borderRadius: 6,
                    borderLeft: '3px solid var(--accent)', fontSize: 12,
                  }}>
                    <span style={{ color: 'var(--text-dim)', minWidth: 20 }}>#{d.position}</span>
                    <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)' }}>{d.input_original}</span>
                    <span style={{ color: 'var(--accent)', marginLeft: 'auto', fontSize: 11 }}>dup of {d.duplicate_of}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {accepted_count === 0 && rejected_count === 0 && duplicate_count === 0 && (
          <p style={{ fontSize: 13, color: 'var(--text-dim)', textAlign: 'center' }}>No rows found in file.</p>
        )}
      </div>
    </div>
  )
}


// ── Triage bucket color ───────────────────────────────────────────────────────

function triageColor(bucket) {
  const m = {
    malicious: 'var(--danger)',
    suspicious: 'var(--warn)',
    held: 'var(--accent)',
    clean: 'var(--ok)',
    error: 'var(--text-dim)',
    pending: 'var(--text-dim)',
  }
  return m[bucket] || 'var(--text)'
}

function confidenceColor(conf) {
  const m = {
    high: 'var(--ok)',
    clean: 'var(--ok)',
    medium: 'var(--warn)',
    low: 'var(--danger)',
    unknown: 'var(--text-dim)',
  }
  return m[conf] || 'var(--text-dim)'
}

function TriageReasonList({ reasons }) {
  if (!reasons || reasons.length === 0) return null
  return (
    <ul style={{ margin: '4px 0 0 0', padding: '0 0 0 16px', fontSize: 12, color: 'var(--text-dim)' }}>
      {reasons.map((r, i) => <li key={i} style={{ marginBottom: 2 }}>{r}</li>)}
    </ul>
  )
}

// ── Job section (VT job processing — early implementation) ────────────────────

function JobSection({ job, jobError, jobId, restoredFromSession, onDismissRestore }) {
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

  const pending = job ? (job.queued ?? 0) : 0
  const done    = job ? (job.processed ?? 0) : 0
  const total   = job ? (job.total ?? 0) : 0
  const pct     = total > 0 ? Math.round((done / total) * 100) : 0
  const results = job?.results ?? []

  const malCount  = results.filter(r => r.triage_bucket === 'malicious').length
  const suspCount = results.filter(r => r.triage_bucket === 'suspicious').length
  const cleanCnt  = results.filter(r => r.triage_bucket === 'clean').length
  const errCount  = results.filter(r => r.triage_bucket === 'error').length
  const heldCount = results.filter(r => r.triage_bucket === 'held').length

  const statusColor = {
    queued: 'var(--text-muted)', running: 'var(--accent)',
    done: 'var(--ok)', error: 'var(--danger)',
  }[job?.status] || 'var(--text-muted)'

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">VT Job</span>
        {restoredFromSession && (
          <span style={{
            fontSize: 11, color: 'var(--ok)', fontWeight: 600,
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            ↩ Restored from last session
            <button
              onClick={onDismissRestore}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--text-dim)', fontSize: 11, padding: '0 2px',
              }}
              title="Dismiss"
            >✕</button>
          </span>
        )}
        <span style={{ fontSize: 11, color: 'var(--warn)', fontWeight: 600 }}>
          VT job processing — early implementation
        </span>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

        {/* Status bar */}
        {job && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}>
                Job: <code style={{ fontSize: 11 }}>{jobId}</code>
              </span>
              <span style={{ color: statusColor, fontWeight: 600, textTransform: 'uppercase', fontSize: 11 }}>
                {job.status}
              </span>
            </div>
            {total > 0 && (
              <div style={{ height: 6, background: 'var(--bg-elevated)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{
                  height: '100%', borderRadius: 4,
                  width: `${pct}%`,
                  background: job.status === 'done' ? 'var(--ok)'
                    : job.status === 'error' ? 'var(--danger)' : 'var(--accent)',
                  transition: 'width 0.3s ease',
                }} />
              </div>
            )}
          </div>
        )}

        {/* Saved job settings summary */}
        {job && (job.status === 'done' || job.status === 'error') && (
          <div style={{
            fontSize: 11, color: 'var(--text-dim)', padding: '6px 10px',
            background: 'var(--bg-elevated)', borderRadius: 4, lineHeight: 1.7,
          }}>
            <strong>Job ran with:</strong>{' '}
            {job.use_domain_reports ? 'Domain report mode' : 'URL report mode'}{' '}
            · Stale after {job.stale_threshold_days ?? 7} days
            {restoredFromSession && <span style={{ marginLeft: 8, color: 'var(--ok)', fontStyle: 'italic' }}>(recovered)</span>}
          </div>
        )}

        {/* Count tiles */}
        {job && (
          <div className="summary-grid" style={{ gridTemplateColumns: 'repeat(6, 1fr)' }}>
            {[
              { label: 'Total',      value: total,     color: 'var(--text)' },
              { label: 'Malicious',  value: malCount,  color: malCount  > 0 ? 'var(--danger)' : 'var(--text-muted)' },
              { label: 'Suspicious', value: suspCount, color: suspCount > 0 ? 'var(--warn)'   : 'var(--text-muted)' },
              { label: 'Clean',      value: cleanCnt,  color: cleanCnt  > 0 ? 'var(--ok)'     : 'var(--text-muted)' },
              { label: 'Held/Skip',  value: heldCount + (job.held_skipped ?? 0), color: 'var(--accent)' },
              { label: 'Error',      value: errCount,  color: errCount  > 0 ? 'var(--danger)' : 'var(--text-muted)' },
            ].map(t => (
              <div key={t.label} className="summary-tile">
                <span className="tile-label">{t.label}</span>
                <span className="tile-value" style={{ color: t.color }}>{t.value}</span>
              </div>
            ))}
          </div>
        )}

        {/* Live-check and enrichment counter summary (MDI-12A) */}
        {job && (job.status === 'done' || job.status === 'running') && (
          (() => {
            const lcc  = job.live_check_count ?? 0
            const lcsk = job.live_check_skipped_count ?? 0
            const lce  = job.live_check_error_count ?? 0
            const rdap = job.rdap_enriched_count ?? 0
            const anyLive = lcc > 0 || lcsk > 0 || lce > 0
            const anyRdap = rdap > 0
            if (!anyLive && !anyRdap) return null
            return (
              <div style={{
                fontSize: 11, color: 'var(--text-dim)', padding: '6px 10px',
                background: 'var(--bg-elevated)', borderRadius: 4,
                display: 'flex', flexWrap: 'wrap', gap: '6px 20px',
              }}>
                {anyRdap && (
                  <span title="Domains enriched via RDAP/WHOIS before VT processing">
                    RDAP enriched: <strong style={{ color: 'var(--text-muted)' }}>{rdap}</strong>
                  </span>
                )}
                {anyLive && (
                  <>
                    <span title="Items that received a live HTTP activity check">
                      Live checks run: <strong style={{ color: lcc > 0 ? 'var(--accent)' : 'var(--text-dim)' }}>{lcc}</strong>
                    </span>
                    <span title="Items skipped by live-check eligibility (clean, held, or error)">
                      Live checks skipped: <strong style={{ color: 'var(--text-dim)' }}>{lcsk}</strong>
                    </span>
                    {lce > 0 && (
                      <span title="Items where the live check returned an error">
                        Live-check errors: <strong style={{ color: 'var(--warn)' }}>{lce}</strong>
                      </span>
                    )}
                  </>
                )}
              </div>
            )
          })()
        )}

        {/* Results table */}
        {results.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
              Results ({results.length})
            </p>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  {['#', 'Input', 'Status', 'Bucket / Reason', 'VT Hits', 'Ratio', 'Freshness', 'Action', 'Confidence', 'Evidence'].map(h => (
                    <th key={h} style={{
                      textAlign: 'left', padding: '6px 10px',
                      borderBottom: '1px solid var(--border)',
                      color: 'var(--text-muted)', fontWeight: 600, whiteSpace: 'nowrap',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '5px 10px', color: 'var(--text-dim)' }}>{r.position}</td>
                    <td style={{ padding: '5px 10px', fontFamily: 'monospace', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.input_normalized}
                    </td>
                    <td style={{ padding: '5px 10px', fontSize: 11, color: 'var(--text-muted)' }}>
                      {r.processing_status}
                    </td>
                    <td style={{ padding: '5px 10px' }}>
                      <span style={{ fontWeight: 600, color: triageColor(r.triage_bucket), fontSize: 11, textTransform: 'uppercase' }}>
                        {r.triage_bucket}
                      </span>
                      {Array.isArray(r.triage_reason) && r.triage_reason.length > 0 && (
                        <TriageReasonList reasons={r.triage_reason} />
                      )}
                    </td>
                    <td style={{ padding: '5px 10px', textAlign: 'center', color: (r.vt_hits ?? 0) > 0 ? 'var(--danger)' : 'var(--text-muted)' }}>
                      {r.vt_hits ?? '—'}
                    </td>
                    <td style={{ padding: '5px 10px', fontFamily: 'monospace', color: 'var(--text-muted)' }}>
                      {r.vt_ratio ?? '—'}
                    </td>
                    <td style={{ padding: '5px 10px', fontSize: 11, color: 'var(--text-muted)' }}>
                      {r.freshness ?? '—'}
                    </td>
                    <td style={{ padding: '5px 10px', fontSize: 11, color: 'var(--text-muted)' }}>
                      {r.recommended_action ?? '—'}
                    </td>
                    <td style={{ padding: '5px 10px', fontSize: 11, color: confidenceColor(r.triage_confidence) }}>
                      {r.triage_confidence ?? '—'}
                    </td>
                    <td style={{ padding: '5px 10px', fontSize: 11, color: 'var(--text-muted)' }}>
                      {r.evidence_status ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {job && results.length === 0 && job.status === 'running' && (
          <p style={{ fontSize: 13, color: 'var(--text-dim)', textAlign: 'center' }}>
            Processing… results will appear as they complete.
          </p>
        )}
        {job && results.length === 0 && job.status === 'queued' && (
          <p style={{ fontSize: 13, color: 'var(--text-dim)', textAlign: 'center' }}>Queued…</p>
        )}
      </div>
    </div>
  )
}

function SettingsSection({ useDomainReports, setUseDomainReports, staleThresholdDays, setStaleThresholdDays, locked }) {
  const lockedStyle = locked ? { opacity: 0.55, pointerEvents: 'none' } : {}
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-label">Settings</span>
        {locked && (
          <span style={{ fontSize: 11, color: 'var(--text-dim)', fontStyle: 'italic' }}>
            Locked — start a new job to change settings
          </span>
        )}
      </div>
      <div className="card-body">

        {/* ── Group 1: Functional settings ──────────────────────────────── */}
        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
            VT Processing Options
          </div>
          <div className="settings-list" style={lockedStyle}>

            {/* VT Report Mode */}
            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-name">VT Report Mode</span>
                <span className="setting-desc">
                  {useDomainReports
                    ? 'Domain report mode — 1 VT call per bare domain. Less detail than URL mode.'
                    : 'URL report mode (recommended) — up to 3 VT calls per bare domain. Better coverage.'}
                </span>
              </div>
              <button
                className={`btn ${useDomainReports ? 'btn-secondary' : 'btn-primary'}`}
                style={{ fontSize: 11, padding: '4px 12px', minWidth: 130, whiteSpace: 'nowrap' }}
                onClick={() => setUseDomainReports(v => !v)}
                disabled={locked}
                title={locked ? 'Settings locked while a job is active' : undefined}
              >
                {useDomainReports ? '⚙ Domain report' : '⚙ URL report'}
              </button>
            </div>

            {/* Stale threshold */}
            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-name">Stale Threshold</span>
                <span className="setting-desc">
                  VT reports older than this many days are classified as <strong>STALE</strong> (lower confidence). Default: 7 days.
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="number"
                  min={1}
                  max={90}
                  value={staleThresholdDays}
                  onChange={e => {
                    const v = parseInt(e.target.value, 10)
                    if (!isNaN(v) && v >= 1 && v <= 90) setStaleThresholdDays(v)
                  }}
                  disabled={locked}
                  style={{
                    width: 60, padding: '4px 6px', borderRadius: 4, border: '1px solid var(--border)',
                    background: 'var(--surface)', color: 'var(--text)', fontSize: 13,
                    opacity: locked ? 0.55 : 1,
                  }}
                  title={locked ? 'Settings locked while a job is active' : 'Stale threshold in days (1–90)'}
                />
                <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>days</span>
              </div>
            </div>

          </div>
        </div>

        {/* ── Group 2: Disabled placeholders (not yet implemented) ───────── */}
        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
            Advanced Options <span style={{ fontSize: 10, fontWeight: 400, textTransform: 'none' }}>(not yet implemented)</span>
          </div>
          <div className="settings-list">

            <div className="setting-row" style={{ opacity: 0.5 }}>
              <div className="setting-info">
                <span className="setting-name">Auto-Rescan Stale Results</span>
                <span className="setting-desc">
                  Automatically request fresh VT scans for stale items. <strong>Not yet implemented.</strong>{' '}
                  When enabled, will consume additional VT quota per stale item.
                </span>
              </div>
              <div className="toggle-placeholder" title="Not yet implemented — auto-rescan coming in a future release" />
            </div>

            <div className="setting-row" style={{ opacity: 0.5 }}>
              <div className="setting-info">
                <span className="setting-name">URL Activity Check</span>
                <span className="setting-desc">
                  Live HEAD-request probe for each item (SSRF-safe). <strong>Coming in a future release.</strong>
                </span>
              </div>
              <div className="toggle-placeholder" title="Not yet implemented — URL activity check coming in a future release" />
            </div>

            <div className="setting-row" style={{ opacity: 0.5 }}>
              <div className="setting-info">
                <span className="setting-name">Export Results</span>
                <span className="setting-desc">
                  Download results as CSV or JSON. <strong>Coming soon.</strong>
                </span>
              </div>
              <div className="toggle-placeholder" title="Not yet implemented — export coming in a future release" />
            </div>

          </div>
        </div>

        {/* ── Group 3: Info rows (read-only) ────────────────────────────── */}
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
            Current Behavior (read-only)
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.8 }}>
            <div><strong>VT hit definition:</strong> MALICIOUS ≥ 1 engine → Malicious · SUSPICIOUS ≥ 1 engine → Suspicious. Configurable threshold coming soon.</div>
            <div><strong>Max items per job:</strong> 500</div>
            <div><strong>Default scheme:</strong> HTTP (bare tokens treated as domains)</div>
            <div><strong>Hold detection:</strong> clientHold / serverHold domains skip VT — enabled by default</div>
          </div>
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

// ── Quota widget ──────────────────────────────────────────────────────────────

function QuotaWidget({ quota, loading, error }) {
  if (loading) {
    return (
      <div style={{
        fontSize: 11, color: 'var(--text-dim)', padding: '4px 0',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{ opacity: 0.6 }}>⏳ Checking VT quota…</span>
      </div>
    )
  }
  if (error) {
    return (
      <div style={{
        fontSize: 11, color: 'var(--warn)', padding: '4px 0',
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        ⚠ Quota check failed: {error}
      </div>
    )
  }
  if (!quota) return null

  const pct = quota.remaining != null && quota.daily_limit != null
    ? Math.round(((quota.daily_limit - quota.remaining) / quota.daily_limit) * 100)
    : null
  const barColor = quota.remaining <= 0 ? 'var(--danger)'
    : quota.remaining < 50 ? 'var(--warn)' : 'var(--ok)'
  const checkedStr = quota.checkedAt
    ? new Date(quota.checkedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 14,
      fontSize: 11, color: 'var(--text-muted)',
      padding: '5px 0', flexWrap: 'wrap',
    }}>
      <span title="Shared VT quota — used by MDI and VT Bulk Check">
        <span style={{ color: 'var(--text-dim)' }}>VT quota: </span>
        <span style={{ fontFamily: 'monospace', color: quota.remaining <= 0 ? 'var(--danger)' : 'var(--text)' }}>
          {quota.daily_lookups_used ?? '?'} / {quota.daily_limit ?? '500'}
        </span>
        {' '}
        <span style={{ color: barColor, fontWeight: 600 }}>
          ({quota.remaining ?? '?'} remaining)
        </span>
      </span>
      {pct != null && (
        <span style={{
          display: 'inline-block', width: 60, height: 6,
          background: 'var(--bg-elevated)', borderRadius: 3, overflow: 'hidden',
          verticalAlign: 'middle',
        }}>
          <span style={{
            display: 'block', height: '100%',
            width: `${Math.min(pct, 100)}%`,
            background: barColor, borderRadius: 3,
          }} />
        </span>
      )}
      {checkedStr && (
        <span style={{ color: 'var(--text-dim)' }}>
          Last checked: {checkedStr}
        </span>
      )}
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

// How old a quota reading can be before estimate/submit forces a refresh (ms).
const QUOTA_STALE_MS = 60_000

export default function App() {
  // Shared VT quota state (MDI-12A — refreshed on load, before submit, after completion)
  const [quotaState, setQuotaState] = useState(null)    // { daily_lookups_used, remaining, daily_limit, checkedAt }
  const [quotaLoading, setQuotaLoading] = useState(false)
  const [quotaError, setQuotaError] = useState(null)

  async function refreshQuota() {
    setQuotaLoading(true)
    setQuotaError(null)
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/usage`)
      if (!resp.ok) {
        setQuotaError(`HTTP ${resp.status}`)
        return null
      }
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

  // Paste preview state
  const [rawInput, setRawInput] = useState('')
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState(null)
  const [previewError, setPreviewError] = useState(null)

  // Estimate state
  const [estimating, setEstimating] = useState(false)
  const [estimateResult, setEstimateResult] = useState(null)
  const [estimateError, setEstimateError] = useState(null)
  const [estimateStale, setEstimateStale] = useState(false)

  // Upload preview state
  const fileRef = useRef(null)
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploadPreviewing, setUploadPreviewing] = useState(false)
  const [uploadPreview, setUploadPreview] = useState(null)
  const [uploadError, setUploadError] = useState(null)

  // Settings state
  const [useDomainReports, setUseDomainReports] = useState(false)
  const [staleThresholdDays, setStaleThresholdDays] = useState(7)

  // VT job state
  const [submitting, setSubmitting] = useState(false)
  const [jobId, setJobId] = useState(null)
  const [job, setJob] = useState(null)
  const [jobError, setJobError] = useState(null)
  const [restoredFromSession, setRestoredFromSession] = useState(false)
  const pollRef = useRef(null)

  const canRunJob = !!(preview && preview.accepted_count > 0)

  // Settings are locked while a job is running/queued or a recovered job is shown
  const settingsLocked = !!(
    restoredFromSession ||
    (job && (job.status === 'queued' || job.status === 'running'))
  )

  // Shared settings payload — single source of truth for both estimate and submit
  const settingsPayload = {
    default_scheme: 'http',
    max_items: 500,
    use_domain_reports: useDomainReports,
    stale_threshold_days: staleThresholdDays,
  }

  async function handleEstimate() {
    if (!rawInput.trim()) return
    // Refresh shared quota first if stale — for operator visibility before the estimate renders
    if (isQuotaStale()) await refreshQuota()
    setEstimating(true)
    setEstimateResult(null)
    setEstimateError(null)
    setEstimateStale(false)
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/estimate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_input: rawInput, ...settingsPayload }),
      })
      if (!resp.ok) {
        const text = await resp.text()
        setEstimateError(`HTTP ${resp.status}: ${text}`)
        return
      }
      setEstimateResult(await resp.json())
    } catch (err) {
      setEstimateError(err.message || 'Network error')
    } finally {
      setEstimating(false)
    }
  }

  function handleRawInputChange(val) {
    setRawInput(val)
    // Mark existing estimate as stale when input changes
    if (estimateResult) setEstimateStale(true)
  }

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
      setPreview(await resp.json())
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
    setEstimateResult(null)
    setEstimateError(null)
    setEstimateStale(false)
  }

  function handleFileChange(e) {
    const f = e.target.files?.[0] || null
    setSelectedFile(f)
    setUploadPreview(null)
    setUploadError(null)
  }

  async function handleUploadPreview() {
    if (!selectedFile) return
    setUploadPreviewing(true)
    setUploadPreview(null)
    setUploadError(null)
    try {
      const form = new FormData()
      form.append('file', selectedFile)
      form.append('default_scheme', 'http')
      form.append('max_items', '500')
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/upload-preview`, {
        method: 'POST',
        body: form,
      })
      if (!resp.ok) {
        const text = await resp.text()
        setUploadError(`HTTP ${resp.status}: ${text}`)
        return
      }
      setUploadPreview(await resp.json())
    } catch (err) {
      setUploadError(err.message || 'Network error')
    } finally {
      setUploadPreviewing(false)
    }
  }

  // Poll job status until done/error; refresh shared quota on completion
  const pollJob = useCallback(async (id) => {
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/${id}`)
      if (!resp.ok) return
      const data = await resp.json()
      setJob(data)
      if (data.status === 'done' || data.status === 'error') {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
        // Refresh quota to reflect consumption by the completed job
        refreshQuota()
      }
    } catch (_) { /* ignore poll errors */ }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  async function handleRunJob() {
    if (!rawInput.trim() || submitting) return

    // Always refresh shared quota immediately before submit so the UI shows current usage
    // and we can block if quota is exhausted.
    const freshQuota = await refreshQuota()
    if (freshQuota && freshQuota.remaining <= 0) {
      setJobError(
        `VT quota exhausted — ${freshQuota.daily_lookups_used ?? '?'} / ` +
        `${freshQuota.daily_limit ?? 500} used today. Wait until UTC midnight to reset.`
      )
      return
    }

    setSubmitting(true)
    setJob(null)
    setJobId(null)
    setJobError(null)
    setRestoredFromSession(false)
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    try {
      const resp = await fetch(`${API_BASE}/api/mdi/jobs/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_input: rawInput, ...settingsPayload }),
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        const msg = data?.detail?.message || data?.detail || `HTTP ${resp.status}`
        setJobError(msg)
        return
      }
      const data = await resp.json()
      const id = data.job_id
      setJobId(id)
      // Start polling every 2s
      pollRef.current = setInterval(() => pollJob(id), 2000)
      // Immediate first poll
      await pollJob(id)
    } catch (err) {
      setJobError(err.message || 'Network error')
    } finally {
      setSubmitting(false)
    }
  }

  // Mark estimate stale when settings change (same as when input changes)
  useEffect(() => {
    if (estimateResult) setEstimateStale(true)
  }, [useDomainReports, staleThresholdDays])  // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch shared VT quota on app load (MDI-12A)
  useEffect(() => {
    refreshQuota()
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Recovery: on mount, attempt to restore the latest completed job
  useEffect(() => {
    let cancelled = false
    async function tryRecover() {
      try {
        const resp = await fetch(`${API_BASE}/api/mdi/jobs/latest`)
        if (cancelled) return
        if (resp.status === 404) return  // no prior job — silent
        if (!resp.ok) return             // unexpected error — non-blocking
        const data = await resp.json()
        if (cancelled) return
        setJob(data)
        setJobId(data.job_id)
        setRestoredFromSession(true)
        // If the recovered job is still running, resume polling
        if (data.status === 'queued' || data.status === 'running') {
          pollRef.current = setInterval(() => pollJob(data.job_id), 2000)
        }
      } catch (_) {
        // Network error on mount — do not block the UI
      }
    }
    tryRecover()
    return () => { cancelled = true }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Cleanup on unmount
  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current)
  }, [])

  return (
    <div className="layout">
      <nav className="nav">
        <a href="/tools" className="nav-back"><IconArrowLeft /> All tools</a>
        <div className="nav-divider" />
        <span className="nav-title">MDI</span>
        <span className="nav-badge">beta</span>
      </nav>

      <main className="main">
        <div className="shell-notice">
          <IconInfo />
          MDI — VT core + RDAP/WHOIS enrichment + live checks (MDI-12) active.
        </div>

        {/* Shared VT quota display (MDI-12A) */}
        <QuotaWidget quota={quotaState} loading={quotaLoading} error={quotaError} />

        <div className="page-header">
          <h1 className="page-title">Malicious Domain Identifier</h1>
          <p className="page-subtitle">
            Internal malicious-domain triage tool. Combines domain reputation, WHOIS, and live activity into a single check.
          </p>
        </div>

        <InputSection
          rawInput={rawInput}
          setRawInput={handleRawInputChange}
          onPreview={handlePreview}
          previewing={previewing}
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
        <PreviewResultsSection preview={preview} error={previewError} />
        <UploadPreviewResultsSection preview={uploadPreview} error={uploadError} />

        <JobSection
          job={job}
          jobError={jobError}
          jobId={jobId}
          restoredFromSession={restoredFromSession}
          onDismissRestore={() => { setRestoredFromSession(false); setJob(null); setJobId(null) }}
        />

        <SettingsSection
          useDomainReports={useDomainReports}
          setUseDomainReports={setUseDomainReports}
          staleThresholdDays={staleThresholdDays}
          setStaleThresholdDays={setStaleThresholdDays}
          locked={settingsLocked}
        />
        <DashboardSection />
      </main>

      <footer className="footer">
        © {new Date().getFullYear()} Forge Forward — MDI
      </footer>
    </div>
  )
}
