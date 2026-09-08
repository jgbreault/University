# tests/testthat.R

if (requireNamespace("testthat", quietly = TRUE)) {
  library(testthat)
  library(openmeteoR)
  
  test_check("openmeteoR")
} else {
  message("Skipping tests: 'testthat' is not installed.")
}
