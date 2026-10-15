import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchNatureMeta, fetchNatureStats, fetchSectorGaps, searchLibrary, searchMap } from './api'
import Logo from './Logo'
import './Nature.css'

const TABS = [
  { id: 'library', label: 'Library' },
  { id: 'map', label: 'Industry map' },
]

const STATUS_LABEL = {
  ai_extracted: 'AI-extracted, not yet expert-checked',
  expert_validated: 'Expert-validated',
  disputed: 'Disputed',
}
const KIND_LABEL = { mechanism: 'Mechanism', material: 'Material', process: 'Process', practice: 'Practice' }
const MAP_TYPE_LABEL = { paper: 'Paper', patent: 'Patent', grant: 'Grant', project: 'Project', company: 'Company' }
// "Inspired by nature" and "better for nature" are different claims; these labels only describe the link type.
const NATURE_LINK_LABEL = {
  biomimetic: 'Inspired by nature',
  bio_based: 'Bio-based',
  nature_based_solution: 'Nature-based solution',
  circular: 'Circular',
  other: 'Other',
}
const GRADE_LABEL = { strong: 'Strong evidence', moderate: 'Moderate evidence', weak: 'Weak evidence', contested: 'Contested' }

const LIBRARY_LIMIT = 100 // the API maximum; v0 serves fewer records than this

function labelMap(list, key = 'label') {
  const out = {}
  for (const item of list || []) out[item.id] = item[key] || item.label_en || item.id
  return out
}

function ExternalLink({ href, children }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  )
}

function safeUrl(u) {
  return typeof u === 'string' && /^https?:\/\//i.test(u) ? u : null
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

// Counts from 0 up to `target` after `delay` ms, easing out; jumps straight there when motion is reduced.
function useCountUp(target, { duration = 1400, delay = 0 } = {}) {
  const [value, setValue] = useState(0)
  useEffect(() => {
    if (!target) return undefined
    if (prefersReducedMotion()) {
      setValue(target)
      return undefined
    }
    let raf = 0
    let start = 0
    const tick = (now) => {
      if (!start) start = now
      const t = Math.min(1, (now - start) / duration)
      setValue(Math.round(target * (1 - Math.pow(2, -10 * t))))
      if (t < 1) raf = requestAnimationFrame(tick)
      else setValue(target)
    }
    const timer = setTimeout(() => {
      raf = requestAnimationFrame(tick)
    }, delay)
    return () => {
      clearTimeout(timer)
      cancelAnimationFrame(raf)
    }
  }, [target, duration, delay])
  return value
}

function CountBubble({ value, label, delay, tone }) {
  const shown = useCountUp(value, { delay: delay + 250 })
  return (
    <div className={`nat-count nat-count--${tone}`} style={{ animationDelay: `${delay}ms` }} aria-label={`${value} ${label}`}>
      <span className="nat-count__num" aria-hidden="true">
        {shown}
      </span>
      <span className="nat-count__label" aria-hidden="true">
        {label}
      </span>
    </div>
  )
}

function GradePill({ grade }) {
  if (!grade) return null
  return <span className={`nat-pill nat-pill--${grade}`}>{GRADE_LABEL[grade] || grade}</span>
}

function StatusBadge({ status }) {
  return <span className={`nat-badge nat-badge--${status}`}>{STATUS_LABEL[status] || status}</span>
}

function Loading({ children = 'Loading…' }) {
  return (
    <p className="nat-state" role="status">
      <span className="nat-spinner" aria-hidden="true" />
      {children}
    </p>
  )
}

function ErrorBox({ error }) {
  if (!error) return null
  return (
    <p className="nat-state nat-state--error" role="alert">
      {error}
    </p>
  )
}

function Select({ id, label, value, onChange, options, anyLabel = 'Any' }) {
  return (
    <div className="nat-field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{anyLabel}</option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </div>
  )
}

function EvidenceLinks({ evidence }) {
  const items = (evidence || []).filter((e) => e.doi || safeUrl(e.url))
  if (!items.length) return null
  return (
    <ul className="nat-links">
      {items.map((e, i) => (
        <li key={i}>
          {e.doi ? (
            <ExternalLink href={`https://doi.org/${e.doi}`}>DOI {e.doi}</ExternalLink>
          ) : (
            <ExternalLink href={safeUrl(e.url)}>{e.citation || e.url}</ExternalLink>
          )}
          {e.year ? <span className="nat-muted"> ({e.year})</span> : null}
        </li>
      ))}
    </ul>
  )
}

function RecordCard({ record, grade, labels }) {
  const organism = record.organism
  return (
    <article className={`nat-card nat-card--${record.kind || 'other'}`}>
      <header className="nat-card__head">
        <div className="nat-row">
          <span className="nat-tag nat-tag--kind">{KIND_LABEL[record.kind] || record.kind}</span>
          <GradePill grade={grade} />
        </div>
        <h4>{record.title}</h4>
        {organism?.scientific_name && (
          <p className="nat-organism">
            <em>{organism.scientific_name}</em>
            {organism.common_names?.length ? ` · ${organism.common_names.join(', ')}` : ''}
          </p>
        )}
      </header>
      <p>{record.summary}</p>
      <div className="nat-row">
        {(record.functions || []).map((f) => (
          <span key={f} className="nat-tag nat-tag--fn">
            {labels.functions[f] || f}
          </span>
        ))}
      </div>
      <p className="nat-caveat">
        <strong>Caveat: </strong>
        {record.caveat}
      </p>
      {record.popular_claim_note && <p className="nat-caveat">{record.popular_claim_note}</p>}
      <footer className="nat-card__foot">
        <StatusBadge status={record.provenance?.status} />
        <EvidenceLinks evidence={record.evidence} />
        {(record.see_also || []).filter(safeUrl).length > 0 && (
          <ul className="nat-links">
            {record.see_also.filter(safeUrl).map((u) => (
              <li key={u}>
                <ExternalLink href={u}>Further reading</ExternalLink>
              </li>
            ))}
          </ul>
        )}
      </footer>
    </article>
  )
}

function MapCard({ record, labels }) {
  const ids = record.identifiers || {}
  const href = ids.doi ? `https://doi.org/${ids.doi}` : safeUrl(ids.url)
  return (
    <article className="nat-card nat-card--map">
      <header className="nat-card__head">
        <div className="nat-row">
          <span className="nat-tag nat-tag--kind">{MAP_TYPE_LABEL[record.type] || record.type}</span>
          <span className="nat-tag">{NATURE_LINK_LABEL[record.nature_link] || record.nature_link}</span>
        </div>
        <h4>{href ? <ExternalLink href={href}>{record.title}</ExternalLink> : record.title}</h4>
      </header>
      {record.summary && <p>{record.summary}</p>}
      <p className="nat-muted">
        {[labels.sectors[record.sector] || record.sector, record.country, record.year, record.trl ? `TRL ${record.trl}` : null]
          .filter(Boolean)
          .join(' · ')}
        {record.organisations?.length ? ` · ${record.organisations.map((o) => o.name).join(', ')}` : ''}
      </p>
      <div className="nat-row">
        {(record.problem_functions || []).map((f) => (
          <span key={f} className="nat-tag nat-tag--fn">
            {labels.functions[f] || f}
          </span>
        ))}
      </div>
      <footer className="nat-card__foot">
        <StatusBadge status={record.provenance?.status} />
      </footer>
    </article>
  )
}

function SectorGaps({ data, labels }) {
  if (!data) return null
  return (
    <section className="nat-panel nat-gaps-panel" aria-label="Sector gaps">
      <h3>Library mechanisms this sector has not used yet</h3>
      <p className="nat-note">
        Based on classified papers only: {data.classified_papers} classified, {data.unclassified_papers} unclassified
        and not counted.
      </p>
      {data.gaps?.length ? (
        <ul className="nat-gaps">
          {data.gaps.map((g) => (
            <li key={g.record_id}>
              <strong>{g.title}</strong> <GradePill grade={g.evidence_grade} />
              <div className="nat-row">
                {g.functions_overlap.map((f) => (
                  <span key={f} className="nat-tag nat-tag--fn">
                    {labels.functions[f] || f}
                  </span>
                ))}
                <span className="nat-muted">demand weight {g.weight}</span>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="nat-muted">No gaps found from the classified papers.</p>
      )}
    </section>
  )
}

/* ── Library tab ─────────────────────────────────────────────────────────── */

function LibraryTab({ meta, labels }) {
  const [f, setF] = useState({ q: '', area: '', sector: '', kind: '', status: '' })
  const [phase, setPhase] = useState('loading')
  const [error, setError] = useState('')
  const [hits, setHits] = useState([])
  const tx = meta.taxonomy

  useEffect(() => {
    let live = true
    setPhase('loading')
    setError('')
    const timer = setTimeout(() => {
      searchLibrary({ ...f, q: f.q.trim(), limit: LIBRARY_LIMIT })
        .then((r) => live && (setHits(r), setPhase('done')))
        .catch((e) => live && (setError(e.message), setPhase('error')))
    }, 250)
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [f])

  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }))

  return (
    <div>
      <div className="nat-panel nat-filters">
        <div className="nat-field nat-field--search">
          <label htmlFor="nat-lib-q">Search</label>
          <input
            id="nat-lib-q"
            type="search"
            placeholder="Try “drag”, “cooling” or “adhesion”"
            value={f.q}
            onChange={(e) => set('q')(e.target.value)}
          />
        </div>
        <Select id="nat-lib-area" label="Area" value={f.area} onChange={set('area')} options={(tx.areas || []).map((a) => [a.id, a.label])} />
        <Select id="nat-lib-sector" label="Sector" value={f.sector} onChange={set('sector')} options={(tx.sectors || []).map((s) => [s.id, s.label_en])} />
        <Select id="nat-lib-kind" label="Kind" value={f.kind} onChange={set('kind')} options={Object.entries(KIND_LABEL)} />
        <Select id="nat-lib-status" label="Review status" value={f.status} onChange={set('status')} options={Object.entries(STATUS_LABEL)} />
      </div>
      {phase === 'loading' && <Loading>{hits.length ? 'Updating results…' : 'Loading records…'}</Loading>}
      {phase === 'error' && <ErrorBox error={error} />}
      {phase === 'done' && hits.length === 0 && <p className="nat-state">No records match these filters.</p>}
      {phase === 'done' && hits.length > 0 && (
        <p className="nat-count-line">
          {hits.length} record{hits.length === 1 ? '' : 's'}
        </p>
      )}
      {phase !== 'error' && hits.length > 0 && (
        <div className="nat-grid" aria-busy={phase === 'loading'} style={phase === 'loading' ? { opacity: 0.6 } : undefined}>
          {hits.map((h) => (
            <RecordCard key={h.record.id} record={h.record} grade={h.evidence_grade} labels={labels} />
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Industry map tab ────────────────────────────────────────────────────── */

function MapTab({ meta, labels }) {
  const sectors = meta.taxonomy.sectors || []
  const [sector, setSector] = useState(sectors[0]?.id || '')
  const [type, setType] = useState('')
  const [phase, setPhase] = useState('loading')
  const [error, setError] = useState('')
  const [hits, setHits] = useState([])
  const [gaps, setGaps] = useState(null)

  useEffect(() => {
    if (!sector) {
      setHits([])
      setGaps(null)
      setError('')
      setPhase('idle')
      return undefined
    }
    let live = true
    setPhase('loading')
    setError('')
    Promise.all([searchMap({ sector, type, limit: 30 }), fetchSectorGaps(sector)])
      .then(([m, g]) => {
        if (!live) return
        setHits(m)
        setGaps(g)
        setPhase('done')
      })
      .catch((e) => {
        if (!live) return
        setError(e.message)
        setPhase('error')
      })
    return () => {
      live = false
    }
  }, [sector, type])

  return (
    <div>
      <div className="nat-panel nat-filters">
        <Select id="nat-map-sector" label="Sector" value={sector} onChange={setSector} anyLabel="Choose a sector" options={sectors.map((s) => [s.id, s.label_en])} />
        <Select id="nat-map-type" label="Record type" value={type} onChange={setType} options={Object.entries(MAP_TYPE_LABEL)} />
      </div>
      {phase === 'loading' && <Loading>Loading sector…</Loading>}
      {phase === 'error' && <ErrorBox error={error} />}
      {phase === 'done' && (
        <>
          <p className="nat-count-line">
            {hits.length} record{hits.length === 1 ? '' : 's'} shown for {labels.sectors[sector] || sector}
          </p>
          <div className="nat-grid">
            {hits.map((h) => (
              <MapCard key={h.record.id} record={h.record} labels={labels} />
            ))}
          </div>
          <SectorGaps data={gaps} labels={labels} />
        </>
      )}
    </div>
  )
}

/* ── Page ────────────────────────────────────────────────────────────────── */

export default function Nature() {
  const [tab, setTab] = useState('library')
  const [meta, setMeta] = useState(null)
  const [stats, setStats] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    Promise.all([fetchNatureMeta(), fetchNatureStats()])
      .then(([m, s]) => {
        if (!live) return
        setMeta(m)
        setStats(s)
      })
      .catch((e) => live && setError(e.message || 'Could not load the nature library'))
    return () => {
      live = false
    }
  }, [])

  const labels = useMemo(
    () => ({
      functions: labelMap(meta?.taxonomy?.functions),
      sectors: labelMap(meta?.taxonomy?.sectors, 'label_en'),
    }),
    [meta],
  )

  return (
    <div className="nat">
      <div className="nat-bg" aria-hidden="true">
        <span className="nat-blob nat-blob--a" />
        <span className="nat-blob nat-blob--b" />
        <span className="nat-blob nat-blob--c" />
      </div>

      <header className="nat-topbar">
        <Link to="/" className="nat-brand">
          <Logo className="nat-brand__logo" />
          <span>Sylva</span>
        </Link>
        <nav className="nat-nav">
          <Link to="/hardware">Hardware</Link>
          <Link to="/wild">Wild</Link>
        </nav>
      </header>

      <main className="nat-main">
        <section className="nat-hero">
          <div className="nat-hero__text">
            <span className="nat-eyebrow">Learning from nature</span>
            <h1>Nature library</h1>
            <p className="nat-lede">
              Mechanisms, materials and practices from nature, each with its evidence and review status, linked to
              what industry is researching.
            </p>
          </div>
          {stats && (
            <div className="nat-counts" aria-label="Coverage">
              <CountBubble value={stats.map_total} label="map records" delay={0} tone="map" />
              <CountBubble value={stats.library_served} label="library records" delay={180} tone="lib" />
            </div>
          )}
        </section>

        <ErrorBox error={error} />
        {!meta && !error && <Loading>Loading the library…</Loading>}

        {meta && (
          <>
            <div className="nat-tabs" role="tablist" aria-label="Nature sections">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  id={`nat-tab-${t.id}`}
                  aria-selected={tab === t.id}
                  aria-controls={`nat-panel-${t.id}`}
                  className={tab === t.id ? 'is-active' : ''}
                  onClick={() => setTab(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div role="tabpanel" id={`nat-panel-${tab}`} aria-labelledby={`nat-tab-${tab}`} className="nat-tabpanel" key={tab}>
              {tab === 'library' && <LibraryTab meta={meta} labels={labels} />}
              {tab === 'map' && <MapTab meta={meta} labels={labels} />}
            </div>
          </>
        )}
      </main>
    </div>
  )
}
