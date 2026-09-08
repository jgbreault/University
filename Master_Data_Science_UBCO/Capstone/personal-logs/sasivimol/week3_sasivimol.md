# Week 3

## Summary
Focused on exploring and experimenting with different approaches 
for LLM-based rule extraction from laneway home bylaw PDFs, 
with the goal of finding a scalable solution across BC municipalities.

## Tasks
- Presented weekly project update
- Started building a prototype rule extraction pipeline in 
  Jupyter notebook — currently testing with max_lot_coverage 
  across 3 cities as an initial experiment
- Explored different parsing approaches (regex vs LLM) and found 
  that a universal LLM parser may be more promising for handling 
  varied PDF formats, though this is still being evaluated
- Began designing the pipeline with scalability in mind — 
  experimenting with a city config layer so new cities can be 
  added without major code changes
- Participated in team discussion on RAG vs scraper + LLM — 
  shared findings from prototype to help inform the decision

## Time
- Pipeline design and prototyping: 25 hours
- Team discussions and architecture review: 2 hours
- Bylaw research (zone validation, cross-references): 5 hours
- Presentation preparation: 5 hours

**Total: 37 hours**

## Challenges
- Each city has different PDF format and bylaw structure — 
  still figuring out the best way to handle this generically
- Burnaby's collapsed table format is difficult to parse reliably
- Still in early stages of finding the right balance between 
  extraction accuracy and scalability

## Next Steps
- Continue experimenting with block-cutting for large PDFs
- Set up local Ollama for testing
- Build ground truth specs for max_lot_coverage to evaluate 
  extraction accuracy
- Iterate based on test results before scaling further
