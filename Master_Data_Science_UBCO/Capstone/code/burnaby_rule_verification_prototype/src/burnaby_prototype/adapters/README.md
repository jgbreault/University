# Adapters

Adapters convert outside extraction formats into the verifier's internal
contract:

```text
rule_candidates + evidence_units
```

Current canonical modules still live at the package top level for import
compatibility:

| Current module | Purpose |
|---|---|
| `zihao_adapter.py` | Pipeline 5-style registry intake. |
| `pipeline9_adapter.py` | Pipeline 9 graph-RAG intake with provenance and source re-anchoring. |
| `native_extraction.py` | Current native LLM candidate generation output parser used by M4. |

Adapters are proposer-tier only. They must never promote a rule into
`verified_rules.json`.
