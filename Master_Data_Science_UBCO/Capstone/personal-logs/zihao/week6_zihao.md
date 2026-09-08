# Week 6

## Summary
This week focused on improving the rule extraction workflow and making the pipeline more practical for repeated city-level runs. The main work was reducing token usage, improving extraction speed, restructuring the extraction process around a RAG-style block representation, and generalizing the Calgary extraction logic so the same approach can be reused for other cities with less manual adjustment.

The rule extraction path was reviewed from block selection through final rule merging. Instead of sending a large number of loosely related blocks directly into the extraction stage, the workflow was refined to first organize candidate blocks into a more compact evidence structure. This helped keep the extraction focused on rules that are directly related to the target building type, while still retaining higher-level contextual rules such as dwelling-unit requirements when they apply.

## Tasks
- Prepared the weekly presentation slides summarizing current pipeline progress, extraction bottlenecks, and the updated optimization direction.
- Presented the weekly progress update and discussed the current rule extraction strategy with the team.
- Attended the weekly project meeting and reviewed next steps for pipeline generalization and output validation.
- Optimized token usage in the rule extraction process by reducing unnecessary candidate blocks, improving target-aware filtering, and avoiding extraction from blocks that were not relevant to the target building type.
- Reduced the estimated token cost by approximately 80% compared with the earlier extraction approach that processed a much broader set of candidate blocks.
- Improved extraction speed by narrowing the input set before API extraction and reducing redundant rule extraction calls.
- Shortened the estimated extraction runtime by approximately 60% through stricter block filtering, better candidate grouping, and fewer unnecessary LLM calls.
- Redesigned the overall extraction structure so selected blocks are first converted into a RAG-style structure before rule extraction.
- Organized block-level evidence into compact rule packages, including text blocks, table blocks, source references, target relevance, and higher-level semantic relationships.
- Improved the handling of target-specific rules and parent-category rules, such as regulations that apply to all dwelling units and should also apply to backyard suites or similar accessory dwelling types.
- Generalized the Calgary extraction workflow by reducing city-specific assumptions and moving toward a reusable target-aware extraction process.
- Compared Calgary logic with Vancouver and Burnaby cases to check whether the generalized block selection and extraction strategy could support multiple cities without adding a separate custom builder for each one.
- Reviewed extracted rule outputs and identified cases where irrelevant general zoning rules were entering the pipeline too early.
- Updated the extraction strategy so irrelevant blocks are filtered before rule extraction instead of being cleaned only after extraction.
- Documented the revised pipeline direction and key design decisions for the next stage of implementation.

## Time
- Weekly presentation PPT preparation: 3 hours
- Weekly presentation delivery: 1 hour
- Weekly team meeting: 1 hour
- Token usage and cost optimization for rule extraction: 9 hours
- Extraction speed optimization and redundant call reduction: 7 hours
- RAG-style block structure design and extraction workflow update: 10 hours
- Calgary extraction generalization and cross-city comparison: 7 hours
- Documentation, output review, and next-step planning: 2 hours

**Total: 40 hours**

## Challenges
One major challenge was balancing recall and precision during block selection. If the filtering is too broad, the pipeline sends many unrelated zoning blocks into the extraction stage, which increases token cost and makes the final review harder. If the filtering is too strict, the pipeline may miss parent-level rules that still apply to the target building type.

Another challenge was making the Calgary workflow more general without encoding too many city-specific section names or manual exclusions. The updated direction is to rely more on target-aware block structure, semantic relevance, and compact evidence packages instead of maintaining a separate custom builder for every new city.

## Next Steps
- Continue validating the generalized extraction process across Calgary, Vancouver, and Burnaby.
- Refine the RAG-style block package format so it can support both text and table extraction consistently.
- Improve filtering for parent-category rules that apply to the target building type indirectly.
- Add more systematic checks for whether extracted rules are directly relevant, indirectly relevant, or unrelated.
- Continue reducing unnecessary API calls while preserving important zoning and building regulation coverage.
