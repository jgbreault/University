# Exports

Exports turn verified rules into downstream artifacts. They should consume only
verified, source-supported outputs.

Current canonical modules still live at the package top level:

| Current module | Purpose |
|---|---|
| `gis_felt_export.py` | Verified-only Felt/GIS export. |
| `geometry_operator.py` | Maps rule families into coarse GIS operations. |
| `compliance.py` | Proposal checker returning approved, rejected, or needs_review. |
| `applicability.py` | Dwelling/unit-range applicability parsing for table columns. |

GIS must not consume review-only, rejected, or advisory LLM outputs.
