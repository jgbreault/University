# Jamie's Work Notebook

**Jan 14**
- Met with group to decide on the project scope and API selection. 
- Selected the Open-Meteo API due to its free tier, ease of use for beginners, and comprehensive weather variables (temperature, snowfall, wind speed).
- Established team roles; I took the lead on the core API wrapper development. Pushed contribution document to git repo.
- [Commit](https://github.com/spandandey12/Data534_project/commit/9a28d8bd8299e72635cd533f0afeaaa1cf8b0fc1)

**Jan 15**
- Initialized the base R wrapper code in a Jupyter Notebook environment for rapid prototyping.
- Developed `get_forecast_raw` using the `httr2` package to handle API queries.
- Implemented `get_forecast` to parse JSON into structured dataframes, handling both hourly and daily resolutions.
- Added preliminary plotting logic and structured the project directory for future R package conversion.
- [Commit](https://github.com/spandandey12/Data534_project/commit/be9ee4f3163b5a377fe0bd3cf96aebd5f0b89b51)

**Jan 16**
- Conducted a code review of the initial wrapper. 

**Jan 17**
- Explored the Open-Meteo API documentation further to determine default variables.
- Defined `default_variables` (rain, snowfall, cloud cover, etc.) to simplify the user experience, allowing beginners to get relevant data without manually specifying parameters.

**Jan 18**
- Drafted the project proposal report.

**Jan 19**
- Finalized the project proposal.

**Jan 20**
- Prepared presentation slides for the proposal.

**Jan 21**
- No work.

**Jan 22**
- Presented proposal to the class and received feedback from the instructor regarding "uniqueness."
- Shifted focus from historical data to real-time forecasting. This allows mountaineers to use the tool for trip planning.
- Focused on the "Gap Analysis"—noting that while `ropenmeteo` exists, there isn't a package specifically catering to mountain summit comparisons.
- Refined the logic for the `forecast_mountains` function to ensure it could handle different `time_resolution` arguments dynamically.
- Identified a need for a mountain-specific dataset. Researched and sourced the Andrew Kirmse 2023 prominence dataset to ensure our "mountaineering" niche was data-backed.
- Created visual representations of how the `forecast_mountains` function would iterate through mountain lists to provide a side-by-side comparison.
- Integrated the mountain summit dataset logic: merged mountain filtering with API calling.
- [Commit](https://github.com/spandandey12/Data534_project/commit/426bc95a3fe283cf73f024d36363fa84d42242ef)

**Jan 23**
- Began drafting the `get_nearest_mountains` function.
- Refined the methodology section, specifically how we would calculate distances using the `geosphere` library and `distHaversine` formula.
- Added `prominence_threshold` and `elevation_threshold` as parameters. This is crucial for mountaineers who only want to find "significant" peaks rather than small hills.

**Jan 24**
- Debugging session for the `geosphere` integration.
- Worked on converting the distance output from `distHaversine` (meters) to a more user-friendly kilometers format, rounding to one decimal place for clarity.

**Jan 25**
- Documentation planning.

**Jan 26**
- Researched how to mock API responses to test `get_forecast` without hitting the Open-Meteo rate limits during development.

**Jan 27**
- Collaborative Troubleshooting: Helped a teammate resolve a corrupted local file.
- Reverted to a previous commit and added changes manually from there.

**Jan 28**
- Substantial README update.
- Documented all four core functions (`get_forecast_raw`, `get_forecast`, `get_nearest_mountains`, and `forecast_mountains`).
- Explicitly stated the data source (Andrew Kirmse) to ensure proper attribution.
- Ensured all dependencies (`httr2`, `ggplot2`, `readr`, `geosphere`) were correctly listed.
- [Commit](https://github.com/spandandey12/Data534_project/commit/7149daa768982bf1be8ca29dfe9f52f29bd0635d)

**Jan 29**
- Refined the `forecast_mountains` loop.
- Optimized the way the dataframe is initialized using `rownames(mountain)` to ensure the output table is easy for users to read at a glance.

**Jan 30**
- Review of the package vignette.
- Tested the code with coordinates for UBCO (49.2593, -123.2475).

**Jan 31**
- No work.

**Feb 1**
- Final team meeting before submission. Helped with package structure to make the project an R package.
- Reviewed the final presentation slides and synchronized the package versioning.

**Feb 2**
- Final presentation to the class.
