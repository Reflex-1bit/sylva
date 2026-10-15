"""Check the donate_url and source_url of every group in groups.json. A report only: exit 0 always.

For each URL: HEAD, falling back to GET on 403/405 (and on other 4xx/5xx a HEAD can get wrongly).
Redirects are followed, 1 request per second, 20 s timeout, User-Agent SylvaNatureCatalogue/0.1.
No credentials, no contact address, no platform API: plain requests to the groups' public pages.
Bot-protection answers (403, 429, 503 with a challenge) are listed as "blocked", not as dead links.

Usage (from repo root):
    python scripts/nature/catalogue/check_links.py [--data-dir PATH] [--out PATH]
Writes build/stage/links.json and prints a table.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import BUILD_DIR, CATALOGUE_DIR, load_groups  # noqa: E402

USER_AGENT = "SylvaNatureCatalogue/0.1"
TIMEOUT = 20
DELAY = 1.0
BLOCKED_STATUSES = {401, 403, 429, 451, 503}

# (status, final_url, error)
Fetcher = Callable[[str, str], tuple[Optional[int], Optional[str], Optional[str]]]


def fetch(url: str, method: str) -> tuple[Optional[int], Optional[str], Optional[str]]:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.geturl(), None
    except urllib.error.HTTPError as exc:
        return exc.code, exc.geturl() if hasattr(exc, "geturl") else url, None
    except Exception as exc:  # DNS, TLS, timeout, reset
        return None, None, f"{type(exc).__name__}: {exc}"[:200]


def classify(status: Optional[int], error: Optional[str]) -> str:
    if error or status is None:
        return "error"
    if 200 <= status < 400:
        return "ok"
    if status in BLOCKED_STATUSES:
        return "blocked"
    return "dead"


def check_url(url: str, fetcher: Fetcher = fetch, sleep: Callable[[float], None] = time.sleep) -> dict:
    status, final, error = fetcher(url, "HEAD")
    method = "HEAD"
    if status is not None and status >= 400:  # many sites refuse HEAD (403/405) or mishandle it
        sleep(DELAY)
        status, final, error = fetcher(url, "GET")
        method = "GET"
    return {"url": url, "method": method, "status": status, "final_url": final, "error": error,
            "result": classify(status, error), "redirected": bool(final and final != url)}


def run(groups, fetcher: Fetcher = fetch, sleep: Callable[[float], None] = time.sleep, log=print) -> dict:
    rows = []
    first = True
    for g in groups:
        for field in ("donate_url", "source_url"):
            if not first:
                sleep(DELAY)
            first = False
            row = {"group": g.id, "field": field, **check_url(getattr(g, field), fetcher, sleep)}
            rows.append(row)
            log(f"{row['result']:8} {str(row['status'] or '-'):>4} {row['method']:4} {g.id:34} {field}")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    return {"checked": len(rows), "summary": counts, "results": rows}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=CATALOGUE_DIR)
    parser.add_argument("--out", type=Path, default=BUILD_DIR / "stage" / "links.json")
    args = parser.parse_args(argv)
    groups = load_groups(args.data_dir).groups
    print(f"{'result':8} {'code':>4} {'via':4} {'group':34} url")
    report = run(groups)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"\nchecked {report['checked']} urls: {report['summary']}")
    print("blocked = bot protection (403/429/503), not edited automatically; dead = 404/410/5xx; error = no answer")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
