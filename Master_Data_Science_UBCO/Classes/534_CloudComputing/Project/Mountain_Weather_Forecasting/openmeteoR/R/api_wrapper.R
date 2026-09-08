#' Internal helper: load mountains dataset from installed package
#'
#' Loads `inst/extdata/mountains.csv` shipped with the package.
#'
#' @return A data.frame of mountains.
#' @keywords internal
load_mountains <- function() {
  f <- system.file("extdata", "mountains.csv", package = "openmeteoR")

  if (f == "") {
    stop("mountains.csv not found in installed package.")
  }

  utils::read.csv(f, header = TRUE)
}

# The default weather variables fetched by the API, all are hourly
default_variables <- c(
  "temperature_2m",
  "rain",
  "snowfall",
  "wind_speed_10m",
  "relative_humidity_2m",
  "snow_depth",
  "cloud_cover"
)

# ---- Validation helpers ----

#' Internal helper: validate latitude / longitude
#'
#' @param latitude numeric scalar
#' @param longitude numeric scalar
#' @return NULL (throws error if invalid)
#' @keywords internal
check_lat_lon <- function(latitude, longitude) {
  if (!is.numeric(latitude) || length(latitude) != 1 || is.na(latitude)) {
    stop("latitude must be a single numeric value (not NA).")
  }
  if (!is.numeric(longitude) || length(longitude) != 1 || is.na(longitude)) {
    stop("longitude must be a single numeric value (not NA).")
  }
  if (latitude < -90 || latitude > 90) {
    stop("latitude must be between -90 and 90.")
  }
  if (longitude < -180 || longitude > 180) {
    stop("longitude must be between -180 and 180.")
  }
}

#' Internal helper: validate forecast date range
#'
#' Open-Meteo Forecast API supports forecasts up to 16 days ahead.
#'
#' @param start_date Date or string coercible to Date
#' @param end_date Date or string coercible to Date
#' @return list(start_date=Date, end_date=Date)
#' @keywords internal
check_date_forecast <- function(start_date, end_date) {
  start_date <- as.Date(start_date)
  end_date   <- as.Date(end_date)

  if (is.na(start_date) || is.na(end_date)) {
    stop("start_date and end_date must be valid dates like '2026-01-23'.")
  }
  if (start_date > end_date) {
    stop("start_date must be before or equal to end_date.")
  }

  max_end <- Sys.Date() + 16
  if (end_date > max_end) {
    stop(sprintf(
      "end_date is too far in the future. Forecast API supports up to 16 days ahead (max end_date = %s).",
      max_end
    ))
  }

  list(start_date = start_date, end_date = end_date)
}

# ---- Core API helpers ----

#' Internal: call Open-Meteo forecast endpoint and return raw httr2 response
#'
#' @param latitude numeric scalar
#' @param longitude numeric scalar
#' @param start_date Date/string
#' @param end_date Date/string
#' @param daily_variables character vector
#' @param hourly_variables character vector
#' @return httr2_response
#' @keywords internal
get_forecast_raw <- function(latitude,
                             longitude,
                             start_date,
                             end_date,
                             daily_variables = c(),
                             hourly_variables = c()) {

  check_lat_lon(latitude, longitude)

  dates <- check_date_forecast(start_date, end_date)
  start_date <- format(dates$start_date, "%Y-%m-%d")
  end_date   <- format(dates$end_date, "%Y-%m-%d")

  req <- httr2::req_url_query(
    httr2::request("https://api.open-meteo.com/v1/forecast"),
    latitude   = latitude,
    longitude  = longitude,
    start_date = start_date,
    end_date   = end_date,
    daily      = paste(daily_variables, collapse = ","),
    hourly     = paste(hourly_variables, collapse = ",")
  )

  response <- httr2::req_perform(req)

  if (httr2::resp_status(response) != 200) {
    err_json <- tryCatch(httr2::resp_body_json(response), error = function(e) NULL)

    if (!is.null(err_json) && !is.null(err_json$reason)) {
      stop(sprintf(
        "Open-Meteo API request failed (HTTP %s): %s",
        httr2::resp_status(response),
        err_json$reason
      ))
    } else {
      stop(sprintf(
        "Open-Meteo API request failed (HTTP %s).",
        httr2::resp_status(response)
      ))
    }
  }

  response
}

# ---- Public functions ----

#' Get weather forecast from Open-Meteo
#'
#' Fetches hourly or daily forecast data for a given latitude/longitude and date range.
#'
#' @param latitude numeric scalar
#' @param longitude numeric scalar
#' @param start_date Date or string coercible to Date
#' @param end_date Date or string coercible to Date
#' @param time_resolution "hourly" or "daily"
#' @param variables character vector of variable names
#'
#' @return A data.frame containing forecast time and requested variables.
#' @export
get_forecast <- function(latitude,
                         longitude,
                         start_date,
                         end_date,
                         time_resolution = "hourly",
                         variables = default_variables) {

  if (!time_resolution %in% c("hourly", "daily")) {
    stop('time_resolution must be "hourly" or "daily".')
  }

  if (!is.character(variables) || length(variables) < 1) {
    stop("variables must be a non-empty character vector.")
  }

  if (time_resolution == "hourly") {
    response <- get_forecast_raw(
      latitude         = latitude,
      longitude        = longitude,
      start_date       = start_date,
      end_date         = end_date,
      hourly_variables = variables
    )

    data_json <- httr2::resp_body_json(response)

    weather_data <- as.data.frame(lapply(data_json$hourly, function(x) unlist(x)))
    weather_data$time <- as.POSIXct(weather_data$time, format = "%Y-%m-%dT%H:%M")
  } else {
    response <- get_forecast_raw(
      latitude        = latitude,
      longitude       = longitude,
      start_date      = start_date,
      end_date        = end_date,
      daily_variables = variables
    )

    data_json <- httr2::resp_body_json(response)

    weather_data <- as.data.frame(lapply(data_json$daily, function(x) unlist(x)))
    weather_data$time <- as.Date(weather_data$time, format = "%Y-%m-%d")
  }

  weather_data
}

#' Get nearest mountains to an input location
#'
#' Finds the nearest mountains based on great-circle distance, after filtering by
#' prominence and elevation thresholds.
#'
#' @param latitude numeric scalar
#' @param longitude numeric scalar
#' @param num_mountains integer >= 1
#' @param prominence_threshold numeric >= 0
#' @param elevation_threshold numeric >= 0
#'
#' @return A data.frame of mountains (subset) with an added `distance_km` column.
#' @export
get_nearest_mountains <- function(latitude,
                                  longitude,
                                  num_mountains        = 5,
                                  prominence_threshold = 500,
                                  elevation_threshold  = 0) {

  check_lat_lon(latitude, longitude)

  if (!is.numeric(num_mountains) || length(num_mountains) != 1 || is.na(num_mountains) || num_mountains < 1) {
    stop("num_mountains must be a single number >= 1.")
  }
  num_mountains <- as.integer(num_mountains)

  if (!is.numeric(prominence_threshold) || length(prominence_threshold) != 1 || is.na(prominence_threshold) || prominence_threshold < 0) {
    stop("prominence_threshold must be a single number >= 0.")
  }

  if (!is.numeric(elevation_threshold) || length(elevation_threshold) != 1 || is.na(elevation_threshold) || elevation_threshold < 0) {
    stop("elevation_threshold must be a single number >= 0.")
  }

  mountains_all <- load_mountains()

  mountains_temp <- mountains_all[
    mountains_all$prominence >= prominence_threshold &
      mountains_all$elevation  >= elevation_threshold,
  ]

  if (nrow(mountains_temp) == 0) {
    stop("No mountains match your thresholds. Try lowering prominence_threshold/elevation_threshold.")
  }

  input_coord     <- c(longitude, latitude)
  mountain_coords <- mountains_temp[, c("longitude", "latitude")]

  distances <- round(geosphere::distHaversine(mountain_coords, input_coord) / 1000, 1)
  mountains_temp$distance_km <- distances

  mountains_sorted <- mountains_temp[order(mountains_temp$distance_km), ]

  utils::head(mountains_sorted, num_mountains)
}

#' Get forecasts for multiple mountains over a date range
#'
#' Given a mountains data.frame (must include latitude/longitude), fetches forecasts
#' for each mountain and returns a wide data.frame with time and one column per mountain.
#'
#' @param mountains data.frame containing columns `latitude` and `longitude`
#' @param start_date Date or string coercible to Date
#' @param end_date Date or string coercible to Date
#' @param time_resolution "hourly" or "daily"
#' @param weather_feature single variable name string (e.g. "temperature_2m")
#'
#' @return A data.frame: `time` column + one column per mountain rowname.
#' @export
forecast_mountains <- function(mountains,
                               start_date,
                               end_date,
                               time_resolution = "hourly",
                               weather_feature = "temperature_2m") {

  if (!is.data.frame(mountains) || nrow(mountains) == 0) {
    stop("mountains must be a non-empty dataframe.")
  }

  if (!all(c("latitude", "longitude") %in% names(mountains))) {
    stop("mountains must contain columns: latitude and longitude.")
  }

  if (!is.character(weather_feature) || length(weather_feature) != 1) {
    stop("weather_feature must be a single character string, e.g. 'temperature_2m'.")
  }

  if (is.null(rownames(mountains)) || any(rownames(mountains) == "")) {
    rownames(mountains) <- sprintf("mountain_%d", seq_len(nrow(mountains)))
  }

  mountain_weather <- data.frame()

  for (i in seq_len(nrow(mountains))) {
    mountain <- mountains[i, ]

    forecast <- get_forecast(
      latitude        = mountain$latitude,
      longitude       = mountain$longitude,
      start_date      = start_date,
      end_date        = end_date,
      time_resolution = time_resolution,
      variables       = weather_feature
    )

    if (!"time" %in% colnames(mountain_weather)) {
      mountain_weather <- data.frame(matrix(nrow = nrow(forecast), ncol = 0))
      mountain_weather$time <- forecast$time
    }

    mountain_column_name <- rownames(mountain)
    mountain_weather[[mountain_column_name]] <- forecast[[weather_feature]]
  }

  mountain_weather
}
