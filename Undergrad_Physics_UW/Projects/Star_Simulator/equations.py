import numpy as np

## All values are in SI units
M_sun = 1.989e30 ## Mass of sun
R_sun = 695700000.0 ## Radius of sun
L_sun = 3.846e26 ## Luminosity of sun
G = 6.67408e-11 ## Newton Constant
gamma = 5.0/3.0 ## condiditon for star to be locally convectively stable
c = 299792458.0 ## speed of light
sigma = 5.670367e-8 ## Stefan-Boltzmann constant
a = 4.0*sigma/c
m_proton = 1.6726219e-27 ## mass of proton
m_electron = 9.10938356e-31  ## mass of electron
k = 1.38064852e-23 ##Boltzmann constant
h = 6.62607004e-34 ## Plank constant
hbar = 1.0545718e-34
X = 0.73 ## hydrogen fraction
Y = 0.25 ## helium fraction
Z = 0.02 ## metalicity

def epsilon(rho, T):
	"""epsilon is the sum of the energy produced per second per kg by both the PP-chain and the CNO-cycle"""
	epsilon_PP = 1.07e-7*(rho/10.0**5.0)*X**2.0*(T/10.0**6.0)**4.0
	X_CNO = 0.03*X
	epsilon_CNO = 8.24e-26*(rho/10.0**5.0)*X*X_CNO*(T/10.0**6.0)**19.9
	epsilon = epsilon_PP + epsilon_CNO
	return epsilon

def kappa(rho, T):
	"""kappa is an approximation of the opacity from electron scattering, free-free, and H- ions"""
	kappa_es = 0.02*(1.0 + X)
	kappa_ff = 10.0**24.0*(Z + 0.0001)*(rho/10.0**3.0)**0.7*T**(-3.5)
	kappa_H = 2.5e-32*(Z/0.02)*(rho/10.0**3.0)**0.5*T**9.0
	if T > 10000.0:
		kappa = (1.0/kappa_H + 1.0/max(kappa_es, kappa_ff))**(-1.0)
	else:
		kappa = (1.0/kappa_H + 1.0/min(kappa_es, kappa_ff))**(-1.0)
	return kappa

def drho_dr(rho, T, M, r, dT_dr, lam=None, LAM=None):
	"""rho is density"""
	assert not (lam is not None and LAM is not None)
	mu = (2.0*X + 0.75*Y + 0.5*Z)**(-1.0)
	dP_dT = rho*k/mu/m_proton + 4.0*a*T**3.0/3.0
	dP_drho = (3.0*np.pi**2.0)**(2.0/3.0)*hbar**2.0*(rho/m_proton)**(2.0/3.0)/3.0/m_electron/m_proton + k*T/mu/m_proton
	if lam is None and LAM is None:
		g = G*M/r**2.0
	elif lam is not None and LAM is None:
		g = G*M/r**2.0*(1.0 + lam/r)
	elif lam is None and LAM is not None:
		g = G*M/r**2.0*(1.0 + r/LAM)
	drho_dr = -(g*rho + dP_dT*dT_dr)/dP_drho
	return drho_dr

def dP_dr(rho, M, r):
	"""P is pressure"""
	dP_dr = -G*M*rho/r**2.0
	return dP_dr

def dT_dr(rho, T, M, L, r, kappa, lam=None, LAM=None):
	"""T is tempurature"""
	assert not (lam is not None and LAM is not None)
	mu = (2.0*X + 0.75*Y + 0.5*Z)**(-1.0)
	P = (3.0*np.pi**2.0)**(2.0/3.0)*hbar**2.0*(rho/m_proton)**(5.0/3.0)/5.0/m_electron + rho*k*T/mu/m_proton + a*T**4.0/3.0
	if lam is None and LAM is None:
		g = G*M/r**2.0
	elif lam is not None and LAM is None:
		g = G*M/r**2.0*(1.0 + lam/r)
	elif lam is None and LAM is not None:
		g = G*M/r**2.0*(1.0 + r/LAM)
	dT_dr = -min(3.0*kappa*rho*L/16.0/np.pi/a/c/T**3.0/r**2.0, (1.0 - 1.0/gamma)*T*g*rho/P)
	return dT_dr

def P_deg(rho):
	P_deg = (3.0*np.pi**2.0)**(2.0/3.0)*hbar**2.0*(rho/m_proton)**(5.0/3.0)/5.0/m_electron
	return P_deg

def P_gas(rho, T):
	mu = (2.0*X + 0.75*Y + 0.5*Z)**(-1.0)
	P_gas = rho*k*T/mu/m_proton
	return P_gas

def P_phot(T):
	P_phot = a*T**4.0/3.0
	return P_phot

def P_tot(rho, T):
	"""P_tot is the sum on degeneracy pressure, ideal gas pressure, and photon pressure"""
	mu = (2.0*X + 0.75*Y + 0.5*Z)**(-1.0)
	P_tot = (3.0*np.pi**2.0)**(2.0/3.0)*hbar**2.0*(rho/m_proton)**(5.0/3.0)/5.0/m_electron + rho*k*T/mu/m_proton + a*T**4.0/3.0
	return P_tot

def dM_dr(rho, r):
	"""M is the mass within radius r of the centre of the star"""
	dM_dr = 4.0*np.pi*r**2.0*rho
	return dM_dr

def dL_dr(rho, r, epsilon):
	"""L is luminosity"""
	dL_dr = 4.0*np.pi*r**2.0*rho*epsilon
	return dL_dr

def dtau_dr(rho, kappa):
	"""tau is used to define the surface of the start"""
	dtau_dr = kappa*rho
	return dtau_dr

def rk_array(rho, T, M, L, r, dr, lam=None, LAM=None): #dr is step size in radius
	"""Returns an array of values to be used in 4th order Runge-Kutta integration"""
	k_array = np.empty((5, 4))

	rho1 = drho_dr(rho, T, M, r, dT_dr(rho, T, M, L, r, kappa(rho, T), lam, LAM), lam, LAM)
	T1 = dT_dr(rho, T, M, L, r, kappa(rho, T), lam, LAM)
	M1 = dM_dr(rho, r)
	L1 = dL_dr(rho, r, epsilon(rho, T))
	tau1 = dtau_dr(rho, kappa(rho, T))
	k_array[:,0] = [rho1, T1, M1, L1, tau1]

	rho2 = drho_dr(rho + dr*rho1/2.0, T + dr*T1/2.0, M + dr*M1/2.0, r + dr/2.0, dT_dr(rho + dr*rho1/2.0, T + dr*T1/2.0, M + dr*M1/2.0, L + dr*L1/2.0, r + dr/2.0, kappa(rho + dr*rho1/2.0, T + dr*T1/2.0), lam, LAM), lam, LAM)
	T2 = dT_dr(rho + dr*rho1/2.0, T + dr*T1/2.0, M + dr*M1/2.0, L + dr*L1/2.0, r + dr/2.0, kappa(rho + dr*rho1/2.0, T + dr*T/2.0), lam, LAM)
	M2 = dM_dr(rho + dr*rho1/2.0, r + dr/2.0)
	L2 = dL_dr(rho + dr*rho1/2.0, r + dr/2.0, epsilon(rho + dr*rho1/2.0, T + dr*T1/2.0))
	tau2 = dtau_dr(rho + dr*rho1/2.0, kappa(rho + dr*rho1/2.0, T + dr*T1/2.0))
	k_array[:,1] = [rho2, T2, M2, L2, tau2]

	rho3 = drho_dr(rho + dr/2.0*rho2, T + dr/2.0*T2, M + dr/2.0*M2, r + dr/2.0, dT_dr(rho + dr/2.0*rho2, T + dr/2.0*T2, M + dr/2.0*T2, L + dr/2.0*L2, r + dr/2.0, kappa(rho + dr/2.0*rho2, T + dr/2.0*T2), lam, LAM), lam, LAM)
	T3 = dT_dr(rho + dr/2.0*rho2, T + dr/2.0*T2, M + dr/2.0*M2, L + dr*L2/2.0, r + dr/2.0, kappa(rho + dr/2.0*rho2, T + dr/2.0*T2), lam, LAM)
	M3 = dM_dr(rho + dr/2.0*rho2, r + dr/2.0)           
	L3 = dL_dr(rho + dr/2.0*rho2, r + dr/2.0, epsilon(rho + dr/2.0*rho2, T + dr/2.0*T2))
	tau3 = dtau_dr(rho + dr/2.0*rho2, kappa(rho + dr/2.0*rho2, T + dr/2.0*T2))
	k_array[:,2] = [rho3, T3, M3, L3, tau3]

	rho4 = drho_dr(rho + dr*rho3, T + dr*T3, M + dr*M3, r + dr, dT_dr(rho + dr*rho3, T + dr*T3, M + dr*M3, L + dr*L3, r + dr, kappa(rho + dr*rho3, T + dr*T3), lam, LAM), lam ,LAM)
	T4 = dT_dr(rho + dr*rho3, T + dr*T3, M + dr*M3, L + dr*L3, r + dr, kappa(rho + dr*rho3, T + dr*T), lam, LAM)
	M4 = dM_dr(rho + dr*rho3, r + dr)
	L4 = dL_dr(rho + dr*rho3, r + dr, epsilon(rho + dr*rho3, T + dr*T3))
	tau4 = dtau_dr(rho + dr*rho3, kappa(rho + dr*rho3, T + dr*T3))
	k_array[:,3] = [rho4, T4, M4, L4, tau4]

	return k_array

def evaluate_trial(L_star, R_star, T_star):
	"""This function is used to test how good the guess for rho0. Returns 0.0 when given perfectly correct inital conditions"""
	SB_law = 4.0*np.pi*sigma*(R_star**2.0)*(T_star)**4.0
	test_func = (L_star - SB_law)/((L_star*SB_law)**(0.5))
   	return test_func