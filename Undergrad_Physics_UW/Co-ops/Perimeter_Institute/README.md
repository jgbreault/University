# FRB_finder

Refer to SIGPROC_CrashCourse.odt for terms and definitions.

FRB_finder.py converts simulated FRB data produced by simpulse to a filterbank file, allowing it to be used with SIGPROC. It is imporant to know if SIGPROC's hunt program can find FRBs produced by simpulse. To test this, FRB_finder.py can run the filterbank file through hunt and plot the SNR of the best FRB it finds at each DM. That is the plot seen below to the left. Below to the right is the same plot execpt the data was produced by SIGPROC's fake program instead of simpulse. Care was taken to make sure the data sets produced by simpulse and fake were as similar as possible.
