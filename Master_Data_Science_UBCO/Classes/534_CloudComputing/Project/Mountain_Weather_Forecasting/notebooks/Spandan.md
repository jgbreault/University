# Spandan's Work Notebook

Jan 14
- Met with the group to define project scope and select an API.
- We decided to split the work for this project.
- Contributed to early discussions. Supported the decision to use the Open-Meteo API due to its free access, clear documentation, and suitability for reproducible workflows. 

Jan 15
- Reviewed initial wrapper prototype and respiratory structure.
- Focused on understanding the planned function interface.

Jan 16
- Assisted with early code reviews.
- Identified the importance of robust input validation (latitude, longtitude ranges, date order) to prevent silent API failures and confusing user errors.

Jan 17
- Reviewed Open-Meteo documentation to understanding required parameters.

Jan 18
- Began drafting documentation notes.
- Outlined how error handling and validation should be explained clearly in the README.

Jan 19

- Implemented error handling logic for user inputs -> latitude and longtitude range checks, start and end data validation, added clear error messages.

Jan 20
- Tested the functions using invalid and edge case inputs.
- Refined the validation logic so errors are triggered early and clearly, before any API request is made.

Jan 21
- No project work.

Jan 22
- Helped review the repository after merges and conflict resolution.
- Checked that previously added validation and documentation changes were present after updates from other branches.

Jan 23
- Continued improving error handling and tested additional edge cases. Ensured error messages were clear and informative for users rather than generic API failures.

Jan 24
- Reviewed the structure of the README and suggested seperating usage instructions from error handling explanations to make the documentation easier to follow.

Jan 25
- Focused on documentation.
- Updated the README to clearly describe validation rules, error handling behaviour, and required inputs so users understand why error occur.

Jan 26
- Checked compatibility of the validation logic with newer functionality added by teammates, including mountain-based filtering and forecast comparison functions.

Jan 27
- Assisted a teammate with troubleshooting a corrupted local file.
- Verified the repository state after reverting and re-adding changes to ensure nothing was lost.
 
 Jan 28
 - Made substantial updates to the README.
 - Included clarifying date validation atitude/longitude constraints, and dependency requirements.
 - Merged documentation changes via pull request.
 
Jan 29
- Reviewed the vignette and made small adjustments. 
 
Jan 30
- Tested the package using real coordinates to confirm that validation, error handling, and outputs all behave as expected.
 
Jan 31
- Discussed where we will meet next day for the project.

Feb 1
- Final team meeting before submission.
- Reviewed the final presentation slides and ensured documentation and error contributions were accurately represented.

 