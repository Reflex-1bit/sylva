"""
Build the Sylva-wild search index over every record of the open nature catalogue.

    python -m scripts.nature.wild.build_index                 # all records
    python -m scripts.nature.wild.build_index --limit 2000    # quick trial

Reads data/nature/catalogue/build/catalogue.json (local; see the catalogue
README to rebuild it) and writes data/nature/wild/index/. Embedding runs on a
local ONNX model (no API key, no network after the one-time model download).
Vectors are written in parts of --part-size records under index/parts/, so an
interrupted run resumes where it stopped; parts from different text or model
are discarded.
"""

import argparse
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from app.services.wild.index import (
    DEFAULT_MODEL, INDEX_DIR, ROOT, FastEmbedder, dense_text, doc_fields, text_hash, write_index,
)

CATALOGUE = ROOT / "data" / "nature" / "catalogue" / "build" / "catalogue.json"


def load_docs(path: Path, limit: int | None) -> tuple[list[dict], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data["records"]
    if len(records) != data.get("count", len(records)):
        raise SystemExit(f"catalogue says count={data['count']} but holds {len(records)} records")
    docs = [doc_fields(r) for r in records[:limit] if r.get("title")]
    ids = [d["id"] for d in docs]
    if len(set(ids)) != len(ids):
        raise SystemExit("duplicate record ids in the catalogue")
    return docs, {"catalogue_generated_on": data.get("generated_on"),
                  "catalogue_version": data.get("version")}


def embed_in_parts(texts: list[str], parts_dir: Path, hash_: str, part_size: int,
                   embedder) -> np.ndarray:
    parts_dir.mkdir(parents=True, exist_ok=True)
    stamp = parts_dir / "parts.json"
    want = {"text_hash": hash_, "model": embedder.model, "part_size": part_size, "count": len(texts)}
    if stamp.exists() and json.loads(stamp.read_text(encoding="utf-8")) != want:
        print("parts were built from other text or model; starting over")
        shutil.rmtree(parts_dir)
        parts_dir.mkdir(parents=True)
    stamp.write_text(json.dumps(want), encoding="utf-8")

    n_parts = (len(texts) + part_size - 1) // part_size
    t0 = time.time()
    done_now = 0
    for p in range(n_parts):
        f = parts_dir / f"part-{p:04d}.npy"
        lo, hi = p * part_size, min((p + 1) * part_size, len(texts))
        if f.exists() and np.load(f, mmap_mode="r").shape == (hi - lo, embedder.dim):
            continue
        vecs = embedder(texts[lo:hi], "document").astype(np.float16)
        tmp = parts_dir / f"part-{p:04d}.tmp.npy"
        np.save(tmp, vecs)
        tmp.replace(f)
        done_now += hi - lo
        rate = done_now / max(time.time() - t0, 1e-6)
        left = (len(texts) - hi) / rate if rate else 0
        print(f"part {p + 1}/{n_parts}: records {hi}/{len(texts)}  "
              f"{rate:.0f}/s  ~{left / 60:.1f} min left", flush=True)
    return np.concatenate([np.load(parts_dir / f"part-{p:04d}.npy") for p in range(n_parts)])


def main(argv: list[str] | None = None, embedder=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalogue", type=Path, default=CATALOGUE)
    ap.add_argument("--out", type=Path, default=INDEX_DIR)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, default=None, help="index only the first N records (trial)")
    ap.add_argument("--part-size", type=int, default=5000)
    ap.add_argument("--keep-parts", action="store_true", help="keep index/parts/ after a full build")
    args = ap.parse_args(argv)

    if not args.catalogue.exists():
        print(f"missing {args.catalogue}; build the catalogue first (data/nature/catalogue/README.md)",
              file=sys.stderr)
        return 2
    docs, cat_meta = load_docs(args.catalogue, args.limit)
    embedder = embedder or FastEmbedder(args.model)
    texts = [dense_text(d) for d in docs]
    hash_ = text_hash(texts, embedder.model)
    print(f"{len(docs)} records to index with {embedder.model}")

    parts_dir = args.out / "parts"
    vectors = embed_in_parts(texts, parts_dir, hash_, args.part_size, embedder)

    meta = write_index(args.out, docs, vectors, embedder.model, hash_, {
        **cat_meta,
        "built_on": dt.date.today().isoformat(),
        "dense_text": "title. organism. first 1000 characters of the summary",
    })
    if not args.keep_parts:
        shutil.rmtree(parts_dir)
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
