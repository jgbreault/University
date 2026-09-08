# Discovery

Discovery finds source text and evidence packs before verification. It can
retrieve, chunk, rank, cache, and ask LLMs for candidate rules, but it does not
verify legal correctness.

Current canonical modules still live at the package top level:

| Current module | Purpose |
|---|---|
| `bylaw_rag.py` | Deterministic BM25/source search for dashboard and evidence discovery. |
| `v2_discovery.py` | Full-bylaw source chunks and evidence-pack construction. |
| `v2_store.py` | SQLite cache and run ledger. |
| `v2_bakeoff.py` | Model bakeoff orchestration. |
| `v2_matrix_candidates.py` | Deterministic table-matrix candidate proposal. |
| `native_extraction.py` | LLM extraction lane. |

The verifier may consume candidates and evidence produced here, but it should
not import retrieval ranking as a decision rule.
