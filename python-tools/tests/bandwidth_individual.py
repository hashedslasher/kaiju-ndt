from pathlib import Path
import numpy as np
from scipy.signal.windows import hann
from . import common


def run(args):
    rows,w,fs=common.get_data(args,'bandwidth_individual',3)
    n=common.gate(w,fs,args.noise_us)
    e=common.gate(w,fs,args.echo_us)
    e=e-np.mean(n,axis=1)[:,None]
    window=hann(e.shape[1],sym=False)
    fft_size=max(8192,1 << (e.shape[1]-1).bit_length())
    spectra=np.abs(np.fft.rfft(e*window[None,:],n=fft_size,axis=1))
    frequency=np.fft.rfftfreq(fft_size,1/fs)
    valid=(frequency>=2e6)&(frequency<=min(25e6,fs*.49))
    typical=np.median(spectra,axis=0)
    candidate=np.flatnonzero(valid)
    peak_index=int(candidate[np.argmax(typical[candidate])])
    cutoff=typical[peak_index]*(10**(-6/20))
    lo=peak_index
    while lo>0 and typical[lo-1]>=cutoff:
        lo-=1
    hi=peak_index
    while hi<len(typical)-1 and typical[hi+1]>=cutoff:
        hi+=1
    count=len(w)
    individual_peaks=frequency[np.argmax(spectra[:,candidate],axis=1)+candidate[0]]
    result=dict(shots=count,peak_mhz=round(float(frequency[peak_index]/1e6),5),
                lower_6db_mhz=round(float(frequency[lo]/1e6),5),
                upper_6db_mhz=round(float(frequency[hi]/1e6),5),
                bandwidth_percent=round(float(200*(frequency[hi]-frequency[lo])/(frequency[hi]+frequency[lo])),3),
                median_individual_peak_mhz=round(float(np.median(individual_peaks)/1e6),5),
                note='Median of per-shot magnitude spectra; not calibrated probe bandwidth')
    common.write_csv([result],Path(args.outdir)/'bandwidth_individual_summary.csv')
    if args.plot:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(9,4))
        db=20*np.log10(np.maximum(typical,1e-9)/max(typical.max(),1e-9))
        ax.plot(frequency/1e6,db)
        ax.axhline(-6,ls='--',color='gray')
        ax.set_xlim(0,min(25,fs/2/1e6))
        ax.set_ylim(-70,4)
        ax.set_xlabel('Frequency (MHz)')
        ax.set_ylabel('Relative magnitude (dB)')
        fig.tight_layout()
        out=Path(args.outdir)/'bandwidth_individual.png'
        out.parent.mkdir(parents=True,exist_ok=True)
        fig.savefig(out,dpi=160)
        plt.close(fig)
    print(result)
