const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
// Security: never put GEMINI_API_KEY / OPENTOPO / tokens in VITE_* vars.
// Those are embedded in the public JS bundle. Secrets belong on the server only.

const GEOCODE_TIMEOUT_MS = 12_000
const RECOMMEND_TIMEOUT_MS = 70_000

async function fetchWithTimeout(url, options = {}, timeoutMs = 30_000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } catch (e) {
    if (e?.name === 'AbortError') {
      throw new Error('Request timed out — the server took too long. Try again.')
    }
    throw e
  } finally {
    clearTimeout(timer)
  }
}

export async function geocode(query) {
  const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(query)}`
  const res = await fetchWithTimeout(
    url,
    {
      headers: {
        Accept: 'application/json',
      },
    },
    GEOCODE_TIMEOUT_MS,
  )
  if (!res.ok) throw new Error('Geocoding failed')
  const data = await res.json()
  if (!data.length) throw new Error('Location not found — try a town or coordinates')
  const parts = (data[0].display_name || '').split(',').map((s) => s.trim()).filter(Boolean)
  return {
    lat: parseFloat(data[0].lat),
    lon: parseFloat(data[0].lon),
    label: parts.slice(0, 3).join(', '),
    country: parts.at(-1) || null,
  }
}

export async function fetchRecommendations({ lat, lon, country, topN = 10 }) {
  const params = new URLSearchParams({
    lat: String(lat),
    lon: String(lon),
    radius_km: '5',
    top_n: String(topN),
  })
  if (country) params.set('country', country)

  const res = await fetchWithTimeout(
    `${API_BASE}/farm/recommendations?${params}`,
    {},
    RECOMMEND_TIMEOUT_MS,
  )
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json()
}
