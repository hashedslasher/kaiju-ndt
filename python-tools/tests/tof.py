import numpy as np
from scipy.signal import hilbert
from . import common


def arguments(parser):
    parser.add_argument('--velocity',type=float,default=1480.)


def run(args):
    rows,w,fs=common.get_data(args,'tof')
    echo=common.gate(w,fs,args.echo_us)
    env=np.abs(hilbert(echo-np.mean(common.gate(w,fs,args.noise_us),axis=-1)[:,None],axis=-1))
    time=args.echo_us[0]+np.argmax(env,axis=1)/fs*1e6
    z=np.array([float(r['z_mm']) for r in rows])
    groups=[]
    for pos in sorted(set(z)):
        t=time[z==pos]
        groups.append(dict(z_mm=pos,shots=len(t),mean_tof_us=round(t.mean(),6),std_tof_us=round(t.std(ddof=1),6) if len(t)>1 else 0))
    common.write_csv(groups,common.target(args,'tof_summary'))
    if len(groups)>1:
        slope,intercept=np.polyfit([r['z_mm'] for r in groups],[r['mean_tof_us'] for r in groups],1)
        print(dict(slope_us_per_mm=round(slope,6),abs_expected_us_per_mm=round(2000/args.velocity,6),abs_slope_error_percent=round(100*(abs(slope)/(2000/args.velocity)-1),3)))
    if args.plot:
        common.figure(args,'tof',lambda ax:(ax.plot(z,time,'o'),ax.set_xlabel('Measured Z (mm)'),ax.set_ylabel('Echo arrival (us)')))
