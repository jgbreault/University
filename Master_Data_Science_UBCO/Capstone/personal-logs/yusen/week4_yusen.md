## Week 4

**Summary:**
Focused on rebuilding the Burnaby R1 zoning-rule prototype into a verification-first system. The main goal was to separate rule extraction from rule verification, so different extraction sources can propose candidate rules while a deterministic verifier decides what is safe enough to pass into the GIS rule contract. Integrated old pipeline outputs, Zihao's extracted rules, and layout-aware table evidence into one benchmarked verification workflow.

**Tasks:**

* Refactored the Burnaby prototype into a slim verification-first pipeline based on candidate/evidence JSON
* Built multi-source input modes for old pipeline output, Zihao output, layout-table evidence, combined inputs, and all sources
* Created an adapter to convert Zihao's extraction output into the verifier's standard candidate/evidence contract
* Added an evidence contract and evidence-quality checks for value grounding, unit grounding, candidate/evidence matching, and table context completeness
* Added optional PyMuPDF layout-table extraction to produce structured table evidence with row headers, column headers, cell values, and bounding boxes
* Strengthened deterministic verification checks for value, unit, operator, rule object, applies_to, scope, table context, and rule/unit compatibility
* Updated the benchmark evaluator to support slim-verifier outputs and safety metrics
* Added unit tests for sentence verification, table-cell verification, wrong-value rejection, wrong-rule-object rejection, non-target table columns, Zihao adapter behavior, evidence quality, and layout-table evidence
* Pushed the cleaned verification-first baseline to GitHub main

**Time:**

* Verification-first pipeline refactor and architecture design: 8 hours
* Evidence contract and evidence-quality metrics: 8 hours
* Zihao adapter and multi-source input integration: 8 hours
* PyMuPDF layout-table evidence extraction and table candidate inference: 8 hours
* Benchmarking, tests, validation, cleanup, and GitHub push: 8 hours

**Total: 40 hours**

**Challenges:**

* Keeping the verifier strict while still improving rule coverage
* Avoiding overfitting to Burnaby-specific values or benchmark answers
* Handling table-based rules where the meaning depends on row headers, column headers, and cell values together
* Combining multiple extraction sources without letting noisy or duplicate candidates become verified
* Separating true verification failures from poor evidence quality
* Making sure LLM or upstream confidence scores never override deterministic support checks

**Next Steps:**

* Improve extraction coverage for the remaining missed rules, especially `height_004` and `fire_003`
* Add post-verification deduplication across multiple candidate sources
* Add conflict detection for rules with the same scope but different values
* Improve layout-table evidence quality and bounding-box audit output
* Keep the deterministic verifier as the final GIS trust gate while experimenting with better extraction inputs
