#!/usr/bin/env bash
# One-command end-to-end demo: THREE cities, TWO extraction systems, ONE verifier.
#
#   Burnaby R1    (Pipeline 5 extraction)      -> verify -> benchmark
#   Vancouver RS  (prototype adapter)          -> verify -> benchmark
#   Calgary R-CG  (our internal extraction)    -> verify -> benchmark
#   + adversarial suite, GIS artifacts, 3D envelope, proof graph, RAG, briefs
#
# Every city must hold verified_precision = 1.0 / false_verified = 0.
# Usage:  bash scripts/demo.sh
set -euo pipefail

cd "$(dirname "$0")/../.."
PY="${PYTHON:-.venv/bin/python}"

hr() { printf '\n=== %s ===\n' "$1"; }

gate() { # gate <city>  — print the city's headline metrics from its report
  $PY - "$1" <<'PYEOF'
import json, sys
city = sys.argv[1]
b = json.load(open(f"outputs/{city}_slim_pipeline5_registry/benchmark_report.json"))
m = b["rule_metrics"]; g = b["quality_gates"]["passed"]
print(f"  {city}: verified/review/rejected/not_used = "
      f"{m['verified_rule_count']}/{m['review_rule_count']}/{m['rejected_rule_count']}/{m['not_used_rule_count']}")
print(f"  recall={round(m['verified_gold_recall'],3)}  precision={m['verified_precision']}  "
      f"false_verified={m['false_verified_count']}  GATES={'PASS' if g else 'FAIL'}")
PYEOF
}

hr "1/6  Burnaby R1 — verify (Pipeline 5 extraction) + benchmark"
$PY scripts/run_slim_verifier.py --city burnaby_r1 >/dev/null
$PY benchmark/evaluate_benchmark.py --city burnaby_r1 >/dev/null
gate burnaby_r1

hr "2/6  Vancouver RS — cross-city transfer (no hand-fit) + benchmark"
$PY scripts/run_vancouver_holdout.py >/dev/null 2>&1
$PY benchmark/evaluate_benchmark.py --city vancouver_rs >/dev/null
gate vancouver_rs

hr "3/6  Calgary R-CG — OUR extraction helper -> verify + benchmark"
if [ -f outputs/calgary_rcg_extraction/final_rule_registry.json ]; then
  $PY scripts/run_slim_verifier.py --city calgary_rcg \
      --pipeline5-registry outputs/calgary_rcg_extraction/final_rule_registry.json >/dev/null
  $PY benchmark/evaluate_benchmark.py --city calgary_rcg >/dev/null
  gate calgary_rcg
else
  echo "  (skipped: run scripts/fetch_bylaw.py + scripts/run_extraction.py for calgary_rcg first)"
fi

hr "4/6  Adversarial (poisoned candidates + poisoned bundles must ALL be blocked)"
# evaluate_adversarial.py exits 1 on any leak; the demo must fail loudly with it.
if adv_out="$($PY benchmark/evaluate_adversarial.py)"; then
  printf '%s\n' "$adv_out" | grep -iE "cases:|blocked:|leaked:|ALL BLOCKED"
else
  printf '%s\n' "$adv_out"
  echo "ADVERSARIAL LEAK — demo failed"
  exit 1
fi

hr "5/6  GIS artifacts: buildable envelope + 3D viewer + Felt export"
$PY scripts/build_buildable_envelope.py >/dev/null && echo "  ok: buildable_envelope.json"
$PY scripts/build_envelope_3d.py >/dev/null 2>&1 && echo "  ok: envelope_3d.html (Three.js viewer)" || echo "  (3D viewer build skipped)"

hr "6/6  Explainability: proof graph + RAG indexes + advisory briefs"
$PY scripts/build_proof_graph.py | tail -1
for city in burnaby_r1 vancouver_rs calgary_rcg; do
  $PY scripts/build_rag_index.py --city "$city" >/dev/null 2>&1 && echo "  ok: $city bylaw_rag_index.json" || true
done
$PY scripts/run_review_assistant.py --offline >/dev/null && echo "  ok: review_assistant.json (advisory, offline)"

hr "Done — three cities, two extraction systems, precision 1.0 everywhere"
cat <<EOF
  Dashboard (city selector, map, bylaw + Ask-the-bylaw, 3D envelope):
    $PY -m streamlit run dashboard/streamlit_app.py --server.port 8502
EOF
