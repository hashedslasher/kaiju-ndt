import numpy as np
from . import common


def arguments(parser):
    parser.add_argument('--counts', default='1,2,4,8,16,32,64')


def run(args):
    rows,w,fs=common.get_data(args,'averaging', 2)
    counts=[int(n) for n in args.counts.split(',')]
    results=[]
    for n in counts:
        if n < 1 or n > len(w):
            continue
        m=len(w)//n
        avg=w[:m*n].reshape(m,n,w.shape[1]).mean(axis=1)
        snr,amp,noise=common.snr(avg,fs,args.echo_us,args.noise_us)
        results.append(dict(averages=n,groups=m,mean_snr_db=round(np.mean(snr),3),
                            mean_peak=round(np.mean(amp),3),mean_noise_rms=round(np.mean(noise),3),
                            ideal_gain_db=round(10*np.log10(n),3)))
    if not results:
        raise ValueError('No averaging counts fit the dataset')
    common.write_csv(results,common.target(args,'averaging_summary'))
    if args.plot:
        common.figure(args,'averaging',lambda ax:(ax.plot([v['averages'] for v in results],[v['mean_snr_db'] for v in results],'o-'),ax.set_xlabel('Averages'),ax.set_ylabel('Peak/RMS SNR (dB)')))
