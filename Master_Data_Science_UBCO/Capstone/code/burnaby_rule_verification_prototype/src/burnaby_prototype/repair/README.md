# Repair

Repair improves evidence packets before verification by restoring source
context. It is allowed to add source-backed context, not to change the legal
claim.

Current canonical modules still live at the package top level:

| Current module | Purpose |
|---|---|
| `source_repair.py` | Page re-anchoring, nearby context, parent heading, and table context. |
| `evidence_contract.py` | Evidence type constants and contract helpers. |

Allowed repair examples:

```text
(a) 3.0 metres
```

can become:

```text
The minimum setback is: (a) 3.0 metres
```

only when that parent text is found in the source. Failed repair means review,
not verification.
