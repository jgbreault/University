# Automated Laneway House Feasibility Dashboard

This project converts municipal zoning bylaws into a structured, verifiable rule
layer and uses it to determine — parcel by parcel — whether a laneway home can
legally be built, surfaced through an interactive GIS dashboard with traceable
evidence for every rule.

## Team Members

* Jamie Breault - GIS Lead
* Sasivimol Sirijangkapattana - Dashboard Lead
* Zihao Sheng - Rule Extraction Lead
* Yusen Rong - Rule Verification Lead

## Team Charter

[Link to Team Charter](./team_charter.docx)

## Description

Municipal zoning bylaws define the rules that govern land development — building
height limits, setbacks, density, lot coverage, permitted uses, and accessory
dwelling requirements. For laneway homes, these rules determine whether a
structure is legally feasible on a given parcel and what form it may take. In
practice, applying these rules at scale is hard: bylaws are published as long PDF
documents, tables, amendments, and zoning schedules, with different terminology
and update cycles across municipalities. Checking whether a single parcel can
support a laneway home is still largely manual — a practitioner must identify the
parcel, confirm its zoning, locate the relevant sections, interpret the rules,
and translate them into spatial constraints. Our project builds a practical
prototype that automates this: a dashboard that displays city lot information on
a GIS map, lets a user select a lot, and shows whether a laneway home can be
built there, with the supporting bylaw evidence attached. Burnaby, Vancouver,
and Calgary are prioritized as the first prototype cities to support future
generalization across BC municipalities.

We built an end-to-end automated pipeline with four stages, guided by a single
principle: **extraction proposes, verification proves, and GIS consumes only
verified rules.**

* **Extract** — a large language model reads the bylaw PDF and pulls out
  candidate rules (height, setbacks, lot coverage) from both text and complex
  tables.
* **Verify** — a separate, deterministic checker approves only rules with direct
  source evidence, routing uncertain cases to human review rather than relaxing
  the standard.
* **GIS** — verified rules are spatially applied to parcel data to label lot
  boundaries, generate buildable areas, and fit building footprints per lot.
* **Visualize** — verified rules and GIS parcel attributes are combined and
  displayed in an interactive Felt-based dashboard where a user selects any lot
  and instantly sees the applicable rules and building constraints.

### Repository Structure

* `code/` — extraction, verification, and GIS source (see `code/README.md`)
* `code/burnaby_rule_verification_prototype/` — verification + GIS rule contract
* `code/gis_files/` — GIS scripts, per-city parameters, and buildable-area logic
* `proposal/`, `final-report/` — proposal and final deliverables
* `guidelines/`, `weekly-updates/`, `personal-logs/` — course process artifacts
* `all.md` — plain-language guide to the verification workflow

The single file GIS should consume is the verified rule contract, e.g.
`code/burnaby_rule_verification_prototype/outputs/burnaby_r1_slim_pipeline5_registry/gis_rule_contract.json`.

## Data Sources

The project draws on two kinds of public, open data. The first is municipal
zoning bylaw documents — official PDFs such as Calgary's Land Use Bylaw 1P2007,
along with Burnaby and Vancouver bylaws — which contain the legal rules (height,
setbacks, lot coverage, accessory dwelling requirements) for the targeted
residential zones (e.g. Burnaby R1, Vancouver RS, Calgary R-CG). These documents
are the source of truth: every rule the system uses is traced back to a specific
page and quoted passage. The second is municipal GIS data published through each
city's open data portal, including parcel boundaries, street and lane
centrelines, building footprints, and zoning designations. The extraction and
verification stages transform the bylaw PDFs into a structured, verified rule
contract (`gis_rule_contract.json`), and the GIS stage joins those rules to the
spatial parcel data to compute buildable areas. All data is publicly available
open government data, so there are no personal-privacy or confidentiality
concerns; the main data challenges are differing schemas and update cycles
between municipalities.

## Acknowledgements and References

* **Project partner:** Green Metrics Technology
* **Course:** DATA 599 Capstone, UBC Okanagan MDS — Instructors Dr. Scott
  Fazackerley and Dr. Irene Vrbik; TAs Canruo Shen and Bakdauren Narbayev
* **Data sources:** City of Burnaby, City of Vancouver, and City of Calgary open
  data portals and published zoning/land-use bylaws
* **Tools:** QGIS, Felt, Python, and large language model APIs for rule extraction
