#!/usr/bin/env python3
"""Extract Calgary core RAG-pack rules with a local Ollama model."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import requests
from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parent
DEFAULT_PACKS = ROOT / "experiments" / "calgary_graph_rag" / "extract_now_core_packs.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "experiments" / "calgary_graph_rag" / "core_rule_extraction_ollama"
DEFAULT_MODEL = "qwen2.5:14b-instruct"

RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "rule_key": {"type": "string"},
                    "rule_object": {"type": "string"},
                    "constraint_type": {"type": "string"},
                    "subject": {"type": "string"},
                    "operator": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                    "condition": {"type": "string"},
                    "exception": {"type": "string"},
                    "evidence_text": {"type": "string"},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "source_id", "rule_key", "rule_object", "constraint_type", "subject",
                    "operator", "value", "unit", "condition", "exception", "evidence_text", "warnings",
                ],
            },
        },
        "skipped_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source_id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["source_id", "reason"],
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["rules", "skipped_sources", "warnings"],
}

PROMPT = """Extract Calgary zoning rules.
Return ONLY JSON:
{"rules":[],"skipped_sources":[],"warnings":[]}
Each rule must have:
source_id, rule_key, rule_object, constraint_type, subject, operator, value, unit, condition, exception, evidence_text, warnings.
Rules:
- Use only evidence text. One source_id per rule. Skip deleted clauses.
- Atomic rules only. Prefer numeric limits and required/private amenity clauses.
- operator in [">=","<=","=","permitted","prohibited","required","not required"].
- unit in ["","m","m2","%","storeys","units"]. Values are numbers only when numeric.
- evidence_text must be copied from the cited source.
- Max 16 rules for this input.
Evidence JSON:
"""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def compact_pack(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "pack_id": pack.get("pack_id", ""),
        "page_number": pack.get("page_number"),
        "scope": pack.get("scope", ""),
        "evidence_blocks": [
            {
                "source_id": block.get("source_id", ""),
                "role": block.get("role", ""),
                "text": block.get("text", ""),
            }
            for block in pack.get("evidence_blocks", [])
            if block.get("applicability") == "core_rule"
        ],
    }


def extract_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return json.loads(raw[start:end + 1])
    raise ValueError("No JSON object found in Ollama response.")


def normalize_parsed(parsed: dict[str, Any]) -> dict[str, Any]:
    parsed.setdefault("rules", [])
    parsed.setdefault("skipped_sources", [])
    parsed.setdefault("warnings", [])
    for rule in parsed["rules"]:
        for key in RULE_SCHEMA["properties"]["rules"]["items"]["required"]:
            if key == "warnings":
                rule.setdefault(key, [])
            else:
                rule.setdefault(key, "")
    return parsed


def call_ollama(*, model: str, prompt: str, host: str, timeout: int, num_ctx: int, num_predict: int) -> dict[str, Any]:
    response = requests.post(
        f"{host.rstrip('/')}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def validate_sources(parsed: dict[str, Any], allowed_sources: set[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    validator = Draft7Validator(RULE_SCHEMA)
    for error in validator.iter_errors(parsed):
        issues.append({"type": "schema", "path": list(error.path), "message": error.message})
    for index, rule in enumerate(parsed.get("rules", []), start=1):
        source_id = str(rule.get("source_id", ""))
        if source_id not in allowed_sources:
            issues.append({"type": "bad_source_id", "rule_index": index, "source_id": source_id})
        if str(rule.get("operator", "")) not in {">=", "<=", "=", "permitted", "prohibited", "required", "not required"}:
            issues.append({"type": "bad_operator", "rule_index": index, "operator": rule.get("operator", "")})
        if str(rule.get("unit", "")) not in {"", "m", "m2", "%", "storeys", "units"}:
            issues.append({"type": "bad_unit", "rule_index": index, "unit": rule.get("unit", "")})
    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packs", type=Path, default=DEFAULT_PACKS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=1024)
    parser.add_argument("--max-packs", type=int, default=0, help="Limit core packs for quick local smoke tests.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def merge_parsed(parts: list[dict[str, Any]]) -> dict[str, Any]:
    merged = {"rules": [], "skipped_sources": [], "warnings": []}
    for part in parts:
        merged["rules"].extend(part.get("rules", []))
        merged["skipped_sources"].extend(part.get("skipped_sources", []))
        merged["warnings"].extend(part.get("warnings", []))
    return merged


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    parsed_path = output_dir / "core_rules_parsed.json"
    raw_path = output_dir / "core_rules_raw_response.json"
    summary_path = output_dir / "summary.json"

    packs = [pack for pack in read_jsonl(args.packs) if pack.get("applicability") == "core_rule"]
    if args.max_packs:
        packs = packs[: args.max_packs]
    inventory = [compact_pack(pack) for pack in packs]
    allowed_sources = {
        block["source_id"]
        for pack in inventory
        for block in pack["evidence_blocks"]
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    if parsed_path.exists() and not args.overwrite:
        parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
        raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
        seconds = 0.0
    else:
        started = time.time()
        raw_parts = []
        parsed_parts = []
        for index, pack in enumerate(inventory, start=1):
            part_raw_path = output_dir / f"pack_{index:02d}_raw_response.json"
            part_parsed_path = output_dir / f"pack_{index:02d}_parsed.json"
            if part_parsed_path.exists() and not args.overwrite:
                raw_part = json.loads(part_raw_path.read_text(encoding="utf-8")) if part_raw_path.exists() else {}
                parsed_part = json.loads(part_parsed_path.read_text(encoding="utf-8"))
            else:
                raw_part = call_ollama(
                    model=args.model,
                    prompt=PROMPT + json.dumps([pack], ensure_ascii=False),
                    host=args.ollama_host,
                    timeout=args.timeout,
                    num_ctx=args.num_ctx,
                    num_predict=args.num_predict,
                )
                parsed_part = normalize_parsed(extract_json(raw_part.get("response", "")))
                write_json(part_raw_path, raw_part)
                write_json(part_parsed_path, parsed_part)
            raw_parts.append(
                {
                    "pack_id": pack.get("pack_id", ""),
                    "page_number": pack.get("page_number"),
                    "raw": raw_part,
                }
            )
            parsed_parts.append(parsed_part)
        seconds = time.time() - started
        raw = {"parts": raw_parts}
        parsed = merge_parsed(parsed_parts)
        write_json(raw_path, raw)
        write_json(parsed_path, parsed)

    validation_issues = validate_sources(parsed, allowed_sources)
    summary = {
        "model": args.model,
        "input_pack_count": len(packs),
        "input_block_count": sum(len(pack["evidence_blocks"]) for pack in inventory),
        "rule_count": len(parsed.get("rules", [])),
        "skipped_source_count": len(parsed.get("skipped_sources", [])),
        "warnings": parsed.get("warnings", []),
        "validation_issue_count": len(validation_issues),
        "validation_issues": validation_issues[:50],
        "seconds": seconds,
        "output_dir": str(output_dir),
    }
    write_json(summary_path, summary)
    return summary


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
