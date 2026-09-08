# Review

Review modules help humans understand non-verified candidates. They are
advisory unless they call the deterministic verifier and pass the same gates.

Current canonical modules still live at the package top level:

| Current module | Purpose |
|---|---|
| `review_router.py` | One row per review rule with next-action labels. |
| `review_assistant_packets.py` | Dashboard-ready review packets. |
| `review_resolution.py` | Advisory resolution labels. |
| `llm_review_assistant.py` | Optional LLM summaries and reviewer notes. |
| `semantic_review.py` | Deterministic semantic comparison. |
| `embedding_semantics.py` | Optional embedding ranking. |
| `nli_semantics.py` | Optional entailment second opinion. |
| `evidence_intelligence.py` | Evidence bundle diagnostics. |
| `evidence_repair.py` | Search for stronger existing evidence. |
| `evidence_rerun.py` | Guarded advisory reruns. |
| `review_ranker.py` | Optional learned ranking experiment. |
| `safe_tuning.py` | Planning support for safe tuning. |

An LLM can explain, summarize, or suggest reviewer notes. It cannot approve a
rule or write verified/GIS outputs.
