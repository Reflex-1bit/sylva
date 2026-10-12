import { memo, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import Logo from './Logo'
import './Nature.css'
import './Catalogue.css'

// Everything on this page comes from static files under /catalogue/ (no API calls).
const BASE = '/catalogue/'
const PAGE = 100

const KINDS = [
  ['project', 'Project'],
  ['case_study', 'Case study'],
  ['patent', 'Patent'],
  ['paper', 'Paper'],
]
const KIND_LABEL = Object.fromEntries(KINDS)

// Same rule as app/routers/nature.py (_CSV_FORMULA_START / _csv_cell).
const CSV_FORMULA_START = ['=', '+', '-', '@', '\t', '\r']

// The AMBER list from docs/plans/research/sources.md: useful directories we link to but do not copy.
const MORE_DIRECTORIES = [
  {
    name: 'Europe PMC / PMC Open Access',
    url: 'https://europepmc.org',
    why: 'Licence is set per article; only the CC BY or CC0 full text is reusable, and it is mostly biomedical.',
  },
  {
    name: 'Semantic Scholar',
    url: 'https://www.semanticscholar.org',
    why: 'Bulk data needs an account and API key, data licences vary (some non-commercial), and OpenAlex already covers the same papers.',
  },
  {
    name: 'EU Ecolabel catalogue',
    url: 'https://environmental-data.ec.europa.eu/ecolabel/',
    why: 'Lists certified products rather than ideas, and the dataset licence is not yet verified.',
  },
  {
    name: 'Urban Nature Atlas (NATURVATION)',
    url: 'https://oppla.eu/product/18399',
    why: 'No formal licence; the data is available only on request.',
  },
  {
    name: 'Project Drawdown',
    url: 'https://www.drawdown.org',
    why: 'Its terms of use ban crawling and scraping; reuse needs written permission.',
  },
  {
    name: 'WIPO GREEN',
    url: 'https://www3.wipo.int/wipogreen/en/',
    why: 'Own terms where technology owners keep their rights, and parts need registration.',
  },
  {
    name: 'PANORAMA Solutions',
    url: 'https://panorama.solutions',
    why: 'Default licence is non-commercial (CC BY-NC 4.0), which does not fit a CC BY 4.0 dataset.',
  },
  {
    name: 'WOCAT',
    url: 'https://wocat.net',
    why: 'Practice write-ups are CC BY-NC-SA 4.0 (non-commercial) and the database terms were not found.',
  },
  {
    name: 'OPPLA / NetworkNature',
    url: 'https://oppla.eu',
    why: 'No licence found, so link-only.',
  },
  {
    name: 'Ellen MacArthur Foundation',
    url: 'https://www.ellenmacarthurfoundation.org',
    why: 'Case studies carry no licence we could find, so link-only.',
  },
  {
    name: 'Lens.org',
    url: 'https://www.lens.org',
    why: 'Bulk access needs a plan and its terms were not found.',
  },
  {
    name: 'EPO OPS / DOCDB',
    url: 'https://www.epo.org',
    why: 'Needs registration and the licence is unverified.',
  },
]

/* ── helpers ─────────────────────────────────────────────────────────────── */

const pct = (x) => (typeof x === 'number' && Number.isFinite(x) ? `${Math.round(x * 100)}%` : '–')
const fmt = (n) => (typeof n === 'number' ? n.toLocaleString('en') : '–')

function safeUrl(u) {
  return typeof u === 'string' && /^https?:\/\//i.test(u) ? u : null
}

function fold(s) {
  return String(s ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

// Text from data we do not control: strings stay, numbers become strings, null/objects are skipped.
function safeText(v) {
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  return ''
}

function textOf(v) {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'object') return safeText(v.name)
  return safeText(v)
}

const asArray = (v) => (Array.isArray(v) ? v : v == null ? [] : [v])

function organismName(r) {
  const o = r?.organism
  if (!o) return ''
  return safeText(typeof o === 'string' ? o : o.name)
}

function haystack(r) {
  return fold(
    [r.title, organismName(r), ...asArray(r.organisations).map(textOf)].join(' \u0001 '),
  )
}

let regionNames = null
try {
  regionNames = new Intl.DisplayNames(['en'], { type: 'region' })
} catch {
  regionNames = null
}
function countryName(code) {
  if (typeof code !== 'string' || !code) return ''
  try {
    return (regionNames && regionNames.of(code.toUpperCase())) || code
  } catch {
    return code
  }
}

function recordsOf(data) {
  if (Array.isArray(data)) return data
  return Array.isArray(data?.records) ? data.records : []
}

// Fetch one gzipped chunk and unpack it in the browser. If the server sent it with
// Content-Encoding: gzip, the browser has already decoded it (vite preview does this).
// If unpacking throws anyway, read it again as plain JSON.
const isAbort = (e) => e?.name === 'AbortError'

async function loadChunk(chunk, signal) {
  const path = chunk.path
  // The manifest's sha256 versions the URL, so a republished chunk is never served from an hour-old cache.
  const url = BASE + path + (chunk.sha256 ? `?v=${String(chunk.sha256).slice(0, 12)}` : '')
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(`Could not load ${path} (HTTP ${res.status})`)
  if (/gzip/i.test(res.headers.get('Content-Encoding') || '')) return recordsOf(await res.json())
  try {
    if (typeof DecompressionStream === 'undefined' || !res.body) throw new Error('no DecompressionStream')
    const stream = res.body.pipeThrough(new DecompressionStream('gzip'))
    return recordsOf(await new Response(stream).json())
  } catch (e) {
    if (isAbort(e) || signal?.aborted) throw e
    const again = await fetch(url, { signal })
    if (!again.ok) throw new Error(`Could not load ${path} (HTTP ${again.status})`)
    return recordsOf(await again.json())
  }
}

/* ── downloads (client-side) ─────────────────────────────────────────────── */

function sortKeysDeep(x) {
  if (Array.isArray(x)) return x.map(sortKeysDeep)
  if (x && typeof x === 'object') {
    return Object.fromEntries(
      Object.keys(x)
        .sort()
        .map((k) => [k, sortKeysDeep(x[k])]),
    )
  }
  return x
}

function csvCell(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (Array.isArray(v)) return v.map(csvCell).join('; ')
  if (typeof v === 'object') return JSON.stringify(sortKeysDeep(v))
  if (typeof v === 'string') return v && CSV_FORMULA_START.includes(v[0]) ? `'${v}` : v
  return String(v)
}

function csvQuote(s) {
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

// Rows are written as soon as their chunk arrives; the header only grows, so
// earlier rows are padded with empty cells at the end.
function createCsvBuilder() {
  const header = []
  const index = new Set()
  const rows = []
  const widths = []
  return {
    add(records) {
      for (const r of records) {
        if (!r || typeof r !== 'object') continue
        for (const k of Object.keys(r)) {
          if (!index.has(k)) {
            index.add(k)
            header.push(k)
          }
        }
        rows.push(header.map((k) => csvQuote(csvCell(r[k]))).join(','))
        widths.push(header.length)
      }
    },
    toBlob() {
      const parts = [header.map(csvQuote).join(',') + '\r\n']
      for (let i = 0; i < rows.length; i++) parts.push(rows[i] + ','.repeat(header.length - widths[i]) + '\r\n')
      return new Blob(parts, { type: 'text/csv;charset=utf-8' })
    },
  }
}

function createJsonBuilder(meta) {
  const parts = []
  return {
    add(records) {
      for (const r of records) parts.push((parts.length ? ',' : '') + JSON.stringify(r))
    },
    toBlob() {
      const head = JSON.stringify(meta).slice(0, -1) + ',"records":['
      return new Blob([head].concat(parts, [']}']), { type: 'application/json' })
    },
  }
}

function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

function fileName(manifest, scope, ext) {
  return `sylva-catalogue-${scope}-${manifest.version || 'unversioned'}-CC-BY-4.0.${ext}`
}

function wrapperMeta(manifest, sector) {
  const meta = {
    licence: manifest.licence,
    licence_url: manifest.licence_url,
    attribution: manifest.attribution,
    version: manifest.version,
    db: 'catalogue',
  }
  if (sector) meta.sector = sector
  return meta
}

/* ── small pieces ────────────────────────────────────────────────────────── */

function ExternalLink({ href, className, children }) {
  return (
    <a href={href} className={className} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  )
}

function SectorLabel({ sector }) {
  return (
    <>
      <span className="cat-label-en">{sector.label_en || sector.id}</span>
      {sector.label_es && sector.label_es !== sector.label_en && (
        <span className="cat-label-es" lang="es">
          {sector.label_es}
        </span>
      )}
    </>
  )
}

function PrecisionLine({ sector }) {
  if (typeof sector.precision !== 'number') {
    return <span className="nat-muted">Not spot-checked</span>
  }
  return (
    <span className="cat-prec">
      Strict precision <strong>{pct(sector.precision)}</strong> (n={fmt(sector.n)})
      {typeof sector.lenient_precision === 'number' && (
        <span className="nat-muted"> · lenient {pct(sector.lenient_precision)}</span>
      )}
    </span>
  )
}

function SectorFlags({ sector }) {
  if (!sector.low_sample && !sector.precision_warning) return null
  return (
    <span className="nat-row">
      {sector.precision_warning && <span className="nat-tag cat-flag cat-flag--warn">Low precision</span>}
      {sector.low_sample && <span className="nat-tag cat-flag">Low sample</span>}
    </span>
  )
}

function Donations({ ids, groupsById }) {
  const groups = asArray(ids)
    .map((id) => groupsById.get(id))
    .filter((g) => g && safeUrl(g.donate_url))
  if (!groups.length) return null
  return (
    <div className="cat-donate">
      <p className="cat-donate__head">Support the people protecting this habitat</p>
      <ul className="cat-donate__list">
        {groups.map((g) => (
          <li key={g.id}>
            <ExternalLink href={safeUrl(g.donate_url)} className="cat-donate__btn">
              Support {g.name || g.id}
            </ExternalLink>
            {g.every_org_slug && (
              <ExternalLink
                href={`https://www.every.org/${encodeURIComponent(g.every_org_slug)}#donate`}
                className="cat-donate__alt"
              >
                via Every.org
              </ExternalLink>
            )}
          </li>
        ))}
      </ul>
      <p className="nat-muted">
        Links go to each group&apos;s own donation page. Sylva does not handle money. Groups are matched by rules
        (organism, country, habitat); no partnership with the project is implied.
      </p>
    </div>
  )
}

const Row = memo(function Row({ r, ctx }) {
  const href = safeUrl(r.url) || (typeof r.doi === 'string' && r.doi ? `https://doi.org/${r.doi}` : null)
  const org = organismName(r)
  const gbifKey = r.organism && typeof r.organism === 'object' ? r.organism.gbif_key : null
  const source = ctx.sourcesById.get(r.source)
  const countries = asArray(r.countries).map(countryName).filter(Boolean)
  const orgs = asArray(r.organisations).map(textOf).filter(Boolean)
  const tags = asArray(r.sector_tags).map((t) => ctx.sectorLabels.get(t) || t)
  const confidence = typeof r.sort_confidence === 'number' ? r.sort_confidence.toFixed(2) : null
  const title = safeText(r.title) || '(untitled)'
  const summary = safeText(r.summary)

  return (
    <li className="cat-rec">
      <h4 className="cat-rec__title" dir="auto">{href ? <ExternalLink href={href}>{title}</ExternalLink> : title}</h4>
      <div className="nat-row cat-rec__meta">
        {r.kind && <span className="nat-tag">{KIND_LABEL[r.kind] || r.kind}</span>}
        {r.year != null && <span>{r.year}</span>}
        {org &&
          (gbifKey != null ? (
            <ExternalLink href={`https://www.gbif.org/species/${encodeURIComponent(gbifKey)}`} className="cat-organism">
              {org}
            </ExternalLink>
          ) : (
            <span className="cat-organism">{org}</span>
          ))}
        {r.source && (
          <span className="nat-badge cat-source" title={source?.licence ? `Licence: ${source.licence}` : undefined}>
            {source?.name || r.source}
          </span>
        )}
      </div>
      {countries.length > 0 && <p className="nat-muted">{countries.join(', ')}</p>}
      {orgs.length > 0 && (
        <p className="nat-muted cat-orgs">
          {orgs.slice(0, 4).join('; ')}
          {orgs.length > 4 ? ` and ${orgs.length - 4} more` : ''}
        </p>
      )}
      <details className="cat-details">
        <summary>Why this sector?</summary>
        <p>
          <code className="cat-reason">{r.sort_reason || 'No reason recorded.'}</code>
        </p>
        <p className="nat-muted">
          {confidence != null ? `Confidence ${confidence}` : 'Confidence not recorded'}
          {r.provenance ? ` · ${r.provenance === 'machine_sorted' ? 'machine-sorted by rules' : r.provenance}` : ''}
          {tags.length ? ` · also tagged: ${tags.join(', ')}` : ''}
        </p>
      </details>
      {summary && (
        <details className="cat-details">
          <summary>Summary</summary>
          <p className="cat-summary" dir="auto">{summary}</p>
          <p className="nat-muted">Summary licence: {r.summary_licence || 'not stated'}</p>
        </details>
      )}
      <Donations ids={r.group_ids} groupsById={ctx.groupsById} />
    </li>
  )
})

/* ── page ────────────────────────────────────────────────────────────────── */

export default function Catalogue() {
  const [manifest, setManifest] = useState(null)
  const [error, setError] = useState('')
  const [params, setParams] = useSearchParams()
  const sectorId = params.get('sector') || ''

  const [cache, setCache] = useState({}) // sector id -> records
  const [load, setLoad] = useState({ id: '', done: 0, total: 0, error: '' })
  const [query, setQuery] = useState('')
  const deferredQuery = useDeferredValue(query)
  const [kinds, setKinds] = useState([])
  const [shown, setShown] = useState({ key: '', n: PAGE })
  const [dl, setDl] = useState({ busy: false, message: '' })
  const [copied, setCopied] = useState('')
  const headingRef = useRef(null)
  const dlAbort = useRef(null)

  useEffect(() => {
    let live = true
    fetch(`${BASE}manifest.json`)
      .then((res) => {
        if (!res.ok) throw new Error(`Could not load the catalogue (HTTP ${res.status})`)
        return res.json()
      })
      .then((m) => live && setManifest(m))
      .catch((e) => live && setError(e.message || 'Could not load the catalogue'))
    return () => {
      live = false
    }
  }, [])

  const sectors = useMemo(() => asArray(manifest?.sectors).filter((s) => s && s.id), [manifest])
  const sector = sectors.find((s) => s.id === sectorId) || null

  const ctx = useMemo(
    () => ({
      groupsById: new Map(asArray(manifest?.groups).filter(Boolean).map((g) => [g.id, g])),
      sourcesById: new Map(asArray(manifest?.sources).filter(Boolean).map((s) => [s.id, s])),
      sectorLabels: new Map(sectors.map((s) => [s.id, s.label_en || s.id])),
    }),
    [manifest, sectors],
  )
  const areaLabels = useMemo(
    () => new Map(asArray(manifest?.areas).filter(Boolean).map((a) => [a.id, a.label || a.id])),
    [manifest],
  )
  const totalBytes = useMemo(
    () => sectors.reduce((sum, s) => sum + asArray(s.chunks).reduce((a, c) => a + (Number(c?.bytes) || 0), 0), 0),
    [sectors],
  )
  const totalChunks = useMemo(() => sectors.reduce((sum, s) => sum + asArray(s.chunks).length, 0), [sectors])

  // Load the chosen sector's chunks one after another, with progress.
  useEffect(() => {
    if (!sector || cache[sector.id]) return undefined
    let live = true
    const ctrl = new AbortController()
    const chunks = asArray(sector.chunks).filter((c) => c && c.path)
    setLoad({ id: sector.id, done: 0, total: chunks.length, error: '' })
    ;(async () => {
      const all = []
      try {
        for (let i = 0; i < chunks.length; i++) {
          const recs = await loadChunk(chunks[i], ctrl.signal)
          if (!live) return
          for (const r of recs) all.push(r)
          setLoad({ id: sector.id, done: i + 1, total: chunks.length, error: '' })
        }
        if (live) setCache((c) => ({ ...c, [sector.id]: all }))
      } catch (e) {
        if (live && !isAbort(e)) setLoad((l) => ({ ...l, id: sector.id, error: e.message || 'Could not load this sector' }))
      }
    })()
    return () => {
      live = false
      ctrl.abort()
    }
  }, [sector, cache])

  const records = sector ? cache[sector.id] : null

  const indexed = useMemo(() => (records || []).filter((r) => r && typeof r === 'object').map((r) => ({ r, hay: haystack(r) })), [records])

  const kindCounts = useMemo(() => {
    const c = {}
    for (const { r } of indexed) c[r.kind] = (c[r.kind] || 0) + 1
    return c
  }, [indexed])

  const filtered = useMemo(() => {
    const words = fold(deferredQuery).split(/\s+/).filter(Boolean)
    const kindSet = new Set(kinds)
    return indexed.filter(
      (it) => (!kindSet.size || kindSet.has(it.r.kind)) && words.every((w) => it.hay.includes(w)),
    )
  }, [indexed, deferredQuery, kinds])

  // Group by area in file order (already S3 order); records without an area go last.
  const groups = useMemo(() => {
    const order = []
    const byArea = new Map()
    for (const it of filtered) {
      const a = it.r.area || null
      if (!byArea.has(a)) {
        byArea.set(a, [])
        if (a !== null) order.push(a)
      }
      byArea.get(a).push(it)
    }
    if (byArea.has(null)) order.push(null)
    return order.map((a) => ({ area: a, items: byArea.get(a) }))
  }, [filtered])

  const filterKey = `${sectorId}|${deferredQuery}|${kinds.join(',')}`
  const limit = shown.key === filterKey ? shown.n : PAGE
  const visibleGroups = useMemo(() => {
    let left = limit
    const out = []
    for (const g of groups) {
      if (left <= 0) break
      out.push({ ...g, shownItems: g.items.slice(0, left) })
      left -= g.items.length
    }
    return out
  }, [groups, limit])

  function chooseSector(id) {
    const next = new URLSearchParams(params)
    if (id) next.set('sector', id)
    else next.delete('sector')
    setParams(next)
    setKinds([])
    requestAnimationFrame(() => headingRef.current?.focus())
  }

  const toggleKind = (k) => setKinds((ks) => (ks.includes(k) ? ks.filter((x) => x !== k) : [...ks, k]))

  function downloadSector(format) {
    if (!manifest || !sector || !records) return
    const b = format === 'csv' ? createCsvBuilder() : createJsonBuilder(wrapperMeta(manifest, sector.id))
    b.add(records)
    saveBlob(b.toBlob(), fileName(manifest, sector.id, format))
    setDl({ busy: false, message: `Saved ${fmt(records.length)} records from ${sector.label_en || sector.id}.` })
  }

  async function downloadAll(format) {
    if (!manifest || dl.busy) return
    const mb = (totalBytes / 1e6).toFixed(1)
    const total = manifest.totals?.records
    const ok = window.confirm(
      `Download the whole catalogue${total ? ` (${fmt(total)} records)` : ''}? ` +
        `Your browser will fetch ${mb} MB of compressed data and build the file itself; it is several times larger once unpacked.`,
    )
    if (!ok) return
    const b = format === 'csv' ? createCsvBuilder() : createJsonBuilder(wrapperMeta(manifest, null))
    let done = 0
    let count = 0
    const ctrl = new AbortController()
    dlAbort.current = ctrl
    setDl({ busy: true, message: `Loading 0/${totalChunks}` })
    try {
      for (const s of sectors) {
        const chunks = asArray(s.chunks).filter((c) => c && c.path)
        if (cache[s.id]) {
          b.add(cache[s.id])
          count += cache[s.id].length
          done += chunks.length
          setDl({ busy: true, message: `Loading ${done}/${totalChunks}` })
          continue
        }
        for (const c of chunks) {
          const recs = await loadChunk(c, ctrl.signal)
          b.add(recs)
          count += recs.length
          done += 1
          setDl({ busy: true, message: `Loading ${done}/${totalChunks}` })
        }
      }
      setDl({ busy: true, message: 'Building the file…' })
      saveBlob(b.toBlob(), fileName(manifest, 'all', format))
      setDl({ busy: false, message: `Saved ${fmt(count)} records.` })
    } catch (e) {
      if (isAbort(e)) setDl({ busy: false, message: 'Download cancelled.' })
      else setDl({ busy: false, message: `Download failed: ${e.message || 'unknown error'}` })
    } finally {
      if (dlAbort.current === ctrl) dlAbort.current = null
    }
  }

  function cancelDownload() {
    dlAbort.current?.abort()
  }

  // Leaving the page cancels a running big download.
  useEffect(() => () => dlAbort.current?.abort(), [])

  function copyAttribution() {
    const text = manifest?.attribution || ''
    if (!navigator.clipboard?.writeText) {
      setCopied('Copy is not available here; select the text instead.')
      return
    }
    navigator.clipboard
      .writeText(text)
      .then(() => setCopied('Attribution copied.'))
      .catch(() => setCopied('Copy failed; select the text instead.'))
  }

  const spot = manifest?.spotcheck
  const overall = spot?.overall
  const loadingThis = sector && !records && load.id === sector.id && !load.error
  const loadError = sector && !records && load.id === sector.id ? load.error : ''
  const visibleCount = Math.min(limit, filtered.length)
  const countText = records
    ? `Showing ${fmt(visibleCount)} of ${fmt(filtered.length)}${
        filtered.length !== records.length ? ` matching (${fmt(records.length)} in this sector)` : ''
      }.`
    : ''
  const [announced, setAnnounced] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setAnnounced(countText), 400)
    return () => clearTimeout(t)
  }, [countText])
  const sectorMissing = Boolean(manifest && sectorId && !sector)

  return (
    <div className="nat cat">
      <header className="nat-topbar">
        <Link to="/" className="nat-brand">
          <Logo className="nat-brand__logo" />
          <span>Sylva</span>
        </Link>
        <nav className="nat-nav">
          <Link to="/hardware">Hardware</Link>
          <Link to="/nature">Nature</Link>
        </nav>
      </header>

      <main className="nat-main">
        <h1>Open nature catalogue</h1>
        <p className="nat-lede">
          Bio-inspired designs and nature-based solutions from open sources, sorted into industry sectors by rules,
          not by hand. Every row is machine-sorted and says why it landed in its sector, so check that before relying
          on it.
        </p>

        {error && (
          <p className="nat-state nat-state--error" role="alert">
            {error}
          </p>
        )}
        {!manifest && !error && (
          <p className="nat-state" role="status" aria-live="polite">
            Loading the catalogue…
          </p>
        )}

        {manifest && (
          <>
            <section className="nat-stats" aria-label="Catalogue totals">
              <dl>
                <div>
                  <dt>Records</dt>
                  <dd>{fmt(manifest.totals?.records)}</dd>
                </div>
                <div>
                  <dt>With a summary</dt>
                  <dd>{fmt(manifest.totals?.with_summary)}</dd>
                </div>
                <div>
                  <dt>With an organism</dt>
                  <dd>{fmt(manifest.totals?.with_organism)}</dd>
                </div>
                <div>
                  <dt>With donation links</dt>
                  <dd>{fmt(manifest.totals?.with_group)}</dd>
                </div>
              </dl>
              <p className="nat-licence">
                <span className="nat-badge cat-machine">Machine-sorted</span>{' '}
                <ExternalLink href={safeUrl(manifest.licence_url) || 'https://creativecommons.org/licenses/by/4.0/'}>
                  <span className="nat-badge nat-badge--licence">{manifest.licence || 'CC-BY-4.0'}</span>
                </ExternalLink>{' '}
                <span className="nat-muted">
                  Version {manifest.version || '–'}
                  {asArray(manifest.sources).length > 0 && (
                    <>
                      {' · Sources: '}
                      {asArray(manifest.sources)
                        .filter(Boolean)
                        .map((s, i) => (
                          <span key={s.id || i}>
                            {i > 0 ? ', ' : ''}
                            {safeUrl(s.url) ? <ExternalLink href={safeUrl(s.url)}>{s.name || s.id}</ExternalLink> : s.name || s.id}
                            {s.licence ? ` (${s.licence})` : ''}
                          </span>
                        ))}
                    </>
                  )}
                </span>
              </p>
              <p className="cat-spot">
                {overall && typeof overall.precision === 'number' ? (
                  <>
                    Spot-check: <q>{spot.checked_by}</q> · strict precision <strong>{pct(overall.precision)}</strong>{' '}
                    (n={fmt(overall.n)})
                    {typeof overall.lenient_precision === 'number' && <> · lenient {pct(overall.lenient_precision)}</>}
                  </>
                ) : (
                  'Not yet spot-checked'
                )}
              </p>
              <details className="cat-details cat-accuracy">
                <summary>How accurate is this?</summary>
                <p>
                  <strong>Strict precision</strong> is the share of a random sample whose main sector was judged right.{' '}
                  <strong>Lenient precision</strong> also counts a record as right when the correct sector is one of its
                  extra tags. <em>n</em> is how many records were checked.
                </p>
                <p>
                  The checks were done by independent AI agents on blind samples (each checker saw the record and five
                  shuffled sector options, with the machine&apos;s choice not marked). {!/owner/i.test(spot?.checked_by || '') && <>The owner&apos;s own skim of those samples is still pending. </>}Check label:{' '}
                  <q>{spot?.checked_by || 'not recorded'}</q>.
                </p>
                {asArray(spot?.rounds).length > 0 && (
                  <ul className="cat-list">
                    {asArray(spot.rounds)
                      .filter(Boolean)
                      .map((r, i) => (
                        <li key={r.round ?? i}>
                          Round {r.round ?? i + 1}: strict {pct(r.strict)}, lenient {pct(r.lenient)}
                          {r.note ? ` (${r.note})` : ''}
                        </li>
                      ))}
                  </ul>
                )}
                <p className="nat-muted">
                  Sectors with fewer than 10 checked records are marked <q>low sample</q>: their figure can swing a lot.
                  Sectors under 70% strict are marked <q>low precision</q>.
                </p>
              </details>
              {asArray(manifest.pending).length > 0 && (
                <div className="cat-pending">
                  <p className="nat-muted">Not in this version yet:</p>
                  <ul className="cat-list nat-muted">
                    {asArray(manifest.pending).map((p, i) => (
                      <li key={i}>{String(p)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </section>

            <section aria-labelledby="cat-sectors-h">
              <h2 id="cat-sectors-h" className="cat-h2">
                Sectors
              </h2>
              <ul className="cat-sectors">
                {sectors.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      className={`cat-sector ${s.id === sectorId ? 'is-active' : ''}`}
                      aria-pressed={s.id === sectorId}
                      onClick={() => chooseSector(s.id)}
                    >
                      <span className="cat-sector__name">
                        <SectorLabel sector={s} />
                      </span>
                      <span className="cat-sector__count">{fmt(s.count)} records</span>
                      <PrecisionLine sector={s} />
                      <SectorFlags sector={s} />
                    </button>
                  </li>
                ))}
              </ul>
            </section>

            <section className="nat-panel cat-downloads" aria-labelledby="cat-dl-h">
              <h2 id="cat-dl-h" className="cat-h2">
                Download
              </h2>
              <div className="cat-dl-row">
                <span className="cat-dl-label">This sector:</span>
                {sector && records ? (
                  <>
                    <button type="button" className="nat-chip" onClick={() => downloadSector('json')}>
                      JSON
                    </button>
                    <button type="button" className="nat-chip" onClick={() => downloadSector('csv')}>
                      CSV
                    </button>
                  </>
                ) : (
                  <span className="nat-muted">{sector ? 'loading the sector first…' : 'choose a sector above.'}</span>
                )}
              </div>
              <div className="cat-dl-row">
                <span className="cat-dl-label">Everything:</span>
                <button type="button" className="nat-chip" disabled={dl.busy} onClick={() => downloadAll('json')}>
                  JSON
                </button>
                <button type="button" className="nat-chip" disabled={dl.busy} onClick={() => downloadAll('csv')}>
                  CSV
                </button>
                {dl.busy && (
                  <button type="button" className="nat-chip" onClick={cancelDownload}>
                    Cancel
                  </button>
                )}
                <span className="nat-muted">{(totalBytes / 1e6).toFixed(1)} MB compressed</span>
              </div>
              <p className="nat-muted">
                Large download (~{(totalBytes / 1e6).toFixed(0)} MB compressed, more in memory) – desktop recommended.
              </p>
              <p className="nat-muted" role="status" aria-live="polite">
                {dl.message}
              </p>
              <div className="cat-attr">
                <p>
                  <strong>Attribution:</strong> <span className="cat-attr__text">{manifest.attribution}</span>
                </p>
                <div className="nat-row">
                  <button type="button" className="nat-chip" onClick={copyAttribution}>
                    Copy attribution
                  </button>
                  <span className="nat-muted" aria-live="polite">
                    {copied}
                  </span>
                </div>
                {manifest.download_note && <p className="nat-muted">{manifest.download_note}</p>}
              </div>
            </section>

            {sectorMissing && (
              <p className="nat-state" role="status">
                Sector not found.{' '}
                <Link to="/catalogue" onClick={() => setKinds([])}>
                  Back to the sector list
                </Link>
              </p>
            )}

            {sector && (
              <section className="cat-view" aria-labelledby="cat-view-h">
                <h2 id="cat-view-h" className="cat-h2" tabIndex={-1} ref={headingRef}>
                  <SectorLabel sector={sector} />
                </h2>
                {sector.description && <p className="nat-lede">{sector.description}</p>}
                <p className="nat-row">
                  <PrecisionLine sector={sector} />
                  <SectorFlags sector={sector} />
                </p>
                {sector.precision_warning && (
                  <p className="nat-note">
                    Low precision: in the spot-check, fewer than 70% of sampled records here had the right main sector.
                    Open <q>Why this sector?</q> before relying on a row.
                  </p>
                )}
                {sector.low_sample && (
                  <p className="nat-note">
                    Low sample: only {fmt(sector.n)} records from this sector were checked, so the figure is rough.
                  </p>
                )}

                <p className="nat-state" role="status" aria-live="polite">
                  {loadingThis ? `Loading ${load.done}/${load.total}` : ''}
                </p>
                {loadError && (
                  <p className="nat-state nat-state--error" role="alert">
                    {loadError}
                  </p>
                )}

                {records && (
                  <>
                    <div className="nat-panel cat-filters">
                      <div className="nat-field">
                        <label htmlFor="cat-q">Filter by title, organism or organisation</label>
                        <input id="cat-q" type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
                      </div>
                      <div className="nat-row" role="group" aria-label="Kind">
                        {KINDS.map(([k, label]) => (
                          <button
                            key={k}
                            type="button"
                            className={`nat-chip ${kinds.includes(k) ? 'is-active' : ''}`}
                            aria-pressed={kinds.includes(k)}
                            onClick={() => toggleKind(k)}
                          >
                            {label} ({fmt(kindCounts[k] || 0)})
                          </button>
                        ))}
                      </div>
                    </div>
                    <p className="nat-muted">{countText}</p>
                    <p className="cat-sr-only" role="status" aria-live="polite">
                      {announced}
                    </p>
                    {filtered.length === 0 && <p className="nat-state">No records match this filter.</p>}
                    {visibleGroups.map((g) => (
                      <section key={g.area ?? '__none'} className="cat-group" aria-label={areaLabels.get(g.area) || g.area || 'Other / unclassified'}>
                        <h3>
                          {g.area ? areaLabels.get(g.area) || g.area : 'Other / unclassified'}{' '}
                          <span className="nat-muted">({fmt(g.items.length)})</span>
                        </h3>
                        <ul className="cat-records">
                          {g.shownItems.map((it, i) => (
                            <Row key={it.r.id || `${g.area}-${i}`} r={it.r} ctx={ctx} />
                          ))}
                        </ul>
                      </section>
                    ))}
                    {visibleCount < filtered.length && (
                      <button type="button" className="nat-btn cat-more" onClick={() => setShown({ key: filterKey, n: limit + PAGE })}>
                        Show 100 more
                      </button>
                    )}
                  </>
                )}
              </section>
            )}

            <section className="nat-panel cat-more-dirs" aria-labelledby="cat-dirs-h">
              <h2 id="cat-dirs-h" className="cat-h2">
                More directories
              </h2>
              <p className="nat-muted">
                Useful collections we link to but do not copy, because their licence or access terms do not allow an
                open CC BY 4.0 catalogue.
              </p>
              <ul className="cat-dirs">
                {MORE_DIRECTORIES.map((d) => (
                  <li key={d.name}>
                    <ExternalLink href={d.url}>{d.name}</ExternalLink>
                    <span className="nat-muted"> – {d.why}</span>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </main>
    </div>
  )
}
