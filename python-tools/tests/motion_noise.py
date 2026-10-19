import numpy as np
from . import common


def run(args):
    rows,w,fs=common.get_data(args,'motion_noise')
    groups=np.array([r['label'].lower() for r in rows])
    values=[]
    snr,amp,noise=common.snr(w,fs,args.echo_us,args.noise_us)
    for label in sorted(set(groups)):
        mask=groups==label
        values.append(dict(label=label,n=int(mask.sum()),snr_db=round(np.mean(snr[mask]),3),noise_rms=round(np.mean(noise[mask]),4)))
    common.write_csv(values,common.target(args,'motion_noise_summary'))
    if len(values)<2:
        print('Record separate motor-off and motor-on datasets into the same CSV for comparison')
