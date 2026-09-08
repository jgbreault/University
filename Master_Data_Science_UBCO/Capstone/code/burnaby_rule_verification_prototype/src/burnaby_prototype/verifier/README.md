# Verifier

The verifier is the authority layer. It decides whether a candidate is proven,
needs review, rejected, or out of scope.

Current canonical modules still live at the package top level:

| Current module | Purpose |
|---|---|
| `verification.py` | Main verification loop. |
| `decision_policy.py` | Final bucket policy and global safety gates. |
| `support_checks.py` | Value, unit, operator, scope, and evidence-support checks. |
| `normalization.py` | Candidate canonicalization before proof. |
| `normalization_rules.py` | Config-driven normalization policy. |
| `domain_schema.py` | Rule families, units, operators, and numeric parsing. |
| `table_matrix.py` | Structured table recovery for matrix-style bylaws. |
| `table_natural_logic.py` | Table-aware proof/refutation helpers. |
| `text_span_proof.py` | Prose evidence span checks. |
| `proof_trace.py` | Reviewer-facing proof traces. |
| `proof_dag.py` | Proof graph sidecar. |
| `conflict_guard.py` | Cross-family collision detection. |
| `consensus.py` | Independent-evidence agreement diagnostics. |

Safety target:

```text
false_verified_count = 0
```

Do not weaken this layer to improve recall.
