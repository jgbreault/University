# M4 Release Engineering Checklist

This checklist prepares the M4 release candidate without accidentally committing
generated output noise.

## Current Release State

```text
Current product path: native_m4
Safety status: mvp_safety_ready
Current false verified total: 0
Remote: not configured in this local repo
```

Do not use:

```bash
git add -A
```

The worktree contains many regenerated historical outputs. Stage explicitly.

## Must Stage

Core release guardrails and docs:

```bash
git add .gitignore
git add README.md pyproject.toml
git add docs/README.md docs/CONSOLIDATED_PROTOTYPE.md docs/FINAL_M4_AUDIT.md
git add docs/M4_RELEASE_ENGINEERING.md docs/MVP_VERIFICATION_HANDOFF.md docs/PROJECT_STRUCTURE.md
git add docs/native_extraction_v1.md docs/v2_1_upgrade_report.md
git add outputs/README.md
```

M4/native scripts and legacy separation:

```bash
git add scripts/README.md
git add scripts/build_m4_source_corpus.py scripts/run_consolidated_prototype.py
git add scripts/run_m4_bakeoff.py scripts/run_mvp_verification.py scripts/run_v3_bakeoff.py
git add scripts/run_extraction.py scripts/run_slim_verifier.py
git add scripts/demo.sh scripts/run_holdout_eval.py scripts/run_vancouver_holdout.py
git add scripts/legacy/
```

Verifier, native extraction, source corpus, M4 discovery, and package skeletons:

```bash
git add src/burnaby_prototype/README.md
git add src/burnaby_prototype/adapters/ src/burnaby_prototype/discovery/
git add src/burnaby_prototype/exports/ src/burnaby_prototype/repair/
git add src/burnaby_prototype/reports/ src/burnaby_prototype/review/
git add src/burnaby_prototype/source/ src/burnaby_prototype/verifier/
git add src/burnaby_prototype/v3_clause_candidates.py
git add src/burnaby_prototype/v3_discovery.py src/burnaby_prototype/v3_report.py
git add src/burnaby_prototype/compliance.py src/burnaby_prototype/decision_policy.py
git add src/burnaby_prototype/native_extraction.py src/burnaby_prototype/slim_pipeline.py
git add src/burnaby_prototype/support_checks.py src/burnaby_prototype/v2_bakeoff.py
git add src/burnaby_prototype/v2_matrix_candidates.py src/burnaby_prototype/verification.py
git add src/burnaby_prototype/extraction/
```

Configs, benchmark changes, dashboard, and tests:

```bash
git add configs/burnaby_r1.json configs/calgary_rcg.json
git add benchmark/evaluate_adversarial.py benchmark/gold/burnaby_r1_proposal_cases.json
git add benchmark/source_corpus/
git add dashboard/streamlit_app.py
git add tests/
```

Curated output artifacts only. These are kept visible by `.gitignore`; raw
model outputs, pass1/repair folders, V2 output churn, and old smoke runs remain
ignored or unstaged:

```bash
git add outputs/mvp_verification/
git add outputs/topdown_validation/m4_source_pdf_audit.json
git add outputs/m7_runs/
```

Optional, only if the notebook is part of the handoff:

```bash
git add notebooks/mvp_verification_test_run.ipynb
```

## Do Not Stage

Leave these out of the M4 release commit:

```text
outputs/v2_runs/
outputs/v2_runs_full_discovery/
outputs/*_native_v1_smoke_*
outputs/*_p9/
outputs/*_p9_v21/
outputs/*_slim_pipeline5_registry_v21/
outputs/*_pre_v21_backup/
outputs/**/raw_model_outputs.json
outputs/**/verification_cache.json
outputs/**/pass1/
outputs/**/repair_pass/
outputs/**/dry_run/
outputs/**/*.csv
```

Already-tracked historical output files may still appear as modified in
`git status` because `.gitignore` cannot hide tracked files. Do not stage them.

## Pre-Commit Verification

Run:

```bash
.venv/bin/python -m unittest discover tests
.venv/bin/python benchmark/evaluate_adversarial.py
.venv/bin/python scripts/run_consolidated_prototype.py status
```

Expected:

```text
414 tests OK
ALL BLOCKED: True
overall_status = mvp_safety_ready
current_path_version = native_m4
current_false_verified_total = 0
```

## After Staging, Before Commit

Review exactly what would be committed:

```bash
git diff --cached --stat
git diff --cached --name-only
```

Check for generated-noise mistakes:

```bash
git diff --cached --name-only | rg 'outputs/v2_runs|raw_model_outputs|verification_cache|/pass1/|/repair_pass/|/dry_run/|\\.csv$'
```

That command should print nothing.

## Remote / Backup

This local repo currently has no remote configured. Before treating M4 as safe
from a release-engineering perspective, configure the correct remote and push a
branch after the commit:

```bash
git remote -v
git remote add origin <repo-url>
git push -u origin <branch-name>
```
