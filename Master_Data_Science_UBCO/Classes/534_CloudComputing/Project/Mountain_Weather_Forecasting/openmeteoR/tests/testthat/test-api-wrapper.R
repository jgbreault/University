test_that("load_mountains returns a non-empty data frame with key columns", {
  mountains <- openmeteoR:::load_mountains()

  expect_s3_class(mountains, "data.frame")
  expect_gt(nrow(mountains), 0)

  expect_true(all(
    c("latitude", "longitude", "prominence", "elevation") %in% names(mountains)
  ))
})

test_that("check_lat_lon accepts valid coordinates", {
  expect_silent(openmeteoR:::check_lat_lon(49, -119))   # Kelowna 附近
})

test_that("check_lat_lon rejects invalid latitude", {
  expect_error(
    openmeteoR:::check_lat_lon(100, -119),
    "latitude must be between -90 and 90"
  )
})

test_that("check_lat_lon rejects invalid longitude", {
  expect_error(
    openmeteoR:::check_lat_lon(49, -200),
    "longitude must be between -180 and 180"
  )
})

test_that("check_date_forecast accepts a valid range within 16 days", {
  today <- Sys.Date()
  start <- today
  end   <- today + 3

  res <- openmeteoR:::check_date_forecast(start, end)

  expect_s3_class(res$start_date, "Date")
  expect_s3_class(res$end_date, "Date")
  expect_lte(res$start_date, res$end_date)
})

test_that("check_date_forecast rejects start_date after end_date", {
  today <- Sys.Date()
  expect_error(
    openmeteoR:::check_date_forecast(today + 5, today),
    "start_date must be before or equal to end_date"
  )
})

test_that("check_date_forecast rejects end_date too far in the future", {
  today <- Sys.Date()
  too_far <- today + 30

  expect_error(
    openmeteoR:::check_date_forecast(today, too_far),
    "end_date is too far in the future"
  )
})

