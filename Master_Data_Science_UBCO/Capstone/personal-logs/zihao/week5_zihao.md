# Week 5

## Summary
This week, my main focus was on preparing for and delivering the project presentation, while continuing to improve the rule extraction pipeline. I spent significant time building the presentation slides and rehearsing, then presenting our progress and approach. On the technical side, I worked on optimizing the existing pipeline and ran a new round of experiments on table extraction, which is one of the hardest parts of parsing zoning bylaw documents. I also researched the existing rule extraction system already built by PIBC to understand how their current approach works and where our pipeline can align with or improve on it. I attended the weekly team meeting as well.

## Tasks
- Prepared the **project presentation**, including building slides, organizing the storyline, and rehearsing the delivery
- Summarized the current state of the rule extraction pipeline and results for the presentation audience
- Delivered the **presentation** and answered questions about the pipeline design, accuracy, and next steps
- Continued **optimizing the rule extraction pipeline** to improve robustness and consistency across municipalities
- Ran a new round of **table extraction experiments** focused on parsing complex zoning tables more reliably
  - Tested a geometry-first table flattening approach for handling structured bylaw tables
  - Compared extraction results across different table layouts and formats
- Researched the **existing rule extraction system built by PIBC**, reviewing how their current approach structures and extracts zoning rules
- Identified overlaps and differences between PIBC's system and our pipeline to inform future design decisions
- Attended the weekly internal team meeting to discuss progress and coordinate next steps

## Time
- Presentation preparation (slides and rehearsal): 4 hours
- Delivering the presentation and Q&A: 4 hours
- Pipeline optimization and refinement: 12 hours
- New table extraction experiments: 13 hours
- Researching PIBC's existing rule extraction system: 6 hours
- Team meeting: 1 hour

**Total: 40 hours**

## Challenges
- Table extraction remains one of the most difficult parts of the pipeline. Zoning tables vary widely in layout, merged cells, and nested structure, which makes consistent parsing hard across different municipalities.
- The geometry-first table flattening approach showed promise but still struggles with irregular or visually complex tables, so more iteration is needed before it is reliable.
- Optimizing the pipeline for one city's bylaw format sometimes reduces accuracy for another, so balancing robustness across formats continues to be a challenge.
- Understanding PIBC's existing rule extraction system took time, and it is still not fully clear how much of their approach we should adopt versus replace with our own pipeline.
- Aligning our extraction schema with PIBC's existing system may require further clarification on their expectations and standards.

## Next Steps
- Continue refining the table extraction approach, especially the geometry-first flattening method, to handle more complex table structures
- Further optimize the pipeline to improve cross-municipality robustness without sacrificing accuracy on individual cities
- Apply insights from PIBC's existing rule extraction system to improve our own schema and extraction logic
- Incorporate feedback received during the presentation into the next iteration of the pipeline
- Continue testing the pipeline on additional municipalities and table-heavy bylaw documents
- Clarify with the partner how closely our output should align with PIBC's existing rule extraction format
