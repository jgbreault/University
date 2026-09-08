"""internal extraction helper — legacy diagnostic path; native M4 is current.

This package lets the team read and extract a bylaw PDF themselves (to
diagnose verification behaviour, curate gold sets, and trial new cities)
without replacing the current native M4 product path. It emits the EXISTING
Pipeline-5 registry contract
(``final_rule_registry.json``) so experimental verify-runs need zero verifier
changes — feed the emitted file to ``scripts/run_slim_verifier.py`` via
``--pipeline5-registry``.

Boundary rules (enforced by tests/test_extraction_layer.py):

- No verify-path module may import anything from this package.
- This package never imports the verifier or the decision policy; its
  candidates are PROPOSALS and the deterministic verifier remains the gate.
- API keys come ONLY from the environment (``GOOGLE_API_KEY``); nothing in
  this package writes a key to any file.

Submodules are imported lazily by callers (``pdf_ingest``, ``text_stream``,
``table_stream``, ``registry_writer``) so importing the package itself never
pulls optional heavy dependencies (docling, pdfplumber, google-genai).
"""
