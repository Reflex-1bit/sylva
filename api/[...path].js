/**
 * Tiny Edge proxy — forwards /api/* (and /api/health → /health) to Sylva FastAPI.
 *
 * Secrets stay on the upstream host only. Set in Vercel:
 *   API_UPSTREAM_URL=https://your-sylva.onrender.com
 */
export const config = {
  runtime: 'edge',
}

function upstreamPath(pathname) {
  if (pathname === '/api/health') return '/health'
  return pathname
}

export default async function handler(request) {
  const base = (process.env.API_UPSTREAM_URL || '').replace(/\/$/, '')
  if (!base) {
    return new Response(
      JSON.stringify({
        detail:
          'API_UPSTREAM_URL is not set. Point it at your Sylva FastAPI host (e.g. https://your-app.onrender.com).',
      }),
      {
        status: 502,
        headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
      },
    )
  }

  const incoming = new URL(request.url)
  const target = `${base}${upstreamPath(incoming.pathname)}${incoming.search}`

  const headers = new Headers(request.headers)
  headers.delete('host')
  headers.delete('connection')

  const init = {
    method: request.method,
    headers,
    redirect: 'manual',
  }

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = request.body
    init.duplex = 'half'
  }

  try {
    const upstream = await fetch(target, init)
    const outHeaders = new Headers(upstream.headers)
    outHeaders.set('cache-control', 'no-store')
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: outHeaders,
    })
  } catch (err) {
    return new Response(
      JSON.stringify({
        detail: 'Upstream API unreachable',
        error: String(err?.message || err),
      }),
      {
        status: 502,
        headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
      },
    )
  }
}
