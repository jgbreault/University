# Week 3

## Summary
This week, I mainly worked on building the core rule extraction pipeline for zoning bylaw documents. The focus was on creating a more structured workflow for extracting bylaw content into blocks, preparing those blocks for normalization, and testing how the pipeline performs across different municipalities. I also explored replacing the locally deployed Qwen 3.5 9B model with an external LLM API such as Gemini API, since the local model is not reliable enough for detailed rule extraction and normalization. In addition, I started rule extraction work for the City of Calgary and attended both partner and internal team meetings.

## Tasks
- Developed the main **rule extraction pipeline** for zoning bylaw documents
- Built and tested the block extraction workflow for municipal bylaw PDFs
- Worked on separating zoning documents into structured blocks for later normalization
- Improved the pipeline design for handling:
  - section headings
  - tables
  - zoning rule blocks
  - cross-city bylaw differences
  - rule source tracing
- Tested rule extraction and normalization performance across existing cities
- Evaluated the limitations of the locally deployed Qwen 3.5 9B model
- Explored using **Gemini API** as a possible replacement for the local LLM normalization step
- Continued refining the idea of using an external LLM API for more reliable rule extraction
- Started rule extraction work for the **City of Calgary**
- Reviewed Calgary zoning bylaw structure and began identifying relevant residential zoning rules
- Compared Calgary’s rule structure with the existing municipalities
- Attended a meeting with the project partner to discuss project direction and expectations
- Attended internal team meetings to discuss technical progress, pipeline design, and next steps

## Time
- Main rule extraction pipeline development: 15 hours
- Block extraction workflow testing and debugging: 6 hours
- Rule normalization design and pipeline refinement: 4 hours
- Testing Gemini API as a possible replacement for Qwen 3.5 9B: 3 hours
- Calgary rule extraction and bylaw review: 4 hours
- Partner meeting: 1 hour
- Internal team meetings and coordination: 2 hours

**Total: 35 hours**

## Challenges
- The main rule extraction pipeline is working, but it is still not accurate enough across all cities. For some existing municipalities, the pipeline can reach close to 100% accuracy, but for others the accuracy can drop to around 65%. This shows that the current approach still lacks robustness.
- The pipeline performs differently depending on the structure and formatting of each city’s bylaw documents. Some documents have clearer section and table structures, while others are harder to parse consistently.
- The local Qwen 3.5 9B model is still not reliable enough for detailed zoning rule normalization. It can work for simpler cases, but it struggles with complex table structures, exceptions, conditions, and precise legal wording.
- Future normalization should likely use a stronger LLM API instead of a locally deployed low-quantization model. However, this requires the project partner to provide access to an API such as OpenAI, which was not available this week.
- The current pipeline still lacks a proper review or verification stage. A review process should be added to improve the credibility and trustworthiness of extracted rules.
- It is still unclear whether the partner expects the system to include web scraping for finding bylaw documents online, or whether they plan to manually download the bylaw files and provide them to our pipeline.
- More clarification is needed from the partner about the expected input format, final deliverable, and the level of automation required.

## Next Steps
- Obtain access to the OpenAI API from the project partner and begin adapting the pipeline to use a stronger external LLM for rule normalization
- Replace or supplement the local Qwen 3.5 9B model with an API-based LLM in the core normalization step
- Continue improving the overall rule extraction pipeline to make it more reliable across different municipal bylaw formats
- Add a review and verification workflow to check extracted rules before they are used in the final system
- Improve the normalization schema so that conditions, exceptions, formulas, and source references are handled more consistently
- Continue testing the pipeline on more municipalities, including Calgary
- Clarify with the partner whether web scraping is required for collecting bylaw documents, or whether documents will be provided manually
- If time allows, start building an additional **RAG-based AI assistant** that can answer zoning questions based on city and parcel information, such as whether a user can build a proposed structure and what conditions or restrictions apply
