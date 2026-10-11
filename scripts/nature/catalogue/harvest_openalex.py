"""
Open Nature Catalogue - OpenAlex harvester (keyless-friendly, resumable).

Subcommands:
  discover   find OpenAlex keywords for the scope terms -> openalex_terms.json
  harvest    page works per included keyword into an on-disk cache (resumes from state.json)
  normalise  rebuild RawRecord jsonl from the cache (offline)
  status     keywords done/pending, cached pages, remaining budget

Budget (measured 2026-10-11, keyless): 1000 credits/day; a plain filter list call
costs 1 credit, a *.search filter list call costs 10. The harvester stops before
X-RateLimit-Remaining drops under a reserve and exits 3 on HTTP 429 with state saved.
Set OPENALEX_API_KEY to raise the budget. No contact address is ever sent.

Filtering by keyword uses the documented `keywords.id` works filter
(https://docs.openalex.org/api-entities/works/filter-works).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import RAW_DIR, openalex_licence, today, write_jsonl  # noqa: E402

from app.models.catalogue import RawRecord  # noqa: E402
from app.models.nature import is_open_licence  # noqa: E402

HERE = Path(__file__).resolve().parent
SCOPE_TERMS_PATH = HERE / "scope_terms.json"
TERMS_PATH = HERE / "openalex_terms.json"
OA_DIR = RAW_DIR / "openalex"
PAGES_DIR = OA_DIR / "pages"
DISCOVER_DIR = OA_DIR / "discover"
STATE_PATH = OA_DIR / "state.json"
RECORDS_PATH = OA_DIR / "records.jsonl"

API = "https://api.openalex.org"
SELECT = (
    "id,doi,title,publication_year,type,language,primary_topic,topics,keywords,"
    "best_oa_location,primary_location,abstract_inverted_index,authorships"
)
KEEP_TYPES = {"article", "review", "book-chapter", "preprint", "dissertation"}
DEFAULT_RESERVE = 20
EXIT_BUDGET = 3

# fetch(url, params) -> (json | None, headers dict). Injected in tests.
Fetch = Callable[[str, Optional[dict]], tuple]


class RateLimited(Exception):
    def __init__(self, reset: Optional[int]):
        super().__init__(f"HTTP 429 (reset in {reset} s)")
        self.reset = reset


class BudgetStop(Exception):
    """Reserve reached or --max-calls spent; state is saved and a rerun resumes."""


# ── HTTP ──────────────────────────────────────────────────────────────────────


def http_fetch(url: str, params: Optional[dict] = None) -> tuple:
    """GET JSON plus response headers. Retries timeouts and 5xx (as scripts/nature/_http.py);
    429 raises RateLimited immediately (no sleeping on the daily budget)."""
    import httpx

    attempts = 3
    for attempt in range(attempts):
        last = attempt == attempts - 1
        wait = 2.0**attempt
        try:
            resp = httpx.get(url, params=params, timeout=60.0, follow_redirects=True)
        except httpx.TransportError:
            if last:
                raise
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return None, dict(resp.headers)
        if resp.status_code == 429:
            reset = resp.headers.get("X-RateLimit-Reset", "")
            raise RateLimited(int(reset) if reset.isdigit() else None)
        if resp.status_code >= 500:
            if last:
                resp.raise_for_status()
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json(), dict(resp.headers)
    return None, {}  # unreachable


def cache_key(url: str, params: Optional[dict]) -> str:
    """Stable cache key; api_key is excluded so a keyed rerun hits the keyless cache."""
    key_params = {k: v for k, v in (params or {}).items() if k != "api_key"}
    return hashlib.sha1(json.dumps([url, key_params], sort_keys=True).encode()).hexdigest()


class Client:
    """Cached, budget-aware OpenAlex client."""

    def __init__(
        self,
        cache_dir: Path,
        fetch: Fetch = http_fetch,
        api_key: Optional[str] = None,
        reserve: int = DEFAULT_RESERVE,
        max_calls: Optional[int] = None,
    ):
        self.cache_dir = cache_dir
        self.fetch = fetch
        self.api_key = api_key
        self.reserve = reserve
        self.max_calls = max_calls
        self.calls = 0
        self.credits_used = 0
        self.remaining: Optional[int] = None
        self.reset: Optional[int] = None

    def get(self, url: str, params: Optional[dict] = None, cost: int = 1) -> tuple:
        """Return (data, key, from_cache). Raises BudgetStop / RateLimited."""
        key = cache_key(url, params)
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")), key, True
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise BudgetStop(f"--max-calls {self.max_calls} reached")
        if self.remaining is not None and self.remaining - cost < self.reserve:
            raise BudgetStop(f"budget reserve reached ({self.remaining} credits left, reserve {self.reserve})")
        send = dict(params or {})
        if self.api_key:
            send["api_key"] = self.api_key
        data, headers = self.fetch(url, send)
        self.calls += 1
        h = {k.lower(): v for k, v in (headers or {}).items()}
        if h.get("x-ratelimit-remaining", "").isdigit():
            new = int(h["x-ratelimit-remaining"])
            if self.remaining is not None:
                self.credits_used += max(0, self.remaining - new)
            elif h.get("x-ratelimit-credits-used", "").isdigit():
                self.credits_used += int(h["x-ratelimit-credits-used"])
            self.remaining = new
        if h.get("x-ratelimit-reset", "").isdigit():
            self.reset = int(h["x-ratelimit-reset"])
        if data is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data, key, False


# ── Scope terms and discovery ─────────────────────────────────────────────────


def load_scope_terms(path: Path = SCOPE_TERMS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# Close variants of the scope terms that the plain stem match would miss.
EXTRA_STEMS = [
    "sustainable urban drainage",
    "green stormwater infrastructure",
    "floating treatment wetland",
    "biologically inspired",
    "mussel-inspired",
    "nacre-inspired",
]


def _squash(text: str) -> str:
    return re.sub(r"[\s\-]+", "", text.lower())


def decide_include(display_name: str, terms: list[str]) -> tuple[bool, str]:
    """Include a keyword when its name contains a scope-term stem (hyphens/spaces ignored)."""
    name = _squash(display_name)
    for term in list(terms) + EXTRA_STEMS:
        if _squash(term) in name:
            return True, f"name contains scope term '{term}'"
    return False, "no scope term in the name (generic or off-topic keyword)"


def discover(client: Client, scope: dict, max_pages: int = 6) -> list[dict]:
    all_terms = scope["biomimicry"] + scope["nbs"]
    found: dict[str, dict] = {}
    for term in all_terms:
        for page in range(1, max_pages + 1):
            params = {
                "search": term,
                "per_page": 50,
                "page": page,
                "select": "id,display_name,works_count",
            }
            data, _, _ = client.get(f"{API}/keywords", params)
            results = (data or {}).get("results", [])
            for r in results:
                found.setdefault(r["id"], r)
            if len(results) < 50:
                break
    out = []
    for kid, r in sorted(found.items(), key=lambda kv: kv[1].get("works_count", 0)):
        include, reason = decide_include(r["display_name"], all_terms)
        out.append(
            {
                "id": kid,
                "display_name": r["display_name"],
                "works_count": r.get("works_count", 0),
                "include": include,
                "reason": reason,
            }
        )
    return out


def short_id(openalex_url: str) -> str:
    return openalex_url.rstrip("/").rsplit("/", 1)[-1]


# ── State ─────────────────────────────────────────────────────────────────────


def load_state(path: Path = STATE_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"jobs": {}, "pages": {}, "rate": {}}


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def keyword_job(kw: dict) -> dict:
    kid = short_id(kw["id"])
    return {
        "id": f"kw:{kid}",
        "filter": f"keywords.id:{kid},is_retracted:false",
        "cost": 1,
        "label": kw["display_name"],
    }


def search_job(term: str) -> dict:
    return {
        "id": f"search:{term}",
        "filter": f'title_and_abstract.search:"{term}",is_retracted:false',
        "cost": 10,
        "label": f"search {term}",
    }


def harvest_job(client: Client, job: dict, state: dict, state_path: Path, per_page: int = 200) -> None:
    entry = state["jobs"].setdefault(
        job["id"], {"status": "pending", "next_cursor": "*", "pages": 0, "works": 0, "label": job["label"]}
    )
    while entry["status"] != "done":
        params = {
            "filter": job["filter"],
            "per_page": per_page,
            "cursor": entry["next_cursor"],
            "select": SELECT,
        }
        data, key, from_cache = client.get(f"{API}/works", params, cost=job["cost"])
        results = (data or {}).get("results", [])
        nxt = ((data or {}).get("meta") or {}).get("next_cursor")
        if not from_cache:
            state["pages"][key] = today()
        entry["pages"] += 1
        entry["works"] += len(results)
        if results and nxt:
            entry["next_cursor"] = nxt
        else:
            entry["status"] = "done"
            entry["next_cursor"] = None
            entry["finished_on"] = today()
        state["rate"] = {"remaining": client.remaining, "reset": client.reset, "seen_on": today()}
        save_state(state, state_path)


def job_order(keywords: list[dict], bio_terms: list[str]) -> list[dict]:
    """Biomimicry keywords first, then nature-based-solution ones; biggest first within each
    group so a budget-limited run covers the broad core sets before the long tail."""
    stems = [_squash(t) for t in bio_terms + EXTRA_STEMS[3:]]

    def bio(k: dict) -> bool:
        return any(t in _squash(k["display_name"]) for t in stems)

    return sorted((k for k in keywords if k["include"]), key=lambda k: (not bio(k), -k["works_count"]))


def run_harvest(
    client: Client,
    keywords: list[dict],
    state_path: Path = STATE_PATH,
    search_terms: Optional[list[str]] = None,
    bio_terms: Optional[list[str]] = None,
) -> int:
    """Returns 0 (done or paused on reserve/max-calls) or EXIT_BUDGET (HTTP 429)."""
    state = load_state(state_path)
    bio_terms = bio_terms if bio_terms is not None else load_scope_terms()["biomimicry"]
    jobs = [keyword_job(k) for k in job_order(keywords, bio_terms)]
    jobs += [search_job(t) for t in (search_terms or [])]
    try:
        for job in jobs:
            if state["jobs"].get(job["id"], {}).get("status") == "done":
                continue
            harvest_job(client, job, state, state_path)
    except RateLimited as exc:
        save_state(state, state_path)
        print(
            f"OpenAlex daily budget used; rerun after {exc.reset} s or set OPENALEX_API_KEY",
            file=sys.stderr,
        )
        return EXIT_BUDGET
    except BudgetStop as exc:
        save_state(state, state_path)
        print(f"Paused: {exc}. Rerun harvest to resume.")
        return 0
    save_state(state, state_path)
    print("Harvest complete for all selected jobs.")
    return 0


# ── Normalise ─────────────────────────────────────────────────────────────────


def rebuild_abstract(inverted: Optional[dict]) -> Optional[str]:
    if not inverted:
        return None
    slots: dict[int, str] = {}
    for word, positions in inverted.items():
        for p in positions:
            slots[p] = word
    text = " ".join(slots[i] for i in sorted(slots)).strip()
    return text or None


def _bare_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
    return d if d.startswith("10.") and not re.search(r"\s", d) else None


def _uniq(items) -> list:
    seen, out = set(), []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def work_to_record(work: dict, harvested_on: str) -> Optional[RawRecord]:
    if work.get("type") not in KEEP_TYPES:
        return None
    title = (work.get("title") or "").strip()
    wid = short_id(work.get("id") or "")
    if not title or not re.fullmatch(r"W\d+", wid):
        return None
    doi = _bare_doi(work.get("doi"))
    landing = ((work.get("primary_location") or {}).get("landing_page_url") or "").strip()
    if doi:
        url = f"https://doi.org/{doi}"
    elif landing.startswith("https://") and not re.search(r"\s", landing):
        url = landing
    else:
        url = f"https://openalex.org/{wid}"

    summary = summary_licence = None
    lic = openalex_licence((work.get("best_oa_location") or {}).get("license"))
    if is_open_licence(lic):
        summary = rebuild_abstract(work.get("abstract_inverted_index"))
        if summary:
            summary_licence = lic

    insts = [i for a in work.get("authorships") or [] for i in a.get("institutions") or []]
    countries = _uniq(
        i["country_code"].upper() for i in insts if re.fullmatch(r"[A-Za-z]{2}", i.get("country_code") or "")
    )
    orgs = _uniq((i.get("display_name") or "").strip() for i in insts)[:10]

    topics = ([work["primary_topic"]] if work.get("primary_topic") else []) + list(work.get("topics") or [])
    subfields = _uniq((t.get("subfield") or {}).get("display_name") for t in topics)
    topic_names = _uniq(t.get("display_name") for t in topics)
    keywords = _uniq(k.get("display_name") for k in work.get("keywords") or [])

    year = work.get("publication_year")
    return RawRecord(
        id=f"oa-{wid}",
        source="openalex",
        source_id=wid,
        kind="paper",
        title=title,
        summary=summary,
        summary_licence=summary_licence,
        source_licence="CC0-1.0",
        url=url,
        doi=doi,
        year=year if isinstance(year, int) and 1500 <= year <= 2100 else None,
        countries=countries,
        organisations=orgs,
        source_codes={"openalex_subfields": subfields, "openalex_topics": topic_names},
        keywords=keywords,
        harvested_on=harvested_on,
    )


def normalise(
    pages_dir: Path = PAGES_DIR, state_path: Path = STATE_PATH, out_path: Path = RECORDS_PATH
) -> dict:
    state = load_state(state_path)
    seen: dict[str, RawRecord] = {}
    skipped = {"type": 0, "invalid": 0, "duplicate": 0}
    for page in sorted(pages_dir.glob("*.json")) if pages_dir.exists() else []:
        harvested_on = state["pages"].get(page.stem, today())
        data = json.loads(page.read_text(encoding="utf-8"))
        for work in data.get("results", []):
            if work.get("type") not in KEEP_TYPES:
                skipped["type"] += 1
                continue
            try:
                rec = work_to_record(work, harvested_on)
            except ValueError:
                rec = None
            if rec is None:
                skipped["invalid"] += 1
            elif rec.id in seen:
                skipped["duplicate"] += 1
            else:
                seen[rec.id] = rec
    written = write_jsonl(out_path, seen.values())
    with_summary = sum(1 for r in seen.values() if r.summary)
    sub: dict[str, int] = {}
    for r in seen.values():
        for s in r.source_codes.openalex_subfields:
            sub[s] = sub.get(s, 0) + 1
    return {
        "written": written,
        "with_summary": with_summary,
        "skipped": skipped,
        "top_subfields": sorted(sub.items(), key=lambda kv: -kv[1])[:15],
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def load_terms_file() -> dict:
    return json.loads(TERMS_PATH.read_text(encoding="utf-8"))


def status() -> None:
    state = load_state()
    jobs = state["jobs"]
    included = []
    if TERMS_PATH.exists():
        included = [k for k in load_terms_file()["keywords"] if k["include"]]
    done = sum(1 for j in jobs.values() if j["status"] == "done")
    pending = max(len(included) - done, 0)
    pages = len(list(PAGES_DIR.glob("*.json"))) if PAGES_DIR.exists() else 0
    print(f"keyword jobs: {len(included)} included, {done} done, {pending} pending ({len(jobs)} started)")
    print(f"cached work pages: {pages}")
    rate = state.get("rate") or {}
    print(
        f"remaining budget at last call: {rate.get('remaining')} "
        f"(reset in {rate.get('reset')} s, seen {rate.get('seen_on')})"
    )
    for _, j in sorted(jobs.items()):
        print(f"  {j['status']:7} {j['works']:7} works {j['pages']:4} pages  {j.get('label')}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Open Nature Catalogue OpenAlex harvester")
    ap.add_argument("command", choices=["discover", "harvest", "normalise", "status"])
    ap.add_argument("--max-calls", type=int, default=None, help="stop after N network calls")
    ap.add_argument("--reserve", type=int, default=DEFAULT_RESERVE, help="credits to keep unspent")
    ap.add_argument(
        "--search-terms", action="store_true", help="also run the title_and_abstract.search pass (10 credits/page)"
    )
    args = ap.parse_args(argv)

    api_key = os.environ.get("OPENALEX_API_KEY") or None
    if args.command == "status":
        status()
        return 0
    if args.command == "normalise":
        print(json.dumps(normalise(), indent=1))
        return 0
    if args.command == "discover":
        client = Client(DISCOVER_DIR, api_key=api_key, reserve=args.reserve, max_calls=args.max_calls)
        try:
            kws = discover(client, load_scope_terms())
        except RateLimited as exc:
            print(f"OpenAlex daily budget used; rerun after {exc.reset} s or set OPENALEX_API_KEY", file=sys.stderr)
            return EXIT_BUDGET
        except BudgetStop as exc:
            print(f"Paused: {exc}. Rerun discover to resume (pages are cached).")
            return 0
        TERMS_PATH.write_text(
            json.dumps({"generated_on": today(), "keywords": kws}, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        inc = [k for k in kws if k["include"]]
        print(f"{len(kws)} keywords found, {len(inc)} included, credits used {client.credits_used}")
        return 0
    client = Client(PAGES_DIR, api_key=api_key, reserve=args.reserve, max_calls=args.max_calls)
    kws = load_terms_file()["keywords"]
    terms = load_scope_terms()["biomimicry"] if args.search_terms else None
    code = run_harvest(client, kws, search_terms=terms)
    print(f"network calls {client.calls}, credits used {client.credits_used}, remaining {client.remaining}")
    return code


if __name__ == "__main__":
    sys.exit(main())
