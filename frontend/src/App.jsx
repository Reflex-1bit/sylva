import { useEffect, useRef, useState, useTransition } from 'react'
import { Link } from 'react-router-dom'
import { fetchRecommendations, geocode } from './api'
import Logo from './Logo'
import './App.css'

const EXAMPLES = ['Córdoba, Spain', 'Nairobi, Kenya', 'Guelph, Ontario']

export default function App() {
  const [query, setQuery] = useState('')
  const [phase, setPhase] = useState('idle') // idle | loading | results | error
  const [error, setError] = useState('')
  const [place, setPlace] = useState(null)
  const [data, setData] = useState(null)
  const [isPending, startTransition] = useTransition()
  const inputRef = useRef(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  async function runSearch(raw) {
    const q = (raw ?? query).trim()
    if (!q || phase === 'loading') return

    setPhase('loading')
    setError('')
    setData(null)

    try {
      const loc = await geocode(q)
      setPlace(loc)
      const rec = await fetchRecommendations({
        lat: loc.lat,
        lon: loc.lon,
        country: loc.country,
      })
      startTransition(() => {
        setData(rec)
        setPhase('results')
      })
    } catch (e) {
      setError(e.message || 'Something went wrong')
      setPhase('error')
    }
  }

  function reset() {
    setPhase('idle')
    setData(null)
    setPlace(null)
    setError('')
    setQuery('')
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  const busy = phase === 'loading' || isPending
  const showResults = phase === 'results' && data

  return (
    <div className={`shell ${showResults ? 'shell--results' : ''}`}>
      <div className="atmosphere" aria-hidden="true">
        <div className="atmosphere__wash" />
        <div className="atmosphere__grain" />
        <div className="atmosphere__hill atmosphere__hill--a" />
        <div className="atmosphere__hill atmosphere__hill--b" />
        <div className="atmosphere__canopy" />
      </div>

      <header className="topbar">
        <button type="button" className="brand" onClick={reset} aria-label="Sylva home">
          <Logo className="brand__logo" />
          <span className="brand__name">Sylva</span>
        </button>
        <nav className="topnav">
          <Link to="/hardware">Hardware</Link>
          {showResults && (
            <button type="button" className="ghost-btn" onClick={reset}>
              New location
            </button>
          )}
        </nav>
      </header>

      <main className="main">
        {!showResults ? (
          <section className="hero">
            <p className="hero__eyebrow">Agroforestry intelligence</p>
            <div className="hero__brand">
              <Logo className="hero__logo" />
              <h1 className="hero__title">Sylva</h1>
            </div>
            <p className="hero__lede">
              Match trees to your soil. Get a phased transition plan you can actually plant.
            </p>

            <SearchForm
              query={query}
              setQuery={setQuery}
              onSubmit={runSearch}
              busy={busy}
              inputRef={inputRef}
              large
            />

            {phase === 'error' && <p className="banner banner--error" role="alert">{error}</p>}
            {busy && (
              <p className="banner banner--busy">
                Reading soil · matching species · drafting plan…
                <span className="banner__hint"> usually under 30s</span>
              </p>
            )}

            {!busy && phase !== 'error' && (
              <div className="examples">
                <span>Try</span>
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    className="chip"
                    onClick={() => {
                      setQuery(ex)
                      runSearch(ex)
                    }}
                  >
                    {ex}
                  </button>
                ))}
              </div>
            )}
          </section>
        ) : (
          <ResultsView
            place={place}
            data={data}
            query={query}
            setQuery={setQuery}
            onSubmit={runSearch}
            busy={busy}
            inputRef={inputRef}
            error={phase === 'error' ? error : ''}
          />
        )}
      </main>
    </div>
  )
}

function SearchForm({ query, setQuery, onSubmit, busy, inputRef, large }) {
  return (
    <form
      className={`search ${large ? 'search--hero' : ''}`}
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
    >
      <label className="sr-only" htmlFor="loc">
        Farm location
      </label>
      <input
        id="loc"
        ref={inputRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Town, region, or coordinates"
        autoComplete="off"
        disabled={busy}
      />
      <button type="submit" disabled={busy || !query.trim()}>
        {busy ? 'Working…' : 'Plan'}
      </button>
    </form>
  )
}

function ResultsView({ place, data, query, setQuery, onSubmit, busy, inputRef, error }) {
  const plan = data.plan || {}
  const profile = data.profile || {}
  const soil = profile.soil?.topsoil
  const soilSource = profile.soil?.source || ''
  const ndvi = profile.ndvi
  const topo = profile.topography
  const species = plan.priority_species?.length
    ? plan.priority_species
    : (data.recommended_species || []).slice(0, 5).map((s) => ({
        species: s.species,
        reason: s.nitrogen_fixer
          ? 'Nitrogen-fixing — builds soil'
          : (s.uses || []).slice(0, 2).join(', '),
      }))

  const phases = [
    { key: 'years_0_3', label: 'Years 0–3', text: plan.phased_plan?.years_0_3 },
    { key: 'years_3_7', label: 'Years 3–7', text: plan.phased_plan?.years_3_7 },
    { key: 'years_7_plus', label: 'Years 7+', text: plan.phased_plan?.years_7_plus },
  ].filter((p) => p.text)

  return (
    <div className="results">
      <div className="results__head">
        <div>
          <p className="place-label">{place?.label}</p>
          <p className="place-meta">
            {place?.lat.toFixed(4)}, {place?.lon.toFixed(4)}
            {data.plan_model ? ` · ${data.plan_model}` : ''}
          </p>
        </div>
        <SearchForm
          query={query}
          setQuery={setQuery}
          onSubmit={onSubmit}
          busy={busy}
          inputRef={inputRef}
        />
      </div>

      {error && <p className="banner banner--error" role="alert">{error}</p>}

      <div className="results__grid">
        <article className="panel panel--lead reveal">
          <h2>Transition plan</h2>
          <p className="lede">{plan.summary}</p>
          {plan.recommended_layout && (
            <p className="layout-callout">
              <span>Layout</span>
              {plan.recommended_layout}
            </p>
          )}
        </article>

        <aside className="vitals reveal reveal--delay">
          <Vital
            label="Soil pH"
            value={soil?.ph != null ? Number(soil.ph).toFixed(1) : '—'}
          />
          <Vital label="Texture" value={soil?.texture_class || '—'} />
          <Vital
            label="Organic C"
            value={
              soil?.organic_carbon_g_kg != null
                ? `${soil.organic_carbon_g_kg} g/kg`
                : '—'
            }
          />
          <Vital
            label="Vegetation"
            value={ndvi?.health_label || '—'}
            bar={ndvi?.health_score}
          />
          {topo?.elevation?.mean_m != null && (
            <Vital label="Elevation" value={`${Math.round(topo.elevation.mean_m)} m`} />
          )}
          {soilSource && (
            <p className="source-note">{soilSource}</p>
          )}
        </aside>

        <section className="panel reveal reveal--delay2">
          <h2>Priority species</h2>
          <ul className="species">
            {species.map((s, i) => {
              const name = typeof s === 'string' ? s : s.species
              const reason = typeof s === 'string' ? '' : s.reason
              return (
                <li key={`${name}-${i}`}>
                  <em>{name}</em>
                  {reason && <span>{reason}</span>}
                </li>
              )
            })}
          </ul>
        </section>

        {phases.length > 0 && (
          <section className="panel panel--phases reveal reveal--delay3">
            <h2>Phased roadmap</h2>
            <ol className="timeline">
              {phases.map((p) => (
                <li key={p.key}>
                  <strong>{p.label}</strong>
                  <p>{p.text}</p>
                </li>
              ))}
            </ol>
          </section>
        )}

        {plan.next_actions?.length > 0 && (
          <section className="panel reveal reveal--delay3">
            <h2>This season</h2>
            <ul className="actions">
              {plan.next_actions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </section>
        )}

        {plan.soil_notes && (
          <section className="panel panel--quiet reveal reveal--delay3">
            <h2>Soil notes</h2>
            <p>{plan.soil_notes}</p>
          </section>
        )}
      </div>
    </div>
  )
}

function Vital({ label, value, bar }) {
  return (
    <div className="vital">
      <span className="vital__label">{label}</span>
      <span className="vital__value">{value}</span>
      {typeof bar === 'number' && (
        <span className="vital__bar" aria-hidden="true">
          <i style={{ width: `${Math.round(bar * 100)}%` }} />
        </span>
      )}
    </div>
  )
}
