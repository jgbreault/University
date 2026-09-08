import numpy as np
import os
import simpulse
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import subprocess


class FRB_finder:

    def write_bin(self, f, i):
        """
        Writes integers, floats, and strings to a file in binary. f is the file, i is the thing being written. 
        When writing a string to binary, the lenth of the string is written first.
        """

        assert type(i)==int or type(i)==str or type(i)==float
        if type(i)==int:
            f.write(np.uint32(i).tostring())
        if type(i)==float:
            f.write(np.float64(i).tostring())
        if type(i)==str:
            f.write(np.uint32(len(i)).tostring())
            f.write(i)


    def header_params(self, telescope_id=None, machine_id=None, data_type=None, rawdatafile=None, 
                     source_name=None, barycentric=None, pulsarcentric=None, az_start=None, 
                     za_start=None, src_raj=None, src_dej=None, tstart=None, tsamp=None, nbits=None, 
                     nsamples=None, fch1=None, foff=None, nchans=None, nifs=None, refdm=None, period=None):
        """
        Creates a dictionary containing all specified header paramerters. These parameters will be written 
        in the header of the filterbank file. Note that not all parameters must be specified.
        """

        header_params={}

        if telescope_id is not None:
            assert type(telescope_id) is int
            header_params['telescope_id'] = telescope_id
        if machine_id is not None:
            assert type(machine_id) is int
            header_params['machine_id'] = machine_id
        if data_type is not None:
            assert type(data_type) is int
            header_params['data_type'] = data_type
        if rawdatafile is not None:
            assert type(rawdatafile) is str
            header_params['rawdatafile'] = rawdatafile
        if source_name is not None:
            assert type(source_name) is str
            header_params['source_name'] = source_name
        if barycentric is not None:
            assert type(barycentric) is int
            header_params['barycentric'] = barycentric
        if pulsarcentric is not None:
            assert type(pulsarcentric) is int
            header_params['pulsarcentric'] = pulsarcentric
        if az_start is not None:
            assert type(az_start) is float
            header_params['az_start'] = az_start
        if za_start is not None:
            assert type(za_start) is float
            header_params['za_start'] = za_start
        if src_raj is not None:
            assert type(src_raj) is float
            header_params['src_raj'] = src_raj
        if src_dej is not None:
            assert type(src_dej) is float
            header_params['src_dej'] = src_dej
        if tstart is not None:
            assert type(tstart) is float
            header_params['tstart'] = tstart
        if tsamp is not None:
            assert type(tsamp) is float
            header_params['tsamp'] = tsamp
        if nbits is not None:
            assert type(nbits) is int
            header_params['nbits'] = nbits
        if nsamples is not None:
            assert type(nsamples) is int
            header_params['nsamples'] = nsamples
        if fch1 is not None:
            assert type(fch1) is float
            header_params['fch1'] = fch1
        if foff is not None:
            assert type(foff) is float
            header_params['foff'] = foff
        if nchans is not None:
            header_params['nchans'] = nchans
        if nifs is not None:
            assert type(nifs) is int
            header_params['nifs'] = nifs
        if refdm is not None:
            assert type(refdm) is float
            header_params['refdm'] = refdm
        if period is not None:
            assert type(period) is float
            header_params['period'] = period

        return header_params


    def array_2D_to_1D(self, time_series_2D, std_dev):
        """
        Converts a 2D array of intesity values to a properly formatted 1D array. This is required to 
        write a filterbank format file the Sigproc can read. Note that the frequency channels of the 2D 
        array must be ordered from highest to lowest frequency.

        Noise is added, and the values are rescaled to be within 0 and 65535 (2**16). You can not set a 
        partiular SNR, but you can set the standard deviation of the noise.
        """

        time_series_1D = np.zeros(np.size(time_series_2D))

        nf = len(time_series_2D[:,0]) #number of frequency channels
        nt = len(time_series_2D[0,:]) #number of time samples

        for t in range(nt): #converting 2D array to 1D array
            time_series_1D[t*nf:(t+1)*nf] = time_series_2D[:,t]

        time_series_1D = np.uint16(time_series_1D)

        noise = np.random.normal(loc=0.0, scale=std_dev, size=(len(time_series_1D)))
        time_series_1D = np.array(time_series_1D) + noise #adding gaussian noise
        time_series_1D = np.uint16((65534*((time_series_1D-min(time_series_1D))/(max(time_series_1D)-min(time_series_1D))))+1) #rescaling
        assert min(time_series_1D) >= 0 #can't have negative values

        return time_series_1D


    def make_filterbank(self, header_params, time_series_1D, tmpfile='tmpfile'):
        """
        Given a dictionary of header parameters from header_params and a properly formatted 1D array of 
        intesity values from array_2D_to_1D, this creates a filterbank format file containing the header 
        and data in binary. The data must be in a filterbank file in order to be used with Sigproc. Note 
        that this code is only set up to write filterbank files where nbits is specifed to be 16. If 
        another value for nbits is desired, write_bin and possible array_2D_to_1D must be tweaked. The 
        name of the filterbank file can be specificed, though it will be deleted if find_FRB_in_filterbank 
        is used.
        """

        self.tmpfile = tmpfile
        self.header_params = header_params

        f = open(tmpfile + '.fil', 'wb')

        self.write_bin(f, 'HEADER_START')

        assert header_params['nbits'] == 16
        if 'source_name' in header_params:
            self.write_bin(f, 'source_name')
            self.write_bin(f, header_params['source_name'])
        if 'rawdatafile' in header_params:
            self.write_bin(f, 'rawdatafile')
            self.write_bin(f, header_params['rawdatafile'])
        if 'machine_id' in header_params:
            self.write_bin(f, 'machine_id')
            self.write_bin(f, header_params['machine_id'])
        if 'telescope_id' in header_params:
            self.write_bin(f, 'telescope_id')
            self.write_bin(f, header_params['telescope_id'])
        if 'data_type' in header_params:
            self.write_bin(f, 'data_type')
            self.write_bin(f, header_params['data_type'])
        if 'fch1' in header_params:
            self.write_bin(f, 'fch1')
            self.write_bin(f, header_params['fch1'])
        if 'foff' in header_params:
            self.write_bin(f, 'foff')
            self.write_bin(f, header_params['foff'])
        if 'nchans' in header_params:
            self.write_bin(f, 'nchans')
            self.write_bin(f, header_params['nchans'])
        if 'nbits' in header_params:
            self.write_bin(f, 'nbits')
            self.write_bin(f, header_params['nbits'])
        if 'tstart' in header_params:
            self.write_bin(f, 'tstart')
            self.write_bin(f, header_params['tstart'])
        if 'tsamp' in header_params:
            self.write_bin(f, 'tsamp')
            self.write_bin(f, header_params['tsamp'])
        if 'nifs' in header_params:
            self.write_bin(f, 'nifs')
            self.write_bin(f, header_params['nifs'])
        if 'src_raj' in header_params:
            self.write_bin(f, 'src_raj')
            self.write_str(f, header_params['src_raj'])
        if 'src_dej' in header_params:
            self.write_bin(f, 'src_dej')
            self.write_bin(f, header_params['src_dej'])
        if 'az_start' in header_params:
            self.write_bin(f, 'az_start')
            self.write_bin(f, header_params['az_start'])
        if 'za_start' in header_params:
            self.write_bin(f, 'za_start')
            self.write_bin(f, header_params['za_start'])
        if 'barycentric' in header_params:
            self.write_bin(f, 'barycentric')
            self.write_bin(f, header_params['barycentric'])
        if 'pulsarcentric' in header_params:
            self.write_bin(f, 'pulsarcentric')
            self.write_bin(f, header_params['pulsarcentric'])
        if 'nsamples' in header_params:
            self.write_bin(f, 'nsamples')
            self.write_bin(f, header_params['nsamples'])
        if 'period' in header_params:
            self.write_bin(f, 'period')
            self.write_bin(f, header_params['period'])
        if 'refdm' in header_params:
            self.write_bin(f, 'refdm')
            self.write_bin(f, header_params['refdm'])

        self.write_bin(f, 'HEADER_END')

        f.close()

        with open (tmpfile + '.fil', 'ab') as f:
            f.write(time_series_1D.tostring())


    def find_FRB_in_filterbank(self, dmstart, dmstop, dmstep):
        """
        Uses the hunt program of Sigproc to search for FRBs in a filterbank file. dmstart, dmstop, and 
        dmstep specify the dm values at which hunt will search for FRBs. The dm values are written to 
        a file named dmlist. Hunt is set to search for sigle pulses instead of pulsars. Hunt 
        outputs a .pls file listing all FRB candidates. The .pls file is read and the DM, width, 
        time, and SNR of the best FRB candidate is printed. A plot of the SNR of the best FRB 
        candidate at each tested dm value is made, called SNR_vs_DM.png. Lastly, all temporary files 
        are deleted, including the .fil, .tim, .pls, and dmlist files. This function grabs the tsamp 
        value from the same header parameter dictionary used in make_filterbank. The name of the .tim 
        and .pls files will be the same as the .fil file.
        """

        ### MAKING DMLIST AND RUNNING HUNT ##################################################

        with open ('dmlist', 'w') as f: #writing dm values to be tested to file 'dmlist'
            subprocess.call(['step', str(dmstart), str(dmstop), str(dmstep)], stdout=f)

        subprocess.call(['hunt', self.tmpfile, '-nofft', '-pulse'])
        assert os.path.isfile(self.tmpfile + '.pls') is True #no pulses found if False

        ### GRABBING BEST FRB ################################################################

        #f = open (self.tmpfile + '.pls', 'r')
        #print '\n', f.readline() #print header
        #f.close()

        data = np.genfromtxt(self.tmpfile + '.pls', skip_header=1)

        for i in range(len(data[:,3])):
            if data[i,3] == max(data[:,3]):
                print '\n', 'DM:', data[i,0]
                print 'FRB Width (s):', self.header_params['tsamp']*2**data[i,1]
                print 'Time of pulse (s):', self.header_params['tsamp']*data[i,2]
                print 'SNR:', data[i,3]

        ### PLOTTING SNR VS DM ###############################################################

        DM = []
        SNR_arr = []
        DM.append(data[0,0])
        SNR_arr.append(data[0,3])
        for i in range(1, len(data[:,3])):
            if data[i,0] > data[i-1,0]:
                DM.append(data[i,0])
                SNR_arr.append(data[i,3])

        plt.plot(DM, SNR_arr)
        plt.xlabel('DM')
        plt.ylabel('SNR')
        plt.savefig('SNR_vs_DM.png')
        plt.clf()

        ### DELETING FILES #######################################################

        os.remove(self.tmpfile + '.fil')
        os.remove(self.tmpfile + '.pls')
        os.remove(self.tmpfile + '.tim')
        os.remove('dmlist')

tsamp = 0.0004 #sampling rate in s
tobs = 500000*tsamp #observation time in s
pulse_nt = int(tobs/tsamp)
nfreq = 200
freq_lo_MHz = 400.0
freq_hi_MHz = 800.0
dm = 500.0
sm = 0.0
intrinsic_width = 0.05
fluence = 12.0
spectral_index = 0.0
undispersed_arrival_time = 250000*tsamp
std_dev = 500

sp = simpulse.single_pulse(pulse_nt, nfreq, freq_lo_MHz, freq_hi_MHz, dm, sm, intrinsic_width, fluence, spectral_index, undispersed_arrival_time)

#(t0, t1) = sp.get_endpoints()
t0 = 0.0
t1 = tobs
ts2D = np.zeros((nfreq, pulse_nt))
sp.add_to_timestream(ts2D, t0, t1, freq_hi_to_lo=True)

f1 = FRB_finder()
head = f1.header_params(telescope_id=0, machine_id=0, data_type=0, tstart = 51105.358703, 
                        tsamp=tsamp, fch1=freq_hi_MHz, foff=(freq_lo_MHz-freq_hi_MHz)/nfreq, 
                        nchans=nfreq, nifs=1, nbits=16)  
f1.make_filterbank(header_params = head, time_series_1D = f1.array_2D_to_1D(ts2D, std_dev=std_dev))
f1.find_FRB_in_filterbank(dmstart=475, dmstop=525, dmstep=0.5)
