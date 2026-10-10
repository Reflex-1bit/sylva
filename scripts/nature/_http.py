"""Shared HTTP helper for the nature scripts."""

import time


def fetch_json(url: str, params: dict | None = None) -> dict | None:
    """GET a JSON document; None on 404.

    Retries timeouts, 429 (honouring Retry-After) and 5xx up to 3 attempts with
    exponential backoff; raises after the last attempt.
    """
    import httpx

    attempts = 3
    for attempt in range(attempts):
        last = attempt == attempts - 1
        wait = 2.0**attempt
        try:
            resp = httpx.get(url, params=params, timeout=20.0, follow_redirects=True)
        except httpx.TransportError:
            if last:
                raise
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            if last:
                resp.raise_for_status()
            retry_after = resp.headers.get("Retry-After", "")
            time.sleep(min(float(retry_after), 30.0) if retry_after.isdigit() else wait)
            continue
        resp.raise_for_status()
        return resp.json()
    return None  # unreachable
