import numpy as np
import matplotlib.pyplot as plt
from equations import *
import warnings
warnings.filterwarnings('ignore')

plt.rcParams['mathtext.fontset'] = 'cm'
plt.rcParams['axes.labelsize'] = 16
plt.rcParams['axes.titlesize'] = 24
plt.rcParams['legend.fontsize'] = 16
plt.rcParams['xtick.labelsize'] = 14
plt.rcParams['ytick.labelsize'] = 14
plt.rcParams['figure.figsize'] = [9,6]
plt.rcParams['font.family'] = "serif"
plt.rcParams['font.serif'] = "Computer Modern Roman"
plt.rcParams['text.usetex'] = True

class Star:
    def __init__(self, T0, lam=None, LAM=None):
        """Everything about a star can be determined by it's centre temperature alone"""
        self.T0 = T0
        self.lam = lam
        self.LAM = LAM
        self.rho0 = "rho0 not yet found"
        self.rho_v = "rho_v not yet found"
        self.T_v = "T_v not yet found"
        self.M_v = "M_v not yet found"
        self.L_v = "L_v not yet found"
        self.tau_v = "tau_v not yet found"
        self.r_v = "r_v not yet found"

    def get_rho0(self, min_guess, max_guess, n_iterations):
        """Rho0 (the only unkown initial contition) is determined by guessing and determining how closely 
        the guess satisfies the surface boundary condition of a star defined in the evaluate_trial function. 
        The guess for rho0 is then refined n_iterations times using a bisection method.
        Increasing num_iterations increases the accuracy of the returned rho0 but also decreases speed."""
        mid_guess = (min_guess + max_guess)/2.0
        min_integrated = self.rk_integration(min_guess)
        mid_integrated = self.rk_integration(mid_guess)
        min_trial = evaluate_trial(min_integrated[3,-1], min_integrated[5,-1], min_integrated[1,-1])
        mid_trial = evaluate_trial(mid_integrated[3,-1], mid_integrated[5,-1], mid_integrated[1,-1])

        for n in range(n_iterations):
            if (min_trial < 0.0 and mid_trial < 0.0) or (min_trial > 0.0 and mid_trial > 0.0):
                min_guess = mid_guess
                mid_guess = (min_guess + max_guess)/2.0
                mid_integrated = self.rk_integration(mid_guess)
                mid_trial = evaluate_trial(mid_integrated[3,-1], mid_integrated[5,-1], mid_integrated[1,-1])

            else:
                max_guess = mid_guess
                mid_guess = (min_guess + max_guess)/2.0
                mid_integrated = self.rk_integration(mid_guess)
                mid_trial = evaluate_trial(mid_integrated[3,-1], mid_integrated[5,-1], mid_integrated[1,-1])

        if mid_trial < 0.0: #yeilds most correct rho0 that is positive
            self.rho0 = max_guess
            return max_guess
        else:
            self.rho0 = mid_guess
            return mid_guess


    def rk_integration(self, rho0): 
        """Conducts 4th order Runge-Kutta integration from the centre of the star outward until the surface 
        boundary condition is satisfied."""
        r_v = [1.0] # arbitrarily small but not 0
        rho_v = [rho0] # a guess to be fine tuned
        T_v = [self.T0] # to be varied to produce main sequence
        M_v = [4.0*np.pi*r_v[0]**3.0*rho0/3.0]
        L_v = [4.0*np.pi*r_v[0]**3.0*rho0/3.0*epsilon(rho0, self.T0)]
        tau_v = [0.0]

        delta_tau = 1.0
        R_max = 20.0*R_sun # If the integration goes beyond this radius, the rho0 guess is bad
        M_max = 100.0*M_sun # If the integration goes beyond this mass, the rho0 guess is bad

        i=0
        while delta_tau>0.0001: # this condition defines the surface of the star
            if T_v[i] < 75000.0: # dr is reduced to 10km near the surface to make sure I get an accurate radius  
                dr = 10000
            else:
                dr = 10000 + r_v[i]/2000.0 # dr gets larger with radius to make integration faster
            
            rk_v = rk_array(rho_v[i], T_v[i], M_v[i], L_v[i], r_v[i], dr, self.lam, self.LAM)

            r_v.append(r_v[i]+dr)
            rho_v.append(rho_v[i]+dr/6.0*(rk_v[0,0] + 2.0*rk_v[0,1] + 2.0*rk_v[0,2]+ rk_v[0,3]))
            T_v.append(T_v[i]+dr/6.0*(rk_v[1,0] + 2.0*rk_v[1,1] + 2.0*rk_v[1,2]+ rk_v[1,3]))
            M_v.append(M_v[i]+dr/6.0*(rk_v[2,0] + 2.0*rk_v[2,1] + 2.0*rk_v[2,2]+ rk_v[2,3]))
            L_v.append(L_v[i]+dr/6.0*(rk_v[3,0] + 2.0*rk_v[3,1] + 2.0*rk_v[3,2]+ rk_v[3,3]))
            tau_v.append(tau_v[i]+dr/6.0*(rk_v[4,0] + 2.0*rk_v[4,1] + 2.0*rk_v[4,2]+ rk_v[4,3]))

            i += 1
            delta_tau = kappa(rho_v[i], T_v[i])*rho_v[i]**2.0/abs(drho_dr(rho_v[i], T_v[i], M_v[i], r_v[i], dT_dr(rho_v[i], T_v[i], M_v[i], L_v[i], r_v[i], kappa(rho_v[i], T_v[i]), self.lam, self.LAM), self.lam, self.LAM))

            if r_v[i] > R_max or M_v[i] > M_max:
                break

        integration_result = np.array([rho_v, T_v, M_v, L_v, tau_v, r_v])

        self.rho_v = rho_v
        self.T_v = T_v
        self.M_v = M_v
        self.L_v = L_v
        self.tau_v = tau_v
        self.r_v = r_v

        return integration_result

class Main_Sequence:
    def __init__(self, T0_min, T0_max, num_stars, lam=None, LAM=None):
        """The main sequence is a continuous and distinctive band of stars 
        that appears on plots of stellar surface tempurature versus luminosity.
        Here, stars are produced over a range of central tempuratures. 
        Main sequence stars have central tempuratures ranging from 10.0**6.6 Kelvin to 10.0**7.4 Kelvin"""
        self.T0_min = T0_min
        self.T0_max = T0_max
        self.num_stars = num_stars
        self.lam = lam
        self.LAM = LAM
        self.T0_v = np.linspace(self.T0_min, self.T0_max, self.num_stars)
        self.Tsurf_v = []
        self.Lsurf_v = []

        for i in range(num_stars):
            S = Star(self.T0_v[i], self.lam, self.LAM)
            S.get_rho0(300, 500000, 10) 
            int_result = S.rk_integration(S.rho0)
            self.Tsurf_v.append((int_result[3,-1]/4.0/np.pi/sigma/int_result[5,-1]/int_result[5,-1])**0.25)
            self.Lsurf_v.append(int_result[3,-1]/L_sun)
            print "Star", i+1, "complete"
        print "Main sequence complete"


### Master Plot

S = Star(10.0**7.35)
S.get_rho0(300, 500000, 13)
integration_result = S.rk_integration(S.rho0)

rho_v, T_v, M_v, L_v, r_v = integration_result[0,:], integration_result[1,:], integration_result[2,:], integration_result[3,:], integration_result[5,:]
radius = max(integration_result[5,:])

plt.plot(r_v/radius, rho_v/max(rho_v), label = r'$\frac{\rho}{\rho_c}$')
plt.plot(r_v/radius, T_v/max(T_v), label = r'$\frac{T}{T_c}$')
plt.plot(r_v/radius, M_v/max(M_v), label = r'$\frac{M}{M_*}$')
plt.plot(r_v/radius, L_v/max(L_v), label = r'$\frac{L}{L_*}$')
plt.title(r'$\frac{\rho}{\rho_c}$, $\frac{T}{T_c}$, $\frac{M}{M_*}$, and $\frac{L}{L_*}$ as Functions of Star Radius')
plt.xlabel(r'$\frac{r}{R_*}$')
plt.ylabel(r'$\frac{\rho}{\rho_c}$, $\frac{T}{T_c}$, $\frac{M}{M_*}$, $\frac{L}{L_*}$')
plt.legend(loc = 'best')
plt.grid()
plt.savefig('Master_Plot.png')
plt.clf()


### Pressure

P_deg_v = P_deg(rho_v)
P_gas_v = P_gas(rho_v, T_v)
P_phot_v = P_phot(T_v)
P_tot_v = P_tot(rho_v, T_v)

plt.plot(r_v/radius, P_deg_v/max(P_tot_v), 'r-.', label = r'$P_{degeneracy}$')
plt.plot(r_v/radius, P_gas_v/max(P_tot_v), 'g--', label = r'$P_{gas}$')
plt.plot(r_v/radius, P_phot_v/max(P_tot_v), 'b:', label = r'$P_{photon}$')
plt.plot(r_v/radius, P_tot_v/max(P_tot_v), 'k', label = r'$P_{total}$')
plt.title('Sources of Pressure as Functions of Star Radius')
plt.xlabel(r'$\frac{r}{R_*}$')
plt.ylabel(r'$\frac{P}{P_c}$')
plt.legend(loc = 'best')
plt.grid()
plt.savefig('Pressure.png')
plt.clf()


### Main Sequence Varying lam

lam_v = [None, -10.0**8.0, 10.0**8.0]
lam_labels = [r'$\lambda = -10^8$', 'Newtonian Gravity', r'$\lambda = 10^8$']

for i in range(len(lam_v)):
    MS = Main_Sequence(10.0**6.6, 10.0**7.4, 12, lam = lam_v[i])
    plt.plot(MS.Tsurf_v, MS.Lsurf_v, label = lam_labels[i])
plt.xscale('log')
plt.yscale('log')
plt.title('Main Sequence Varying Small-Scale Gravity')
plt.xlabel('Surface Temperature [K]')
plt.ylabel(r'$\frac{L}{L_{\odot}}$')
plt.legend(loc = 'best')
plt.gca().invert_xaxis()
plt.savefig('Main_Sequence_Small-Scale.png')
plt.clf()


### Main Sequence Varying LAM

LAM_v = [None, 10.0**7.0, 10.0**8.0]
LAM_labels = ['Newtonian Gravity', r'$\Lambda = 10^7$', r'$\Lambda = 10^8$']

for i in range(len(lam_v)):
    MS = Main_Sequence(10.0**6.6, 10.0**7.4, 12, LAM = LAM_v[i])
    plt.plot(MS.Tsurf_v, MS.Lsurf_v, label = LAM_labels[i])
plt.xscale('log')
plt.yscale('log')
plt.title('Main Sequence Varying Large-Scale Gravity')
plt.xlabel('Surface Temperature [K]')
plt.ylabel(r'$\frac{L}{L_{\odot}}$')
plt.legend(loc = 'best')
plt.gca().invert_xaxis()
plt.savefig('Main_Sequence_Large-Scale.png')
plt.clf()