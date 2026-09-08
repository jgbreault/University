#!/usr/bin/env python3
"""Run the ADVISORY LLM review-assistant over the review queue.

This is a separate, opt-in step — it is NOT part of run_slim_verifier.py, so the
core verification pipeline stays deterministic and offline. It reads
``review_needed.json`` and writes ``review_assistant.json`` with a short brief
per review item (why blocked + most likely missing field).

Model: defaults to claude-opus-4-8; pass --model claude-sonnet-4-6 or
claude-haiku-4-5 for a cheaper run. With --offline (or when the anthropic SDK /
ANTHROPIC_API_KEY are unavailable) it produces deterministic heuristic briefs
with no network calls. Nothing here can verify a rule.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from burnaby_prototype.llm_review_assistant import DEFAULT_MODEL, run_review_assistant


def _make_client(offline: bool):
    """Return an Anthropic client, or None to run in offline heuristic mode."""
    if offline:
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[review-assistant] ANTHROPIC_API_KEY not set — running offline (heuristic).")
        return None
    try:
        import anthropic
    except ModuleNotFoundError:
        print("[review-assistant] anthropic SDK not installed (`pip install -e .[llm]`) — running offline.")
        return None
    return anthropic.Anthropic()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "outputs" / "burnaby_r1_slim_pipeline5_registry"),
        help="Folder containing review_needed.json; review_assistant.json is written here.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Claude model id (default: %(default)s).")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N review items.")
    parser.add_argument("--offline", action="store_true", help="Force deterministic heuristic mode (no API).")
    args = parser.parse_args()

    out_dir = Path(args.output_dir).expanduser()
    review_rules = json.loads((out_dir / "review_needed.json").read_text(encoding="utf-8"))

    client = _make_client(args.offline)
    report = run_review_assistant(review_rules, client=client, model=args.model, limit=args.limit)

    dest = out_dir / "review_assistant.json"
    dest.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[review-assistant] mode={report['mode']} model={report['model']} items={report['item_count']}")
    for item in report["items"][:3]:
        fix = item.get("likely_fix", {})
        print(f"  - {item['rule_id']}: fix.field={fix.get('field')} -> {fix.get('proposed_value')!r}")
    print(f"[review-assistant] wrote {dest}")


if __name__ == "__main__":
    main()
