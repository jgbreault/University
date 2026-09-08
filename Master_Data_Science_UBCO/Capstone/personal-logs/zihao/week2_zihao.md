# Week 2

## Summary
Joined the new project team, kept up with the current project progress, and worked on understanding the overall project direction, existing workflow, zoning rule structure, and technical implementation plan. Continued refining zoning rules for selected municipalities and began testing how the extracted rules could be used in a rule-checking and RAG-based pipeline.

## Tasks
- Joined the project team and reviewed the overall project scope, current progress, and expected deliverables
- Discussed the project workflow and technical direction with teammates
- Refined the zoning rules for **Burnaby** and **Surrey**
- Added a more detailed description of **Surrey’s zoning rules**, especially related to R1 residential zoning and laneway home construction requirements
- Cross-checked the zoning rules for **Burnaby, Surrey, and Vancouver**
- Identified and validated the common requirements shared across the three municipalities
- Organized the extracted rules from the three cities into a **JSON-based rule format**
- Started designing a **rule-checking pipeline** for the discovered zoning rules
- Designed an initial workflow to validate user inputs against the extracted zoning rules
- Tested local RAG implementation using:
  - Qwen 2.5 7B
  - Qwen 3.5 9B
- Explored how local LLMs respond to zoning-related questions when provided with structured rule files

## Time
- Team onboarding and project review: 3 hours
- Rule refinement for Burnaby and Surrey: 6 hours
- Cross-checking Burnaby, Surrey, and Vancouver rules: 5 hours
- JSON rule formatting and structure design: 5 hours
- Rule-checking pipeline planning and testing: 5 hours
- Local RAG testing with Qwen models: 5 hours
- Team discussion and coordination: 3 hours

**Total: 32 hours**

## Challenges
- The smaller local LLM model, Qwen 2.5 7B, did not perform well for more complex zoning-related questions. While it could answer simple eligibility questions, its responses became unclear, overly generic, or logically weak when asked about detailed rule requirements.
- Qwen 3.5 9B showed stronger reasoning potential, but its thinking speed was too slow for practical interactive use in the current setup.
- A better balance is needed between model size, reasoning quality, and response speed.
- The GIS component still requires more research, especially on how zoning geometry, parcel information, and setback rules can be combined in a practical rule-checking workflow.
- It remains challenging to translate municipal bylaw language into structured rules that are both compact enough for RAG and precise enough for rule validation.

## Next Steps
- Confirm the final deliverable format with the team and client next Tuesday
- Define a clear product delivery plan for the remaining project timeline
- Continue improving the JSON rule structure for the three municipalities
- Refine the rule-checking pipeline and test it with more realistic user inputs
- Continue evaluating local LLM options to find a better balance between response quality and speed
- Further investigate how GIS data can be integrated with zoning and setback rules for spatial validation
