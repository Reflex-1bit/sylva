const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

export async function geocode(query) {
  const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(query)}`
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
  })
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

  const res = await fetch(`${API_BASE}/farm/recommendations?${params}`)
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
