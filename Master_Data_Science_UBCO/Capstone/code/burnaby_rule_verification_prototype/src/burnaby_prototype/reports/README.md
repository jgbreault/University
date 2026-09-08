# Reports

Reports make verification results understandable. They should describe what the
verifier did; they should not change decisions.

Current canonical modules still live at the package top level:

| Current module | Purpose |
|---|---|
| `slim_pipeline.py` | Orchestrates verifier output writing and sidecar reports. |
| `coverage_report.py` | Coverage and gap matrix reporting. |
| `rule_graph.py` | Links candidates, evidence, verified rules, and review items. |
| `rule_text.py` | Shared rule sentence rendering. |
| `review_text.py` | Reviewer-facing wording helpers. |
