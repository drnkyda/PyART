import numpy as np
from scipy import interpolate
import matplotlib.pyplot as plt
import h5py 
import glob

from ..waveform import  Waveform

class CoRe(Waveform):

    def __init__(self,
                 basepath='../dat/CoRe/',
                 kind     = 'txt',
                 mtdt_path='../dat/CoRe/metadata.txt',
                 ell_emms='all'
                 )->None:

        super().__init__()

        self.ell_emms = ell_emms
        self.metadata = None

        # read metadata
        self.metadata = self.read_metadata(mtdt_path)

        # read data
        self.read_h(basepath, kind)

        pass

    def read_metadata(self, mtdt_path):
        metadata = {}
        with open(mtdt_path, "r") as f:
            lines = [l for l in f.readlines() if l.strip()] # rm empty
            for line in lines:
                if line[0]=="#": continue
                line               = line.rstrip("\n")
                key, val           = line.split("= ")
                key                = key.strip()
                metadata[key] = val.strip()

        return metadata
    
    def read_h(self, basepath, kind):
        if kind == 'txt':
            self.read_h_txt(basepath)
        elif kind == 'h5':
            self.read_h_h5(basepath)
        else:
            raise NameError('kind not recognized')

    def read_h_txt(self, basepath):
        # find all files under basepath
        modes = glob.glob(basepath + '/Rh_l*.txt')

        r = []
        # Extract extraction radii from filenames
        for m in modes:
            r.append(m.split('/')[-1].split('_')[-1].split('.')[0])
        
        # largest extraction radius
        r = list(set(r))
        imaxr = np.argmax([int(rr[1:]) for rr in r])
        largest_radius = r[imaxr]

        # Dictionary to store data
        d = {}

        # read modes
        for m in modes:
            this_r = m.split('/')[-1].split('_')[-1].split('.')[0]
            
            if this_r != largest_radius:
                continue
                
            ell = int(m.split('/')[-1].split('_')[1][1:])
            emm = int(m.split('/')[-1].split('_')[2][1:].split('.')[0])

            if self.ell_emms != 'all':
                if (ell, emm) not in self.ell_emms:
                    continue

            # determine number of columns 
            with open(m, 'r') as f:
                for _ in range(3):  # Skip header rows
                    next(f)
                first_data_line = f.readline().strip()
            num_columns = len(first_data_line.split())

            # load data based on number of columns
            if num_columns == 7:
                u, re, im, Momg, A, phi, t = np.loadtxt(m, unpack=True, skiprows=3)
                d[(ell, emm)] = {
                    'A': A,
                    'p': phi,
                    't': t,
                    'real': re,
                    'imag': im
                }
            elif num_columns == 9:
                u, re, im, redh, imdh, Momg, A, phi, t = np.loadtxt(m, unpack=True, skiprows=3)
                d[(ell, emm)] = {
                    'A': A,
                    'p': phi,
                    't': t,
                    'real': re,
                    'imag': im,
                    'redh': redh,
                    'imdh': imdh
                }
            else:
                raise ValueError(f"Unexpected number of columns ({num_columns}) in file {m}")

        # check if d empty and update
        if d:
            self._t = t
            self._u = u
            self._hlm = d
            self._A = A
            self._re = re
            self._im = im

            pass
        
    # def read_h_txt(self, basepath):
    #     # find all modes under basepath
    #     modes = glob.glob(basepath+'/Rh_l*.txt')

    #     r = []
    #     # find extraction radii
    #     for m in modes:
    #         r.append(m.split('/')[-1].split('_')[-1].split('.')[0])
    #     # find largest extraction radius
    #     r = list(set(r))
    #     imaxr = np.argmax([int(rr[1:]) for rr in r])

    #     # read modes
    #     d = {}
    #     for m in modes:
            
    #         this_r = m.split('/')[-1].split('_')[-1].split('.')[0]
    #         if this_r != r[imaxr]: continue
            
    #         ell = int(m.split('/')[-1].split('_')[1][1:])
    #         emm = int(m.split('/')[-1].split('_')[2][1:].split('.')[0])
    #         if self.ell_emms != 'all':
    #             if (ell, emm) not in self.ell_emms: continue
    #         d[(ell, emm)] = {}

    #         # u/M:0 Reh/M:1 Imh/M:2 Momega:3 A/M:4 phi:5 t:6
    #         u, re, im, Momg, A, phi, t = np.loadtxt(m, unpack=True, skiprows=3)
    #         d[(ell, emm)] ={
    #             'A': A,              'p': phi,
    #             't': t,              'real': re,             'imag': im
    #         }
    #     self._t = t
    #     self._u = u
    #     self._hlm = d
    #     pass

