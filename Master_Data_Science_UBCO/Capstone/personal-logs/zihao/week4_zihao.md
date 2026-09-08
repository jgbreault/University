# Week 4

## Summary

This week, I mainly worked on creating and iterating on the core rule extraction pipeline for zoning bylaw documents. The focus was on improving the pipeline structure, testing different extraction strategies, and narrowing the experiment scope to a more controlled case. Instead of continuing broad multi-city testing, I reduced the experiment to Burnaby and focused on extracting rules related to rear principal and front principal buildings. I also started using the Gemini API for rule extraction experiments, since the locally deployed Qwen 3.5 9B model was not reliable enough for complex table parsing, rule normalization, and evidence-based validation. By the end of this week, the extraction result reached 100% recall for rear principal building rules and around 80% recall for front principal building rules in the Burnaby test case.

## Tasks

- Created and iterated on the main rule extraction pipeline for zoning bylaw PDFs
- Refined the workflow for:
  - block selection
  - evidence unit construction
  - table handling
  - rule extraction
  - rule normalization
  - source evidence tracing
  - validation and review routing
- Reduced the experiment scope to Burnaby R1 zoning rules to make evaluation more controlled
- Focused the Burnaby experiment on rear principal building and front principal building rules
- Tested Gemini API as an external LLM option for rule extraction and normalization
- Compared Gemini API results with the locally deployed Qwen 3.5 9B model
- Improved table extraction logic for complex development regulation tables
- Worked on extracting and validating rules related to:
  - lot coverage
  - building height
  - storeys
  - setbacks
  - building separation
  - front principal buildings
  - rear principal buildings
- Achieved full extraction coverage for rear principal building rules in the Burnaby test case
- Reached approximately 80% extraction coverage for front principal building rules in the Burnaby test case
- Reviewed extraction failures and identified issues related to table parsing, rule relevance, and rule key normalization
- Attended internal team meetings to discuss pipeline progress, technical issues, and next steps

## Time

- Main rule extraction pipeline creation and iteration: 13 hours
- Burnaby-focused rear/front principal building rule experiments: 8 hours
- Gemini API testing and comparison with local Qwen model: 5 hours
- Table extraction and structured evidence handling: 6 hours
- Validation, review routing, and error analysis: 5 hours
- Internal team meetings and coordination: 3 hours

**Total: 40 hours**

## Challenges

The main challenge this week was that rule extraction is still difficult to generalize across different bylaw structures. Even when the pipeline works well for one rule category or one city, the same logic does not always transfer cleanly to another municipality or another table format.

Table extraction remains the biggest technical challenge. Burnaby’s R1 development regulation table contains multi-level headers, grouped rows, shared values, and mixed conditions. This makes it difficult for both deterministic parsing and LLM-based extraction to correctly identify which value belongs to which rule, condition, and building type.

The local Qwen 3.5 9B model continued to struggle with detailed rule extraction, especially for complex tables and precise legal wording. Gemini API produced more stable results, but the pipeline still requires stronger post-processing and validation to avoid incorrect rule keys, wrong evidence matching, and overly broad extraction.

Another challenge was balancing recall and precision. The pipeline was able to reach 100% recall for rear principal building rules in the Burnaby test case, but front principal building rules only reached around 80%. This suggests that the current approach is improving, but still needs better handling of table structure, rule grouping, and target-specific relevance.

## Next Steps

- Continue improving the Burnaby-focused pipeline before expanding back to other municipalities
- Improve front principal building rule extraction to close the remaining recall gap
- Strengthen table parsing for complex development regulation tables
- Improve deterministic post-processing for table-derived rules
- Refine rule key normalization so extracted rules use object-based names instead of section-based names
- Improve routing logic so valid table-derived rules are not incorrectly marked as repair or review
- Continue testing Gemini API for extraction, normalization, and validation steps
- Compare extracted Burnaby rules against a manually prepared gold standard
- Once the Burnaby pipeline is stable, test the same workflow on another municipality
- Continue clarifying how the final extracted rules should connect to the GIS map application
- Add a clearer review workflow for rules that are ambiguous, exception-based, or difficult to verify
