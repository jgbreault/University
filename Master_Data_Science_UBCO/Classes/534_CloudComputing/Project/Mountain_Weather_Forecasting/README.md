# Mountain Weather Forecasting

This R package provides functions to find nearby mountains summits and to compare weather forecasts of those locations. This would be of interest to mountaineers, to help them decide which mountains to climb near their home or a destination. Weather forecasting is done using the [Open-Meteo API](https://open-meteo.com/). The mountain data is from [Andrew Kirmse](https://www.andrewkirmse.com/prominence-update-2023) in the form of a csv file. Although R wrappers for this API do exist already (such as [ropenmeteo](https://github.com/FLARE-forecast/ropenmeteo) and [openmeteo](https://tpisel.r-universe.dev/openmeteo)), none of these other wrappers have added functionality specific to mountaineering. A vignette is provided as an example of how to use the package. Unit tests are ran using GitHub Actions for continuous integration. Author contributions are outlined in `contributions.md`.


We have gone public. Anyone can install this package in Windows, Mac, or Linux environments by running this line in R:
`devtools::install_github("spandandey12/Data534_project", subdir = "openmeteoR")`

**Dependencies:** `httr2`, `ggplot2`, `readr`, `geosphere`

**Authors:**
* Jamie Breault - 26478172
* Pokai Tseng - 96500053
* Spandan Dey - 19289180

---

## Project Structure

```
Data534_project/
├── notebooks/                       # Daily logs of contributions and progress
│   ├── Jamie.md
│   ├── Rex.md
│   └── Spandan.md
├── openmeteoR/                      # Core R Package
│   ├── DESCRIPTION                  # Package metadata and dependencies
│   ├── NAMESPACE                    # Exported functions
│   ├── R/                     
│   │   └── api_wrapper.R            # R function definitions
│   ├── tests/                     
│   │   └── testthat/                
│   │       └──test-api-wrapper.R    # Unit tests
│   └── data/   
│       └── inst/                  
│           └── extdata/
│               └── mountains.csv    # Dataset of mountain summits
├── misc/      
│   ├── 534-Final_Presentation.pptx  # Powerpoint for final class presentation
│   └── passed_unit_tests.jpeg       # Screenshot proving that unit tests pass
├── vignette                         # Example of package use
├── contributions.md                 # Document to outline author contributions
└── README.md                        # Project documentaion
```

---

## Functions

## `get_forecast`
Fetches weather data for a specific location and returns a structured dataframe with a formatted time column.

* **latitude / longitude**: (Numeric) Target coordinates.
* **start_date / end_date**: (String) Forecast date range.
* **time_resolution**: (String) Either `"hourly"` or `"daily"`.
* **variables**: (Vector) The weather metrics to retrieve (e.g., temperature, rain, snowfall).

#### Returns
* **data.frame**: It contains a time column and additional columns for every weather variable passed in the variables arguments.

#### Error Handling:
* Ensures **time_resolution** is either **"hourly"** or **"daily"** or else stops with an error
* Ensures **variables** is a non-empty character vertor or else stops with an error.
* Uses get_forecast_raw() to handle coordinate and date validation along with HTTP error checking.

#### Unit Testing:
* Tests input validation for resolution and varaibles using testthat.
* Mocks API responses to validate parsing logic for hurly and daily forecasts.
* Verifies output structure and column naming.
* Confirms error propafation from get_forecast_raw().

## `get_nearest_mountains`
Finds the closest mountain peaks to a specific coordinate that are above elevation and prominence thresholds.

* **latitude / longitude**: (Numeric) The reference point to measure distance from.
* **num_mountains**: (Integer) Number of results to return (Default: 5).
* **prominence_threshold**: (Numeric) Minimum prominence in meters (Default: 500).
* **elevation_threshold**: (Numeric) Minimum elevation in meters (Default: 0).

#### Returns
* **data.frame**: It contains the location and elevation of the nearest mountains.

#### Error Handling:
* Validates **latitude** and **longitude** using **check_lat_lon()**.
* Validates **num_mountains** is a single numeric value **>1**
* Validates **prominence_threshold** and **elevation_threshold** are single numeric values **>0**.
* If no mountains meet the filtering thresholds, stops with: **"No mountains match your thresholds. Try lowering prominence_threshold/elevation_threshold."**

#### Unit Testing:
* Tests argument validation and threshold checks using testthat.
* Verifies filtering and distance-based ordering logic.
* Covers no-match edge cases with clear error messages.
* Confirms output structure and column names.

## `forecast_mountains`
A wrapper that iterates through a dataframe of mountains to create a comparative weather table.

* **mountains**: (Dataframe) A dataframe containing mountain coordinates (typically the output of `get_nearest_mountains`).
* **start_date / end_date**: (String) Forecast date range.
* **time_resolution**: (String) Either `"hourly"` or `"daily"`.
* **weather_feature**: (String) The specific weather variable to extract into the final table (Default: `"temperature_2m"`).

#### Returns
* **data.frame**: It contains a time column and additional columns for every mountains being forecasted.

#### Error Handling:
* Ensures **mountains** is a non-empty dataframe.
* Ensures **mountains** contains **latitude** and **longtitude** columns.
* Ensures **weather_feature** is a single character string.
* If the mountains dataframe has missing/empty rownames, assigns default names (**mountain_1**, **mountain_2**,...) to ensure valid output column names.
* Relies on **get_forecast()**/**get_forecast_raw()** for coordinate/date/API error handling while looping through mountains.

#### Unit Testing:
* Test input validation for mountain data and weathers.
* Mocks API calls to validate looping and aggregation logic.
* Verifies output structure and column naming.
* Confirms proper error propagation.
