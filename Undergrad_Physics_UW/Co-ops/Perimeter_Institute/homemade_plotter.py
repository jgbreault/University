from pylab import *
from matplotlib import *

input_file=raw_input("Enter ascii file to be plotted: ")
dataMatrix1 = genfromtxt(input_file)

x = dataMatrix1[:,0]
y = dataMatrix1[:,1]

plot(x, y, 'b.', linestyle='')

xlabel('Time (s)')
ylabel('Intensity (Arbitrary Units)')

savefig('plot.png')
show()
