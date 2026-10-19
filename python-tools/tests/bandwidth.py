import numpy as np
from scipy.signal.windows import hann
from . import common


def run(args):
    rows,w,fs=common.get_data(args,'bandwidth')
    echo=common.gate(np.mean(w,axis=0),fs,args.echo_us)
    echo=echo-np.mean(echo)
    fft=np.abs(np.fft.rfft(echo*hann(len(echo)),n=max(8192,2**int(np.ceil(np.log2(len(echo)))))))
    freqs=np.fft.rfftfreq(max(8192,2**int(np.ceil(np.log2(len(echo))))),1/fs)
    k=int(np.argmax(fft))
    inds=np.where(fft>=fft[k]*10**(-6/20))[0]
    lo,hi=freqs[inds[0]],freqs[inds[-1]]
    result=dict(peak_mhz=round(freqs[k]/1e6,5),lower_6db_mhz=round(lo/1e6,5),upper_6db_mhz=round(hi/1e6,5),
                bandwidth_percent=round(200*(hi-lo)/(hi+lo),3) if hi+lo else 0)
    print(result)
    common.save_summary(args,'bandwidth_summary',result)
    if args.plot:
        common.figure(args,'bandwidth',lambda ax:(ax.plot(freqs/1e6,20*np.log10(np.maximum(fft,1e-12)/max(fft))),ax.set_xlim(0,fs/2/1e6),ax.set_ylim(-80,5),ax.set_xlabel('Frequency (MHz)'),ax.set_ylabel('Magnitude (dB rel. peak)')))
