#!/usr/bin/env python3
"""Build the advisory bylaw-RAG index for a city.

Corpus preference order:
1. ``data/bylaws/<city>/sections.json`` — section-anchored text from the
   internal extraction helper (best: whole-section context);
2. the city's run ``evidence_units.json`` — works for every city today.

Writes ``outputs/<city>_slim_pipeline5_registry/bylaw_rag_index.json``.
Advisory only: nothing in the verify path reads this artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.bylaw_rag import (
    BylawIndex,
    build_index_payload,
    load_corpus_from_evidence_units,
    load_corpus_from_sections,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="burnaby_r1")
    parser.add_argument("--ask", default=None, help="Optional smoke question to run against the fresh index.")
    args = parser.parse_args()

    sections_path = ROOT / "data" / "bylaws" / args.city / "sections.json"
    out_dir = ROOT / "outputs" / f"{args.city}_slim_pipeline5_registry"
    if sections_path.exists():
        chunks = load_corpus_from_sections(json.loads(sections_path.read_text(encoding="utf-8")))
        source = str(sections_path)
    else:
        evidence_path = out_dir / "evidence_units.json"
        chunks = load_corpus_from_evidence_units(json.loads(evidence_path.read_text(encoding="utf-8")))
        source = str(evidence_path)

    payload = build_index_payload(chunks)
    payload["corpus_source"] = source
    out_path = out_dir / "bylaw_rag_index.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[rag] {len(chunks)} chunks from {source}")
    print(f"[rag] index written to {out_path}")

    if args.ask:
        index = BylawIndex(chunks)
        for hit in index.ask(args.ask, top_k=3):
            print(f"  [{hit.get('section') or hit['chunk_id']}] score={hit['score']}: {hit['text'][:110]}")


if __name__ == "__main__":
    main()
