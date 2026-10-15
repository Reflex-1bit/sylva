import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { askWild, fetchWildMeta } from './api'
import Logo from './Logo'
import './App.css'
import './Wild.css'

const INTENTS = [
  { id: 'fix', label: 'Fix a problem', hint: 'Something in your product or process is not working well enough.' },
  { id: 'build', label: 'Build something new', hint: 'You are designing a new product, material or system.' },
]

const EXAMPLES = {
  fix: 'Our ship hulls lose fuel to drag and fouling',
  build: 'A facade that keeps an office cool without air conditioning',
}

const NOT_SURE = { id: '', label_en: 'Not sure' }

const MIN_PROBLEM = 10
const MAX_PROBLEM = 1000

// Only http(s) links are rendered; anything else is shown as plain text.
const safeUrl = (u) => (typeof u === 'string' && /^https?:\/\//i.test(u) ? u : null)

export default function Wild() {
  const [meta, setMeta] = useState(null)
  const [metaError, setMetaError] = useState('')
  const [step, setStep] = useState(1)
  const [intent, setIntent] = useState(null)
  const [sector, setSector] = useState(null) // null = not chosen yet, '' = not sure
  const [problem, setProblem] = useState('')
  const [phase, setPhase] = useState('idle') // idle | loading | results | error
  const [error, setError] = useState('')
  const [data, setData] = useState(null)
  const headingRef = useRef(null)
  const textRef = useRef(null)

  useEffect(() => {
    let live = true
    fetchWildMeta()
      .then((m) => live && setMeta(m))
      .catch((e) => live && setMetaError(e.message || 'Could not load the industry list'))
    return () => {
      live = false
    }
  }, [])

  // Move focus to each new step's question (not on first load), without scrolling the page.
  const firstRender = useRef(true)
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    if (phase !== 'idle' && phase !== 'error') return
    const target = step === 3 ? textRef.current : headingRef.current
    target?.focus({ preventScroll: true })
  }, [step, phase])

  const sectors = meta?.sectors || []
  const sectorLabel = useMemo(() => {
    if (sector === '') return NOT_SURE.label_en
    return sectors.find((s) => s.id === sector)?.label_en || sector
  }, [sector, sectors])

  const busy = phase === 'loading'
  const showResults = phase === 'results' && data
  const trimmed = problem.trim()

  async function submit(e) {
    e?.preventDefault()
    if (busy || trimmed.length < MIN_PROBLEM) return
    setPhase('loading')
    setError('')
    try {
      const res = await askWild({ intent, sector: sector || null, problem: trimmed })
      setData(res)
      setPhase('results')
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      setError(err.message || 'Something went wrong')
      setPhase('error')
    }
  }

  function restart() {
    setStep(1)
    setIntent(null)
    setSector(null)
    setProblem('')
    setData(null)
    setError('')
    setPhase('idle')
  }

  function editBrief() {
    setData(null)
    setPhase('idle')
    setStep(3)
  }

  return (
    <div className={`wild shell ${showResults ? 'shell--results' : ''}`}>
      <div className="atmosphere" aria-hidden="true">
        <div className="atmosphere__wash" />
        <div className="atmosphere__grain" />
        <div className="atmosphere__hill atmosphere__hill--a" />
        <div className="atmosphere__hill atmosphere__hill--b" />
        <div className="atmosphere__canopy" />
      </div>

      <header className="topbar">
        <button type="button" className="brand" onClick={restart} aria-label="Sylva-wild home">
          <Logo className="brand__logo" />
          <span className="brand__name">Sylva-wild</span>
        </button>
        <nav className="topnav">
          <Link to="/">Sylva</Link>
          <Link to="/nature">Nature</Link>
          <Link to="/catalogue">Catalogue</Link>
          {showResults && (
            <button type="button" className="ghost-btn" onClick={restart}>
              New question
            </button>
          )}
        </nav>
      </header>

      <main className="main">
        {!showResults ? (
          <section className="hero wild-hero">
            <p className="hero__eyebrow">Nature-inspired solutions for industry</p>
            <div className="hero__brand">
              <Logo className="hero__logo" />
              <h1 className="hero__title">Sylva-wild</h1>
            </div>
            <p className="hero__lede">
              Tell us what you are working on. We search{' '}
              {meta?.record_count ? meta.record_count.toLocaleString('en') : '99,000+'} studies of
              how nature solves it, and show who protects the species behind them.
            </p>

            <Steps step={step} intent={intent} sectorLabel={sector === null ? null : sectorLabel} onJump={setStep} />

            {step === 1 && (
              <fieldset className="wild-step">
                <legend tabIndex={-1} ref={headingRef} className="wild-step__q">
                  What do you want to do?
                </legend>
                <div className="wild-choices">
                  {INTENTS.map((i) => (
                    <button
                      key={i.id}
                      type="button"
                      className="wild-choice"
                      aria-pressed={intent === i.id}
                      onClick={() => {
                        setIntent(i.id)
                        setStep(2)
                      }}
                    >
                      <strong>{i.label}</strong>
                      <span>{i.hint}</span>
                    </button>
                  ))}
                </div>
              </fieldset>
            )}

            {step === 2 && (
              <fieldset className="wild-step">
                <legend tabIndex={-1} ref={headingRef} className="wild-step__q">
                  Which industry are you in?
                </legend>
                {metaError && <p className="banner banner--error" role="alert">{metaError}</p>}
                {!meta && !metaError && <p className="banner banner--busy">Loading industries…</p>}
                <div className="examples wild-sectors">
                  {[...sectors, NOT_SURE].map((s) => (
                    <button
                      key={s.id || 'not-sure'}
                      type="button"
                      className="chip"
                      aria-pressed={sector === s.id}
                      onClick={() => {
                        setSector(s.id)
                        setStep(3)
                      }}
                    >
                      {s.label_en}
                    </button>
                  ))}
                </div>
                <button type="button" className="wild-back" onClick={() => setStep(1)}>
                  ← Back
                </button>
              </fieldset>
            )}

            {step === 3 && (
              <form className="wild-step" onSubmit={submit}>
                <label htmlFor="wild-problem" className="wild-step__q">
                  {intent === 'build' ? 'What do you want to build?' : 'What do you want to fix?'}
                </label>
                <div className="search search--hero wild-ask">
                  <textarea
                    id="wild-problem"
                    ref={textRef}
                    rows={3}
                    value={problem}
                    maxLength={MAX_PROBLEM}
                    onChange={(e) => setProblem(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(e)
                    }}
                    placeholder={`e.g. ${EXAMPLES[intent || 'fix']}`}
                    aria-describedby="wild-notice"
                    disabled={busy}
                  />
                  <button type="submit" disabled={busy || trimmed.length < MIN_PROBLEM}>
                    {busy ? 'Searching…' : "Find nature's solutions"}
                  </button>
                </div>
                <p id="wild-notice" className="wild-notice">
                  {meta && !meta.llm_available
                    ? 'Your text is only used to search the catalogue; Sylva does not store it. Write in English for the best matches.'
                    : `${meta?.notice || "Don't include confidential details. Your text is sent to Google Gemini to process it; Sylva does not store it."} English, Spanish or Portuguese.`}
                </p>
                {phase === 'error' && <p className="banner banner--error" role="alert">{error}</p>}
                {busy && (
                  <p className="banner banner--busy" role="status">
                    Reading your brief · searching {meta?.record_count?.toLocaleString('en') || ''} studies · grouping solutions…
                    <span className="banner__hint"> usually under 20s</span>
                  </p>
                )}
                {!busy && (
                  <button type="button" className="wild-back" onClick={() => setStep(2)}>
                    ← Back
                  </button>
                )}
              </form>
            )}
          </section>
        ) : (
          <Results data={data} intent={intent} sectorLabel={sectorLabel} problem={trimmed} onEdit={editBrief} />
        )}
      </main>
    </div>
  )
}

function Steps({ step, intent, sectorLabel, onJump }) {
  const intentLabel = INTENTS.find((i) => i.id === intent)?.label
  const items = [
    { n: 1, label: intentLabel || 'Goal' },
    { n: 2, label: sectorLabel || 'Industry' },
    { n: 3, label: 'Describe' },
  ]
  return (
    <ol className="wild-steps" aria-label={`Step ${step} of 3`}>
      {items.map((it) => {
        const done = it.n < step
        return (
          <li key={it.n} className={`wild-steps__item ${it.n === step ? 'is-current' : ''} ${done ? 'is-done' : ''}`}>
            {done ? (
              <button type="button" onClick={() => onJump(it.n)} aria-label={`Change step ${it.n}: ${it.label}`}>
                <span className="wild-steps__n">{it.n}</span>
                {it.label}
              </button>
            ) : (
              <span aria-current={it.n === step ? 'step' : undefined}>
                <span className="wild-steps__n">{it.n}</span>
                {it.label}
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}

function Results({ data, intent, sectorLabel, problem, onEdit }) {
  const byRef = useMemo(() => Object.fromEntries(data.records.map((r) => [r.ref, r])), [data])
  const aiWritten = data.model !== 'search only'

  return (
    <div className="results">
      <div className="results__head">
        <div>
          <p className="place-label">Nature&apos;s solutions</p>
          <p className="place-meta">
            {INTENTS.find((i) => i.id === intent)?.label} · {sectorLabel} ·{' '}
            {aiWritten ? `grouped by ${data.model}` : 'search results only'}
          </p>
          <p className="wild-brief">“{problem}”</p>
        </div>
        <button type="button" className="ghost-btn" onClick={onEdit}>
          Edit description
        </button>
      </div>

      <div className="results__grid wild-grid">
        <article className="panel panel--lead reveal">
          <h2>Summary</h2>
          <p className="lede">{data.summary}</p>
          {data.queries?.length > 0 && (
            <p className="layout-callout">
              <span>Searched for</span>
              {data.queries.join(' · ')}
            </p>
          )}
        </article>

        <aside className="panel reveal reveal--delay">
          <h2>Next steps</h2>
          <ul className="actions">
            {(data.next_steps?.length ? data.next_steps : ['Read the cited studies before relying on them.']).map(
              (s, i) => (
                <li key={i}>{s}</li>
              ),
            )}
          </ul>
          <p className="source-note">
            Not engineering advice. Inspired by nature is not the same as better for nature; check each
            study.
          </p>
        </aside>

        {data.solutions.map((s, i) => (
          <SolutionCard key={`${s.title}-${i}`} solution={s} byRef={byRef} delay={i} />
        ))}

        {data.records.length > 0 && (
          <section className="panel panel--phases reveal reveal--delay3">
            <h2>All matching studies</h2>
            <ol className="wild-records">
              {data.records.map((r) => (
                <li key={r.id} id={`study-${r.ref}`}>
                  <span className="wild-ref">{r.ref}</span>
                  <div>
                    <StudyLink record={r} />
                    <p className="wild-record__meta">
                      {[r.year, r.kind, r.organism && `organism: ${r.organism}`, !r.has_summary && 'title only']
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                    <Donations groups={r.groups} compact />
                  </div>
                </li>
              ))}
            </ol>
          </section>
        )}

        <section className="panel panel--quiet wild-offer reveal reveal--delay3">
          <p className="wild-offer__tag">Coming soon</p>
          <h2>Need a solution built for you?</h2>
          <p className="lede">
            Sylva-wild will arrange custom research with wildlife reserves and university partners: studying
            how a species solves your problem, under research permits and without harm to wildlife. Part of
            every project fee funds conservation at the partner reserve.
          </p>
          <button type="button" className="wild-offer__btn" disabled aria-disabled="true">
            Register interest — opening soon
          </button>
        </section>
      </div>

      <p className="wild-attribution">{data.attribution}</p>
    </div>
  )
}

function SolutionCard({ solution, byRef, delay }) {
  const cited = solution.refs.map((r) => byRef[r]).filter(Boolean)
  const groups = []
  const seen = new Set()
  for (const r of cited) {
    for (const g of r.groups || []) {
      if (!seen.has(g.id)) {
        seen.add(g.id)
        groups.push(g)
      }
    }
  }
  return (
    <article className={`panel wild-solution reveal reveal--delay${Math.min(delay + 1, 3)}`}>
      <h2>{solution.title}</h2>
      {solution.nature_strategy && (
        <p className="wild-solution__row">
          <span>From nature</span>
          {solution.nature_strategy}
        </p>
      )}
      {solution.why_it_fits && (
        <p className="wild-solution__row">
          <span>Why it fits</span>
          {solution.why_it_fits}
        </p>
      )}
      {solution.caveat && (
        <p className="wild-solution__row wild-solution__row--caveat">
          <span>Caveat</span>
          {solution.caveat}
        </p>
      )}
      <div className="wild-solution__studies">
        <span className="wild-label">Studies</span>
        <ul>
          {cited.map((r) => (
            <li key={r.ref}>
              <a href={`#study-${r.ref}`} className="wild-ref">
                {r.ref}
              </a>{' '}
              <StudyLink record={r} />
              {r.year ? <span className="wild-record__meta"> · {r.year}</span> : null}
            </li>
          ))}
        </ul>
      </div>
      <Donations groups={groups} />
    </article>
  )
}

function StudyLink({ record }) {
  const url = safeUrl(record.url)
  return url ? (
    <a className="wild-study" href={url} target="_blank" rel="noopener noreferrer">
      {record.title}
    </a>
  ) : (
    <span className="wild-study">{record.title}</span>
  )
}

function Donations({ groups, compact }) {
  const valid = (groups || []).filter((g) => safeUrl(g.donate_url))
  if (!valid.length) return null
  return (
    <div className={`wild-donate ${compact ? 'wild-donate--compact' : ''}`}>
      {!compact && <span className="wild-label">Support the people protecting this habitat</span>}
      <div className="wild-donate__list">
        {valid.map((g) => (
          <a key={g.id} className="chip wild-donate__btn" href={safeUrl(g.donate_url)} target="_blank" rel="noopener noreferrer">
            Donate · {g.name}
          </a>
        ))}
      </div>
    </div>
  )
}
