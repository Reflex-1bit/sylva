"""
Sylva-wild: the shared search index, loaded once in a background thread.

Loading takes a few seconds (and the fastembed import took 21 s on the build
laptop), so the server starts at once and /wild/ask answers 503 until the index
is ready. A missing index (not built on this machine) is reported, not raised.
"""

import json
import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from app.services.wild.index import INDEX_DIR, ROOT, WildIndex

log = logging.getLogger(__name__)

MANIFEST = ROOT / "data" / "nature" / "catalogue" / "build" / "manifest.json"
SECTORS = ROOT / "data" / "nature" / "catalogue" / "sectors.json"
CATCH_ALL = "other"

Status = Literal["ready", "loading", "missing", "error"]


class IndexHolder:
    def __init__(self, index_dir: Path = INDEX_DIR):
        self.index_dir = index_dir
        self._index: Optional[WildIndex] = None
        self._status: Status = "loading"
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start_loading(self) -> None:
        with self._lock:
            if self._thread is not None or self._index is not None:
                return
            if not (self.index_dir / "meta.json").exists():
                self._status = "missing"
                return
            self._status = "loading"
            self._thread = threading.Thread(target=self._load, name="wild-index", daemon=True)
            self._thread.start()

    def _load(self) -> None:
        try:
            index = WildIndex(self.index_dir)
        except Exception:
            log.exception("Sylva-wild index failed to load")
            self._status = "error"
            return
        self._index = index
        self._status = "ready"
        log.info("Sylva-wild index ready: %d records", len(index))

    def set(self, index: WildIndex) -> None:
        """Install an index directly (tests, or a caller that loaded one)."""
        self._index = index
        self._status = "ready"

    @property
    def status(self) -> Status:
        if self._index is None and self._thread is None and self._status == "loading":
            self.start_loading()
        return self._status

    @property
    def index(self) -> Optional[WildIndex]:
        return self._index if self.status == "ready" else None


holder = IndexHolder()


@lru_cache(maxsize=1)
def sector_options() -> list[dict]:
    """Published catalogue sectors (largest first), without the catch-all, with EN/ES/PT labels."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    labels = {s["id"]: s for s in json.loads(SECTORS.read_text(encoding="utf-8"))["sectors"]}
    out = []
    for s in manifest["sectors"]:
        if s["id"] == CATCH_ALL:
            continue
        lab = labels.get(s["id"], {})
        out.append({
            "id": s["id"],
            "label_en": s.get("label_en") or lab.get("label_en") or s["id"],
            "label_es": s.get("label_es") or lab.get("label_es"),
            "label_pt": lab.get("label_pt"),
            "count": int(s.get("count", 0)),
        })
    return sorted(out, key=lambda s: (-s["count"], s["id"]))


@lru_cache(maxsize=1)
def attribution() -> str:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["attribution"]
