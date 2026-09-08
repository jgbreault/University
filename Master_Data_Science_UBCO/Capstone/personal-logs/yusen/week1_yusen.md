# Week 1 Work Log — 32 Hours

**Project:** Automated Municipal Bylaw Interpretation System

## Day 1 — Project Planning and Scope Definition
**Hours: 6**

The first day was spent discussing the overall direction of the project with the team. The core idea is to build a system that can determine whether a proposed building can be constructed on a given parcel, based on the zoning bylaws of a municipality.

One of the first things we agreed on was to keep the first version of the system simple. Instead of trying to handle every possible zoning rule, we decided to focus on a 2D feasibility check using four basic rules: minimum front yard setback, rear yard setback, side yard setback, and maximum site coverage. This made the project feel much more manageable than trying to solve the full problem at once.

## Day 2 — Background Research and Technical Direction
**Hours: 6**

I spent this day researching how AI and NLP can be used to read and extract information from legal documents like zoning bylaws. One of the main things we had to decide was whether to send full bylaw PDFs directly to an LLM, or to build a retrieval system that finds the relevant sections first before asking the model.

After looking into both options, we concluded that direct PDF prompting could work for simple cases, but would likely struggle with long and messy bylaw documents. The more reliable approach is RAG — Retrieval-Augmented Generation — where the system first finds the relevant bylaw clauses and then sends only those to the model. This reduces the chance of the model reading the wrong section or missing an important exception.

## Day 3 — Dataset and Data Source Investigation
**Hours: 7**

This was one of the more important days of the week. I started researching what data the system actually needs to work, and quickly realized that a bylaw PDF alone is not enough. To check whether a building can fit on a lot, the system also needs to know the parcel location, the zoning district that applies to that address, and the actual dimensions of the lot.

This means the project needs three main sources: zoning bylaw documents, zoning district GIS data, and parcel geometry files. All three are generally available through municipal open data portals, but the format and structure varies a lot between cities. Some cities publish one large consolidated zoning PDF, while others split the bylaw into many separate documents. We decided to start with cities that have a single consolidated PDF, since that is much easier to process consistently.

## Day 4 — Edge Case and Scope Analysis
**Hours: 6**

Once the dataset direction was clearer, I spent time thinking through the edge cases — the situations where the system might give a wrong answer if we are not careful.

The two biggest ones we decided to exclude from the first version are height rules and corner lots. Height is surprisingly hard because every city defines it differently, and most bylaws include exemptions for things like chimneys, elevators, and mechanical equipment. Corner lots are also complicated because they often have different setback rules on the flanking street. Rather than trying to handle these cases badly, we agreed that the system should detect them and return "Needs human review" instead.

There are likely other edge cases we have not thought of yet — irregular lots, multiple zoning districts on one parcel, heritage overlays, and so on. These will be identified and handled as we go.

## Day 5 — Proposal Writing and System Design
**Hours: 7**

The last day of the week was focused on writing up what we had figured out. I drafted the methods section, the dataset section, and the database justification, and also thought through the overall pipeline design more carefully.

The system we are proposing works in five steps: collect the bylaw documents, break them into searchable chunks, store those chunks in a vector database, retrieve the relevant clauses when a user asks a question, and then use an LLM to extract the actual rule values. A separate code-based checker then compares those values against the user's building plan and returns a result: likely buildable, not buildable, or needs human review.

By the end of the week, the scope felt much clearer. The goal for the prototype is not to solve every possible legal condition, but to demonstrate that the full pipeline can work reliably for a small set of well-defined cases.

## Total Hours

| Day | Activity | Hours |
|---|---|---|
| Day 1 | Project planning and scope definition | 6 |
| Day 2 | Background research and technical direction | 6 |
| Day 3 | Dataset and data source investigation | 7 |
| Day 4 | Edge case and scope analysis | 6 |
| Day 5 | Proposal writing and system design | 7 |
| | **Total** | **32** |

## Week 1 Summary

The first week was mostly about narrowing the project down to something realistic. I came into it with a broad idea — build a system that tells you if your building can be built — and by the end of the week we had a much clearer picture of what that actually requires technically. The key insight was that the system needs more than just bylaw PDFs. It also needs zoning district data and parcel geometry, which are both available through open data portals but require their own processing steps.

The next step is to pick one city, collect its bylaw PDF and open data files, and start testing whether the pipeline can correctly retrieve and extract basic setback and coverage rules.
