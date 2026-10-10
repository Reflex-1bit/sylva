import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  askNature,
  fetchLibraryRecord,
  fetchNatureMeta,
  fetchNatureStats,
  fetchSectorGaps,
  natureExportUrl,
  searchLibrary,
  searchMap,
} from './api'
import Logo from './Logo'
import './Nature.css'

const TABS = [
  { id: 'ask', label: 'Ask nature' },
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
const VERDICT_LABEL = {
  promising: 'Promising options found',
  weak: 'Only weak matches',
  no_strong_option: 'No strong option',
}

const pct = (x) => `${Math.round((x || 0) * 100)}%`

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

function Chip({ active, onClick, children }) {
  return (
    <button type="button" className={`nat-chip ${active ? 'is-active' : ''}`} aria-pressed={active} onClick={onClick}>
      {children}
    </button>
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

function RecordCard({ record, grade, why, caveat, labels }) {
  const organism = record.organism
  return (
    <article className="nat-card">
      <header className="nat-card__head">
        <h4>{record.title}</h4>
        <div className="nat-row">
          <span className="nat-tag">{KIND_LABEL[record.kind] || record.kind}</span>
          <GradePill grade={grade} />
          <StatusBadge status={record.provenance?.status} />
        </div>
      </header>
      {organism?.scientific_name && (
        <p className="nat-muted">
          <em>{organism.scientific_name}</em>
          {organism.common_names?.length ? ` · ${organism.common_names.join(', ')}` : ''}
        </p>
      )}
      {why && <p className="nat-why">{why}</p>}
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
        {caveat || record.caveat}
      </p>
      {record.popular_claim_note && <p className="nat-caveat">{record.popular_claim_note}</p>}
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
    </article>
  )
}

function MapCard({ record, labels }) {
  const ids = record.identifiers || {}
  const href = ids.doi ? `https://doi.org/${ids.doi}` : safeUrl(ids.url)
  return (
    <article className="nat-card">
      <header className="nat-card__head">
        <h4>{href ? <ExternalLink href={href}>{record.title}</ExternalLink> : record.title}</h4>
        <div className="nat-row">
          <span className="nat-tag">{MAP_TYPE_LABEL[record.type] || record.type}</span>
          <span className="nat-tag">{labels.sectors[record.sector] || record.sector}</span>
          <span className="nat-tag">{NATURE_LINK_LABEL[record.nature_link] || record.nature_link}</span>
          <StatusBadge status={record.provenance?.status} />
        </div>
      </header>
      {record.summary && <p>{record.summary}</p>}
      <p className="nat-muted">
        {[record.country, record.year, record.trl ? `TRL ${record.trl}` : null].filter(Boolean).join(' · ')}
        {record.organisations?.length ? ` · ${record.organisations.map((o) => o.name).join(', ')}` : ''}
      </p>
      <div className="nat-row">
        {(record.problem_functions || []).map((f) => (
          <span key={f} className="nat-tag nat-tag--fn">
            {labels.functions[f] || f}
          </span>
        ))}
      </div>
    </article>
  )
}

function SectorGaps({ data, labels }) {
  if (!data) return null
  return (
    <section className="nat-panel" aria-label="Sector gaps">
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

/* ── Ask tab ─────────────────────────────────────────────────────────────── */

function AskTab({ meta, labels }) {
  const [challenge, setChallenge] = useState('')
  const [sector, setSector] = useState('')
  const [areas, setAreas] = useState([])
  const [phase, setPhase] = useState('idle')
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [extra, setExtra] = useState({})

  const tooShort = challenge.trim().length < 8
  const toggleArea = (id) => setAreas((a) => (a.includes(id) ? a.filter((x) => x !== id) : [...a, id]))

  async function submit(e) {
    e.preventDefault()
    if (tooShort || phase === 'loading') return
    setPhase('loading')
    setError('')
    setResult(null)
    setExtra({})
    try {
      const res = await askNature({ challenge: challenge.trim(), sector: sector || null, areas })
      setResult(res)
      setPhase('done')
      // Options are normally in library_hits; fetch only ids that are missing.
      const have = new Set([
        ...res.library_hits.map((h) => h.record.id),
        ...(res.map_hits || []).map((h) => h.record.id),
      ])
      const missing = (res.answer?.options || [])
        .map((o) => o.record_id)
        .filter((id) => !have.has(id) && String(id).startsWith('lib-'))
      for (const id of missing) {
        fetchLibraryRecord(id)
          .then((r) => setExtra((x) => ({ ...x, [id]: r })))
          .catch(() => setExtra((x) => ({ ...x, [id]: { failed: true } })))
      }
    } catch (err) {
      setError(err.message || 'Something went wrong')
      setPhase('error')
    }
  }

  const answer = result?.answer
  const hitById = useMemo(() => {
    const m = {}
    for (const h of result?.library_hits || []) m[h.record.id] = h
    return m
  }, [result])
  const mapById = useMemo(() => {
    const m = {}
    for (const h of result?.map_hits || []) m[h.record.id] = h.record
    return m
  }, [result])
  const isFallback = result?.model?.startsWith('fallback')

  return (
    <div>
      <form className="nat-panel" onSubmit={submit}>
        <div className="nat-field">
          <label htmlFor="nat-challenge">Your design or engineering challenge</label>
          <textarea
            id="nat-challenge"
            rows={3}
            maxLength={2000}
            value={challenge}
            onChange={(e) => setChallenge(e.target.value)}
            placeholder="For example: keep a greenhouse cool without electricity"
          />
        </div>
        <Select
          id="nat-ask-sector"
          label="Sector (optional)"
          value={sector}
          onChange={setSector}
          options={(meta.taxonomy.sectors || []).map((s) => [s.id, s.label_en])}
        />
        <fieldset className="nat-field">
          <legend>Focus areas (optional)</legend>
          <div className="nat-row">
            {(meta.taxonomy.areas || []).map((a) => (
              <Chip key={a.id} active={areas.includes(a.id)} onClick={() => toggleArea(a.id)}>
                {a.label}
              </Chip>
            ))}
          </div>
        </fieldset>
        <button type="submit" className="nat-btn" disabled={tooShort || phase === 'loading'}>
          {phase === 'loading' ? 'Searching…' : 'Ask nature'}
        </button>
        {tooShort && challenge.length > 0 && <p className="nat-muted">Please write at least 8 characters.</p>}
      </form>

      {phase === 'loading' && <Loading>Searching the library. This can take up to a minute.</Loading>}
      {phase === 'error' && <ErrorBox error={error} />}

      {result && answer && (
        <div className="nat-results">
          <div className="nat-row">
            <span className={`nat-verdict nat-verdict--${result.verdict}`}>
              {VERDICT_LABEL[result.verdict] || result.verdict}
            </span>
            {result.parsed_functions?.map((f) => (
              <span key={f} className="nat-tag nat-tag--fn">
                {labels.functions[f] || f}
              </span>
            ))}
          </div>
          {isFallback && (
            <p className="nat-note" data-testid="fallback-note">
              Ranked by Sylva&apos;s published scoring; AI phrasing unavailable.
            </p>
          )}
          {answer.summary && <p className="nat-summary">{answer.summary}</p>}

          {(answer.options || []).length > 0 && (
            <section aria-label="Options">
              <h3>Options</h3>
              <div className="nat-grid">
                {answer.options.map((o) => {
                  const hit = hitById[o.record_id]
                  const mapRec = !hit && mapById[o.record_id]
                  if (mapRec) {
                    return (
                      <div key={o.record_id}>
                        {o.why && <p className="nat-why">{o.why}</p>}
                        <MapCard record={mapRec} labels={labels} />
                        {o.caveat && <p className="nat-caveat"><strong>Caveat: </strong>{o.caveat}</p>}
                      </div>
                    )
                  }
                  const record = hit?.record || extra[o.record_id]?.record
                  const grade = hit?.evidence_grade || extra[o.record_id]?.evidence_grade
                  if (!record) {
                    const failed = extra[o.record_id]?.failed || !String(o.record_id).startsWith('lib-')
                    return (
                      <p key={o.record_id} className="nat-muted">
                        {failed ? `Record ${o.record_id} is unavailable.` : `Loading ${o.record_id}…`}
                      </p>
                    )
                  }
                  return (
                    <RecordCard key={o.record_id} record={record} grade={grade} why={o.why} caveat={o.caveat} labels={labels} />
                  )
                })}
              </div>
            </section>
          )}

          {answer.open_questions?.length > 0 && (
            <section aria-label="Open questions">
              <h3>Open questions</h3>
              <ul>
                {answer.open_questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </section>
          )}
          {answer.next_steps?.length > 0 && (
            <section aria-label="Next steps">
              <h3>Next steps</h3>
              <ul>
                {answer.next_steps.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </section>
          )}

          {result.map_hits?.length > 0 && (
            <section aria-label="Industry evidence">
              <h3>Industry R&amp;D evidence</h3>
              <p className="nat-note">Work found in the map. Being inspired by nature is not the same as being better for nature.</p>
              <div className="nat-grid">
                {result.map_hits.map((h) => (
                  <MapCard key={h.record.id} record={h.record} labels={labels} />
                ))}
              </div>
            </section>
          )}

          {answer.sector_gaps && <SectorGaps data={answer.sector_gaps} labels={labels} />}
          {result.gaps?.length > 0 && (
            <p className="nat-muted">Unmet needs noted: {result.gaps.join('; ')}</p>
          )}
        </div>
      )}
    </div>
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
      searchLibrary({ ...f, q: f.q.trim(), limit: 30 })
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
        <div className="nat-field">
          <label htmlFor="nat-lib-q">Search</label>
          <input id="nat-lib-q" type="search" value={f.q} onChange={(e) => set('q')(e.target.value)} />
        </div>
        <Select id="nat-lib-area" label="Area" value={f.area} onChange={set('area')} options={(tx.areas || []).map((a) => [a.id, a.label])} />
        <Select id="nat-lib-sector" label="Sector" value={f.sector} onChange={set('sector')} options={(tx.sectors || []).map((s) => [s.id, s.label_en])} />
        <Select id="nat-lib-kind" label="Kind" value={f.kind} onChange={set('kind')} options={Object.entries(KIND_LABEL)} />
        <Select id="nat-lib-status" label="Review status" value={f.status} onChange={set('status')} options={Object.entries(STATUS_LABEL)} />
      </div>
      {phase === 'loading' && <Loading>{hits.length ? 'Updating results…' : 'Loading records…'}</Loading>}
      {phase === 'error' && <ErrorBox error={error} />}
      {phase === 'done' && hits.length === 0 && <p className="nat-state">No records match these filters.</p>}
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
          <p className="nat-summary">
            {hits.length} record{hits.length === 1 ? '' : 's'} shown for {labels.sectors[sector] || sector}.
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
  const [tab, setTab] = useState('ask')
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
      <header className="nat-topbar">
        <Link to="/" className="nat-brand">
          <Logo className="nat-brand__logo" />
          <span>Sylva</span>
        </Link>
        <nav className="nat-nav">
          <Link to="/hardware">Hardware</Link>
        </nav>
      </header>

      <main className="nat-main">
        <h1>Nature library</h1>
        <p className="nat-lede">
          Mechanisms, materials and practices from nature, each with its evidence and review status, linked to
          what industry is researching.
        </p>

        {stats && (
          <section className="nat-stats" aria-label="Coverage">
            <dl>
              <div><dt>Library records</dt><dd>{stats.library_served}</dd></div>
              <div><dt>Expert-validated</dt><dd>{pct(stats.validated_share)}</dd></div>
              <div><dt>With measured values</dt><dd>{pct(stats.measured_share)}</dd></div>
              <div><dt>Industry map records</dt><dd>{stats.map_total}</dd></div>
            </dl>
            <p className="nat-licence">
              <ExternalLink href={meta?.licence?.url || 'https://creativecommons.org/licenses/by/4.0/'}>
                <span className="nat-badge nat-badge--licence">{meta?.licence?.name || 'CC BY 4.0'}</span>
              </ExternalLink>{' '}
              Export library:{' '}
              <a href={natureExportUrl('library', 'json')}>JSON</a>, <a href={natureExportUrl('library', 'csv')}>CSV</a>
              {' · '}map: <a href={natureExportUrl('industry_map', 'json')}>JSON</a>,{' '}
              <a href={natureExportUrl('industry_map', 'csv')}>CSV</a>
            </p>
            {meta?.licence?.attribution && <p className="nat-muted">{meta.licence.attribution}</p>}
          </section>
        )}

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
            <div role="tabpanel" id={`nat-panel-${tab}`} aria-labelledby={`nat-tab-${tab}`}>
              {tab === 'ask' && <AskTab meta={meta} labels={labels} />}
              {tab === 'library' && <LibraryTab meta={meta} labels={labels} />}
              {tab === 'map' && <MapTab meta={meta} labels={labels} />}
            </div>
          </>
        )}
      </main>
    </div>
  )
}
