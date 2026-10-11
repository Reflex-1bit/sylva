"""
Open Nature Catalogue - Climate-ADAPT case-study harvester.

Subcommands:
  harvest    list case studies from the sitemaps, fetch each JSON page (cached, 1 request/second)
  normalise  rebuild raw/climate_adapt/records.jsonl from the cached pages (offline)
  status     pages cached, records written

Source: https://climate-adapt.eea.europa.eu (EEA, CC BY unless an item says otherwise).
Listing: sitemap-index.xml -> gzipped sitemaps -> /en/metadata/case-studies/<slug>.
Detail: GET /++api++/en/metadata/case-studies/<slug> with Accept: application/json.
robots.txt is read first and every URL is checked against it. Images are never fetched.
No contact address is ever sent (User-Agent is the project name only).
"""

import argparse
import gzip
import html
import json
import re
import sys
import time
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import RAW_DIR, today, write_jsonl  # noqa: E402
from scope import ScopeMatcher, cut_summary, fold, load_scope_terms  # noqa: E402
from scrub import scrub_contacts  # noqa: E402

from app.models.catalogue import RawRecord, SourceCodes  # noqa: E402

CA_DIR = RAW_DIR / "climate_adapt"
PAGES_DIR = CA_DIR / "pages"
RECORDS_PATH = CA_DIR / "records.jsonl"
URLS_PATH = CA_DIR / "case_study_urls.txt"

HOST = "https://climate-adapt.eea.europa.eu"
SITEMAP_INDEX = HOST + "/sitemap-index.xml"
ROBOTS_URL = HOST + "/robots.txt"
CASE_RE = re.compile(r"^https://climate-adapt\.eea\.europa\.eu/en/metadata/case-studies/([A-Za-z0-9][A-Za-z0-9-]*)/?$")
USER_AGENT = "SylvaNatureCatalogue/0.1"
PACE_SECONDS = 1.0
LICENCE = "CC-BY-4.0"

# Ecological / green option signals beyond scope_terms.json (matched on adaptation-option titles).
ECO_OPTION_TERMS = ["ecosystem", "ecological", "green", "wetland", "nature-based", "natural flood", "natural water retention"]
# Climate-ADAPT "elements" tokens that mark nature-based content.
ECO_ELEMENT_TOKENS = {"NATUREBASEDSOL"}

COUNTRIES = {
    "Austria": "AT", "Belgium": "BE", "Bulgaria": "BG", "Croatia": "HR", "Cyprus": "CY", "Czechia": "CZ",
    "Czech Republic": "CZ", "Denmark": "DK", "Estonia": "EE", "Finland": "FI", "France": "FR", "Germany": "DE",
    "Greece": "GR", "Hungary": "HU", "Ireland": "IE", "Italy": "IT", "Latvia": "LV", "Lithuania": "LT",
    "Luxembourg": "LU", "Malta": "MT", "Netherlands": "NL", "Poland": "PL", "Portugal": "PT", "Romania": "RO",
    "Slovakia": "SK", "Slovenia": "SI", "Spain": "ES", "Sweden": "SE", "Iceland": "IS", "Liechtenstein": "LI",
    "Norway": "NO", "Switzerland": "CH", "Turkey": "TR", "Türkiye": "TR", "United Kingdom": "GB",
    "Albania": "AL", "Bosnia and Herzegovina": "BA", "Kosovo": "XK", "Montenegro": "ME",
    "North Macedonia": "MK", "Serbia": "RS", "Ukraine": "UA", "Moldova": "MD",
}
_COUNTRIES_FOLDED = {fold(k): v for k, v in COUNTRIES.items()}

Fetch = Callable[[str, dict], Optional[bytes]]  # (url, headers) -> body bytes, None on 404


# ── HTTP (paced, retrying like scripts/nature/_http.py) ───────────────────────


class Client:
    def __init__(self, fetch: Optional[Fetch] = None, pace: float = PACE_SECONDS,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.fetch = fetch or self._http
        self.pace = pace
        self.sleep = sleep
        self.clock = clock
        self._last: Optional[float] = None
        self.requests = 0
        self.robots: Optional[urllib.robotparser.RobotFileParser] = None

    @staticmethod
    def _http(url: str, headers: dict) -> Optional[bytes]:
        import httpx

        attempts = 3
        for attempt in range(attempts):
            last = attempt == attempts - 1
            wait = 2.0**attempt
            try:
                resp = httpx.get(url, headers=headers, timeout=30.0, follow_redirects=True)
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
                ra = resp.headers.get("Retry-After", "")
                time.sleep(min(float(ra), 30.0) if ra.isdigit() else wait)
                continue
            resp.raise_for_status()
            return resp.content
        return None

    def get(self, url: str, accept: Optional[str] = None) -> Optional[bytes]:
        if self._last is not None:
            gap = self.pace - (self.clock() - self._last)
            if gap > 0:
                self.sleep(gap)
        headers = {"User-Agent": USER_AGENT}
        if accept:
            headers["Accept"] = accept
        try:
            return self.fetch(url, headers)
        finally:
            self._last = self.clock()
            self.requests += 1

    def load_robots(self) -> None:
        body = self.get(ROBOTS_URL) or b""
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.decode("utf-8", errors="replace").splitlines())
        self.robots = rp

    def allowed(self, url: str) -> bool:
        if self.robots is None:
            self.load_robots()
        return self.robots.can_fetch(USER_AGENT, url)


# ── listing ───────────────────────────────────────────────────────────────────


def _locs(xml_bytes: bytes) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_bytes.decode("utf-8", errors="replace"))


def _maybe_gunzip(data: bytes) -> bytes:
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def list_case_studies(client: Client) -> list[str]:
    """Slugs of the English case studies in the sitemaps, sorted."""
    index = client.get(SITEMAP_INDEX)
    if not index:
        raise RuntimeError("sitemap-index.xml not available")
    slugs: set[str] = set()
    for sm in _locs(index):
        if not client.allowed(sm):
            continue
        body = client.get(sm)
        if body is None:
            continue
        for loc in _locs(_maybe_gunzip(body)):
            m = CASE_RE.match(loc)
            if m:
                slugs.add(m.group(1))
    return sorted(slugs)


def page_url(slug: str) -> str:
    return f"{HOST}/en/metadata/case-studies/{slug}"


def api_url(slug: str) -> str:
    return f"{HOST}/++api++/en/metadata/case-studies/{slug}"


def harvest(client: Optional[Client] = None, pages_dir: Path = PAGES_DIR, urls_path: Path = URLS_PATH,
            limit: Optional[int] = None) -> dict:
    client = client or Client()
    client.load_robots()
    slugs = list_case_studies(client)
    urls_path.parent.mkdir(parents=True, exist_ok=True)
    urls_path.write_text("\n".join(slugs) + "\n", encoding="utf-8", newline="\n")
    pages_dir.mkdir(parents=True, exist_ok=True)
    stats = {"listed": len(slugs), "fetched": 0, "cached": 0, "missing": 0, "blocked": 0}
    for slug in slugs[:limit]:
        path = pages_dir / f"{slug}.json"
        if path.exists():
            stats["cached"] += 1
            continue
        if not client.allowed(page_url(slug)) or not client.allowed(api_url(slug)):
            stats["blocked"] += 1
            continue
        body = client.get(api_url(slug), accept="application/json")
        if body is None:
            stats["missing"] += 1
            continue
        json.loads(body.decode("utf-8"))  # fail loudly on a non-JSON answer
        path.write_bytes(body)
        stats["fetched"] += 1
    return stats


# ── normalise ─────────────────────────────────────────────────────────────────


class _Text(HTMLParser):
    BLOCKS = {"p", "br", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in self.BLOCKS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in self.BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(value) -> str:
    """HTML (or a {'data': html} wrapper) -> plain text with collapsed whitespace."""
    if isinstance(value, dict):
        value = value.get("data")
    if not isinstance(value, str) or value.strip() in ("", "None"):
        return ""
    parser = _Text()
    parser.feed(value)
    parser.close()
    return re.sub(r"\s+", " ", html.unescape("".join(parser.parts))).strip()


def _titles(items) -> list[str]:
    out = []
    for it in items or []:
        t = it.get("title") if isinstance(it, dict) else it
        if isinstance(t, str) and t.strip() and t.strip() not in out:
            out.append(t.strip())
    return out


def option_names(item: dict) -> list[str]:
    names = _titles(item.get("adaptationoptions")) + [n for n in (item.get("cca_adaptation_options") or []) if isinstance(n, str)]
    return list(dict.fromkeys(names))


def scope_reasons(item: dict, matcher: ScopeMatcher, eco: ScopeMatcher) -> list[str]:
    """Why a case study is in scope (empty list = out of scope)."""
    reasons: list[str] = []
    options = option_names(item)
    text_fields = [html_to_text(item.get(k)) for k in ("long_description", "solutions")]
    for term in matcher.matches(" . ".join(options), *text_fields):
        reasons.append(f"scope:{term}")
    for el in item.get("elements") or []:
        if isinstance(el, dict) and el.get("token") in ECO_ELEMENT_TOKENS:
            reasons.append(f"scope:element:{el.get('title') or el.get('token')}")
    for name in options:
        if eco.matches(name):
            reasons.append(f"scope:option:{name}")
    return list(dict.fromkeys(reasons))


def countries_of(item: dict) -> tuple[list[str], int]:
    geo = item.get("geographic") or {}
    out, dropped = [], 0
    for name in geo.get("countries") or []:
        iso = _COUNTRIES_FOLDED.get(fold(str(name)))
        if iso is None:
            dropped += 1
        elif iso not in out:
            out.append(iso)
    return out, dropped


def _own_copyright(item: dict) -> bool:
    """True when the item states its own rights that are not the site-wide CC BY."""
    rights = item.get("rights")
    if isinstance(rights, dict):
        rights = rights.get("data") or rights.get("title")
    rights = (rights or "").strip() if isinstance(rights, str) else ""
    if not rights or rights == "None":
        return False
    return not re.search(r"cc[- ]?by(?![- ]?(nc|nd))", rights, re.I)


def build_record(slug: str, item: dict, reasons: list[str], harvested_on: str) -> tuple[RawRecord, int]:
    countries, dropped = countries_of(item)
    summary = None
    summary_licence = None
    if not _own_copyright(item):
        text = cut_summary(scrub_contacts(html_to_text(item.get("long_description"))))
        if text:
            summary, summary_licence = text, LICENCE
    year = None
    pub = str(item.get("publication_date") or "")[:4]
    if pub.isdigit():
        year = int(pub)
    keywords = [k.strip() for k in item.get("keywords") or [] if isinstance(k, str) and k.strip()]
    keywords += _titles(item.get("climate_impacts")) + reasons
    rec = RawRecord(
        id=f"ca-{slug.lower()}",
        source="climate_adapt",
        source_id=slug,
        kind="case_study",
        title=" ".join(str(item["title"]).split()),
        summary=summary,
        summary_licence=summary_licence,
        source_licence=LICENCE,
        url=page_url(slug),
        year=year,
        countries=countries,
        organisations=[],
        source_codes=SourceCodes(climate_adapt_sectors=_titles(item.get("sectors"))),
        keywords=list(dict.fromkeys(keywords)),
        harvested_on=harvested_on,
    )
    return rec, dropped


def normalise(pages_dir: Path = PAGES_DIR, out_path: Path = RECORDS_PATH) -> dict:
    matcher = ScopeMatcher(load_scope_terms())
    eco = ScopeMatcher(ECO_OPTION_TERMS)
    stamp = today()
    records: list[RawRecord] = []
    stats = {"pages": 0, "kept": 0, "dropped": 0, "unknown_countries": 0, "with_summary": 0, "sectors": {}}
    for path in sorted(pages_dir.glob("*.json")):
        slug = path.stem
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", slug):
            continue
        item = json.loads(path.read_text(encoding="utf-8"))
        stats["pages"] += 1
        reasons = scope_reasons(item, matcher, eco)
        if not reasons or not item.get("title"):
            stats["dropped"] += 1
            continue
        rec, dropped = build_record(slug, item, reasons, stamp)
        stats["unknown_countries"] += dropped
        records.append(rec)
        for s in rec.source_codes.climate_adapt_sectors:
            stats["sectors"][s] = stats["sectors"].get(s, 0) + 1
    stats["kept"] = write_jsonl(out_path, records)
    stats["with_summary"] = sum(1 for r in records if r.summary)
    stats["sectors"] = sorted(stats["sectors"].items(), key=lambda kv: (-kv[1], kv[0]))
    return stats


def print_stats(stats: dict) -> None:
    print(f"pages: {stats['pages']}, kept: {stats['kept']}, dropped: {stats['dropped']}")
    print(f"with summary: {stats['with_summary']}; unknown country names dropped: {stats['unknown_countries']}")
    for name, n in stats["sectors"][:15]:
        print(f"  {n:4d}  {name}")


def status() -> None:
    n = len(list(PAGES_DIR.glob("*.json"))) if PAGES_DIR.exists() else 0
    print(f"pages cached: {n}")
    if RECORDS_PATH.exists():
        print(f"records.jsonl: {sum(1 for _ in RECORDS_PATH.open(encoding='utf-8'))}")
    else:
        print("records.jsonl: not written")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["harvest", "normalise", "status"])
    parser.add_argument("--limit", type=int, default=None, help="harvest at most N case studies (testing)")
    args = parser.parse_args(argv)
    if args.command == "harvest":
        print(harvest(limit=args.limit))
        print_stats(normalise())
    elif args.command == "normalise":
        print_stats(normalise())
    else:
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
