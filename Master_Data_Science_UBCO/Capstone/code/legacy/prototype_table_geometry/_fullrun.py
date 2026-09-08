import matplotlib; matplotlib.use("Agg")
import sys, io, time, json, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import nbformat
nb = nbformat.read("table_flatten_prototype.ipynb", as_version=4)
ns = {"display": lambda *a, **k: None, "get_ipython": lambda: None}
t0 = time.time()
ok = True
for i, c in enumerate(x for x in nb.cells if x.cell_type == "code"):
    try:
        exec(c.source, ns)
    except Exception as e:
        ok = False
        print(f"CELL {i} FAILED: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        break
res = {}
if ok:
    rf = ns.get("reviewed_facts", [])
    from collections import Counter
    res["wall_clock_s"] = round(time.time() - t0, 1)
    res["total_facts"] = len(rf)
    res["llm_reviewed"] = sum(f["llm_reviewed"] for f in rf)
    res["final_status"] = dict(Counter(f["final_status"] for f in rf))
    res["llm_decisions"] = dict(Counter(f.get("llm_decision") for f in rf if f["llm_reviewed"]))
    res["rule_ready"] = len(ns.get("rule_ready", []))
    # sample of accepted data values
    res["accepted_sample"] = [
        {"row_path": " > ".join(f["final_row_path"]),
         "col_path": " > ".join(f["final_column_path"]),
         "value": f["final_value"], "cond": f["final_condition"],
         "decision": f.get("llm_decision")}
        for f in rf if f["final_status"] == "accepted"
    ][:25]
    # dash check
    res["dash_facts"] = [
        {"value": f["final_value"], "status": f["final_status"], "decision": f.get("llm_decision")}
        for f in rf if f["is_dash"]
    ][:10]
open("_fullrun_out.json", "w", encoding="utf-8").write(json.dumps(res, indent=2, ensure_ascii=False))
print("\n=== DONE ===", res.get("wall_clock_s"), "s", flush=True)
