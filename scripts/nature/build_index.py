"""
Embed the nature library (servable records) and industry map with Gemini and
write data/nature/index/{library,industry_map}.npy plus index_meta.json.

Usage: python scripts/nature/build_index.py [--data-dir DIR]
Needs GEMINI_API_KEY (or GOOGLE_API_KEY); without one it prints a message and
exits 0, and search stays BM25-only.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.services.nature.embeddings import DEFAULT_DIM, embed_model, embed_texts  # noqa: E402
from app.services.nature.search import content_hash, index_documents  # noqa: E402
from app.services.nature.store import DEFAULT_DIR, NatureStore  # noqa: E402


def _api_key() -> str:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""


async def build(data_dir: Path, api_key: str, client=None) -> dict:
    store = NatureStore(data_dir)
    model = embed_model()
    index_dir = Path(data_dir) / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    meta: dict = {"model": model, "dim": DEFAULT_DIM, "dbs": {}}
    pending: list[tuple[Path, Path]] = []  # (temp, final); swapped in only after all succeed
    for name, (records, texts) in index_documents(store).items():
        matrix = await embed_texts(
            texts,
            kind="document",
            api_key=api_key,
            titles=[r.title for r in records],
            model=model,
            client=client,
        )
        tmp = index_dir / f"{name}.npy.tmp"
        with open(tmp, "wb") as fh:
            np.save(fh, matrix)
        pending.append((tmp, index_dir / f"{name}.npy"))
        meta["dbs"][name] = {"hash": content_hash(texts), "ids": [r.id for r in records]}
        print(f"{name}: {len(records)} records embedded")
    meta_tmp = index_dir / "index_meta.json.tmp"
    meta_tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.append((meta_tmp, index_dir / "index_meta.json"))
    for tmp, final in pending:
        os.replace(tmp, final)
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args(argv)
    key = _api_key()
    if not key:
        print("No GEMINI_API_KEY set: skipping embeddings. Search will use BM25 only.")
        return 0
    asyncio.run(build(args.data_dir, key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
