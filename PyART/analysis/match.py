"""
Stuff for mismatches, still need to port the parallelization,
the precessing case and debug/test the code
"""

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize_scalar, dual_annealing
from ..utils import utils as ut

#PyCBC imports
from pycbc.filter import sigmasq, matched_filter_core, overlap_cplx, optimized_match
from pycbc.types.timeseries import TimeSeries
from pycbc.psd import  aLIGOZeroDetHighPower

# TODO move units to  some utils
Msun =  4.925491025543575903411922162094833998e-6 # G/c^3 

class Matcher(object):
    """
    Class to compute the match between two waveforms.
    """
    def __init__(self,
                 WaveForm1,
                 WaveForm2,
                 modes     = [(2,2)],
                 settings  = None,
                 pre_align = False,
                 ) -> None:
        
        self.modes    = modes
        self.settings = self.__default_parameters__()
        self.settings.update(settings)
        
        # choose your function
        if settings['kind'] == 'single-mode':
            mismatch_func = self._compute_mm_single_mode
        elif settings['kind'] == 'HM':
            mismatch_func = self._compute_mm_hms
        elif settings['kind'] == 'precessing':
            mismatch_func = self._compute_mm_precessing
        else:
            raise ValueError('kind not recognized')
        self.match_f = mismatch_func
        
        # Get local objects with TimeSeries
        wf1 = self._wave2locobj(WaveForm1)
        wf2 = self._wave2locobj(WaveForm2)
        
        # align to improve subsequent tapering (applied before matching computation)
        if pre_align: 
            w1f, wf2 = self.pre_alignmet(wf1, wf2)
        
        # Compute tlen
        self.settings['tlen'] = self._find_tlen(wf1, wf2)
        # compute and stor the mismatch
        self.mismatch = 1 - self.match_f(wf1,wf2,self.settings)
        return
    
    def _wave2locobj(self, WaveForm, isgeom=True):
        """
        Extract useful information from WaveForm class 
        (see PyART/waveform.py) and store in a lambda-obj 
        that will be used in this Matcher class
        """
        if not hasattr(WaveForm, 'hp'):
            raise RuntimeError('hp not found! Compute it before calling Matcher')
        wf        = lambda:0 
        wf.domain = WaveForm.domain
        wf.f      = None # FIXME assume TD waveform at the moment
        wf.hlm    = WaveForm.hlm 

        # Get updated time and hp/hc-TimeSeries
        wf.hp, wf.hc, wf.u = self._mass_rescaled_TimeSeries(WaveForm.u, WaveForm.hp, WaveForm.hc, isgeom=isgeom) 
        return wf

    def _mass_rescaled_TimeSeries(self, u, hp, hc, isgeom=True, kind='cubic'):
        """
        Rescale waveforms with the mass used in settings
        and return TimeSeries.
        If the waveform is not in geom-units, the simply
        return the TimeSeries
        """
        # TODO : test isgeom==False
        dT = self.settings['dt']
        if isgeom:
            M       = self.settings['M'] 
            dT_resc = dT/(M*Msun)
            new_u   = np.arange(u[0], u[-1], dT_resc)
            hp = ut.spline(u, hp, new_u, kind=kind) 
            hc = ut.spline(u, hc, new_u, kind=kind) 
        return TimeSeries(hp, dT), TimeSeries(hc, dT), new_u
    
    def pre_alignment(wf1, wf2):
        """
        Align waveforms (TimeSeries) before feeding 
        them to the conditioning/matching functions. 
        This is needed to improve tapering-consistency
        """
        if not self.settings['taper']:
            warnings.warn('Pre-alignment is not needed if no tapering is applied!')
        # and now? 
        return wf1, wf2

    def _find_tlen(self, wf1, wf2, resize_factor=16):
        """
        Given two local-waveform objects (see wave2locobj()),
        return the time-length to use in TD-waveform
        conditioning (before match computation)
        """
        dT   = self.settings['dt']
        h1   = TimeSeries(wf1.hp, dT)
        h2   = TimeSeries(wf2.hp, dT)
        LM   = max(len(h1), len(h2))
        tl   = (LM-1)*dT
        tN   = ut.nextpow2(resize_factor*tl)
        tlen = int(tN/dT)
        return tlen

    def __default_parameters__(self):
        """
        Default parameters for the mismatch calculation
        """
        return {
            'initial_frequency_mm' : 20.,
            'final_frequency_mm'   : 2048.,
            'psd'                  : 'aLIGOZeroDetHighPower',
            'M'                    : 100.,
            'iota'                 : 0.,
            'coa_phase'            : np.linspace(0,2*np.pi,4),
            'eff_pols'             : np.linspace(0,np.pi,5),
            'taper'                : True,
            'taper_start'          : 0.05, # % of the waveform to taper at the beginning
            'taper_end'            : 0.00, # % of the waveform to taper at the end
            'taper_alpha'          : 0.01,  # sigmoid-parameter used in tapering
        }
    
    def _get_psd(self, flen, df, fmin):
        """
        Get the PSD for the mismatch calculation
        """
        if self.settings['psd'] == 'aLIGOZeroDetHighPower':
            psd = aLIGOZeroDetHighPower(flen, df, fmin)
        else:
            raise ValueError('psd not recognized')
        return psd

    def _compute_mm_single_mode(self, wf1, wf2, settings):
        """
        Compute the mismatch between two waveforms with only a single mode.
        Assume that h = h_+ contains the whole information.
        This is true for non-precessing systems with a single (ell, |m|)
        """
        h1 = wf1.hp
        h2 = wf2.hp
        
        # condition TD waveforms (taper, resize, etc)
        if wf1.domain == 'Time':
            h1 = condition_td_waveform(h1, settings)
        if wf2.domain == 'Time':
            h2 = condition_td_waveform(h2, settings)
        
        assert len(h1) == len(h2)
        df   = 1.0 / h1.duration
        flen = len(h1)//2 + 1
        psd  = self._get_psd(flen, df, settings['initial_frequency_mm'])
        
        if False:
            h1f = h1.to_frequencyseries()
            h2f = h2.to_frequencyseries()
            fig, axs = plt.subplots(2,1)
            axs[0].plot(wf1.hp)
            axs[0].plot(wf2.hp)
            axs[0].plot(h1, label='nr', ls='--')
            axs[0].plot(h2, label='eob', ls='--')
            axs[0].legend()
            axs[1].plot(h1f.sample_frequencies, abs(h1f))
            axs[1].plot(h2f.sample_frequencies, abs(h2f))
            axs[1].set_xlim(settings['initial_frequency_mm']-50,
                            settings['final_frequency_mm']+50)
            axs[1].axvline(settings['initial_frequency_mm'])
            axs[1].axvline(settings['final_frequency_mm'])
            axs[1].set_yscale('log')
            axs[1].set_ylim([1e-5, 1e-1])
            plt.show()
            
        m,_  = optimized_match( h1, h2, 
                                psd=psd, 
                                low_frequency_cutoff=settings['initial_frequency_mm'], 
                                high_frequency_cutoff=settings['final_frequency_mm']
                                )

        return m

    def _compute_mm_hms(self, wf1, wf2, settings):
        """
        Compute the match between two waveforms with higher modes.
        Use wf1 as a fixed target, and decompose wf2 in modes to find the
        best orbital phase.
        """

        iota = settings['iota']
        for coa_phase in settings['coa_phase']:
            sp,sx = wf1.compute_hphc(iota, coa_phase)
            sp    = condition_td_waveform(sp, settings)
            sx    = condition_td_waveform(sx, settings)
            spf   = sp.to_frequencyseries() 
            sxf   = sx.to_frequencyseries()
            psd   = self._get_psd(len(spf), spf.delta_f, settings['initial_frequency_mm'])

            for k in settings['eff_pols']:
                s = np.cos(k)*spf + np.sin(k)*sxf

                mm, _ = higher_modes_match_k_phic(
                    s, wf2, 
                    iota,
                    psd,
                    self.modes,
                    dT=settings['dt'],
                    fmin_mm=settings['initial_frequency_mm'],
                    fmax=settings['final_frequency_mm']
                )
            
        return mm
    
### other functions, not just code related to the class
def condition_td_waveform(h, settings):
    """
    Condition the waveforms before computing the mismatch.
    h is already a TimeSeries
    """
    # taper the waveform
    if settings['taper']:
        hlen = len(h)
        t1    = settings['taper_start'] * hlen
        t2    = settings['taper_end']   * hlen
        alpha = settings['taper_alpha']
        t = np.linspace(0, hlen-1, num=hlen)
        h = ut.taper_waveform(t, h, t1=t1, t2=t2, alpha=alpha)
    # resize
    h.resize(settings['tlen'])
    return h

def dual_annealing(func,bounds,maxfun=2000):
    result= dual_annealing(func, bounds, maxfun=maxfun)#, local_search_options={"method": "Nelder-Mead"})
    opt_pars,opt_val=result['x'],result['fun']
    return opt_pars, opt_val


def sky_and_time_maxed_overlap_1(s, hp, hc, psd, low_freq, high_freq):
    """
    https://arxiv.org/abs/1603.02444
    """
    ss   = sigmasq(s,  psd=psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    hphp = sigmasq(hp, psd=psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    hchc = sigmasq(hc, psd=psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    hp  /= np.sqrt(hphp)
    hc  /= np.sqrt(hchc)

    rhop, _, nrm     = matched_filter_core(hp,s, psd = psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    rhop *= nrm
    rhoc, _, nrm     = matched_filter_core(hc,s, psd = psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    rhoc *= nrm
    
    hphccorr       = overlap_cplx(hp, hc, psd=psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)# matched_filter_core(hp,hc)
    hphccorr       = np.real(hphccorr)
    Ipc            = hphccorr

    rhop2 = np.abs(rhop.data)**2
    rhoc2 = np.abs(rhoc.data)**2
    gamma = rhop.data * np.conjugate(rhoc.data)
    gamma = np.real(gamma)

    sqrt_part = np.sqrt((rhop2-rhoc2)**2 + 4*(Ipc*rhop2-gamma)*(Ipc*rhoc2-gamma))
    num       = rhop2 - 2.*Ipc*gamma + rhoc2 + sqrt_part
    den       = 1. - Ipc**2
    
    o = np.sqrt(max(num)/den/2.)/np.sqrt(ss)
    if (o > 1.):
         o = 1.

    return o

def sky_and_time_maxed_overlap_2(s, hp, hc, psd, low_freq, high_freq):
    """
    https://arxiv.org/pdf/1709.09181
    """
    
    ss   = sigmasq(s,  psd=psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    hphp = sigmasq(hp, psd=psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    hchc = sigmasq(hc, psd=psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    hp  /= np.sqrt(hphp)
    hc  /= np.sqrt(hchc)

    rhop, _, nrm     = matched_filter_core(hp,s, psd = psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    rhop *= nrm
    rhoc, _, nrm     = matched_filter_core(hc,s, psd = psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    rhoc *= nrm
    
    hphccorr       = overlap_cplx(hp, hc, psd=psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)# matched_filter_core(hp,hc)
    Ipc            = np.real(hphccorr)
    
    re_rhop  = np.real(rhop.data)
    re_rhoc  = np.real(rhoc.data) 
    re_rhop2 = re_rhop**2
    re_rhoc2 = re_rhoc**2

    num   = re_rhop2 - 2.*Ipc*re_rhop*re_rhoc + re_rhoc2
    den   = 1. - Ipc**2
    o = np.sqrt(max(num)/den)/np.sqrt(ss)

    if (o > 1.):
        o = 1.

    return o

def time_maxed_overlap(s, hp, hc, psd, low_freq, high_freq, max_pol=True):
    """
    Assume s is + only. 
    We allow for a polarization shift, i.e. a **global** change of sign in the waveform.
    TODO: check if this is implemented correctly, see Sec. VD of https://arxiv.org/abs/1812.07865
    """
    
    ss   = sigmasq(s,  psd=psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    hphp = sigmasq(hp, psd=psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    hp  /= np.sqrt(hphp)

    rhop, _, nrm  = matched_filter_core(hp, s, psd = psd, low_frequency_cutoff=low_freq, high_frequency_cutoff=high_freq)
    rhop         *= nrm
    
    # allow for different polarization conventions
    # potential global - sign change
    os = []
    for ang in [np.pi/2, 0.]:
        re_rhop  = np.real(rhop.data*np.exp(2*1j*ang))
        num   = re_rhop
        o     = max(num)/np.sqrt(ss)
        os.append(o)

    # maximize over allowed polarization
    if max_pol: o = max(os)
    else:       o = os[0]

    if (o > 1.):
        o = 1.
    return o

def higher_modes_match_k_phic(  s, wf, 
                                inc, psd, modes, 
                                func=sky_and_time_maxed_overlap_2,
                                dT=1./4096, fmin_mm=20,fmax=2048
                            ):

    def to_minimize_dphi(x):
        hp, hc   = wf.compute_hphc(x, inc, modes=modes)
        settings = {'taper':True, 'dt':dT}
        hps      = condition_td_waveform(hp, settings)
        hxs      = condition_td_waveform(hc, settings)
        # To FD
        hpf = hps.to_frequencyseries()
        hcf = hxs.to_frequencyseries()       
        return 1.-func(s, hpf, hcf, psd,fmin_mm,fmax)

    res_ms = minimize_scalar(
                to_minimize_dphi,
                method="bounded",
                bounds=(0, 2.*np.pi),
                options={'xatol':1e-15}
                )
    res = to_minimize_dphi(res_ms.x)
    print('minimize_scalar:', res)
    if  res > 1e-2:
        # try also with (more expensive) dual annealing
        # and choose the minimum
        _, res_da = dual_annealing(
                 to_minimize_dphi,
                 [(0., 2.*np.pi)],
                 maxfun=100
             )
        res = min(res, res_da)

    return res
