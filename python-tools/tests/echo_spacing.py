from pathlib import Path
import numpy as np
from scipy.signal import hilbert
from . import common


def arguments(parser):
    parser.add_argument('--front-gate',type=float,nargs=2,default=[80.,87.])
    parser.add_argument('--plate-mm',type=float,default=6.11)
    parser.add_argument('--aluminum-velocity',type=float,default=6320.)
    parser.add_argument('--search-tolerance-us',type=float,default=.40)


def run(args):
    rows,w,fs=common.get_data(args,'echo_spacing',3)
    if args.plate_mm<=0 or args.aluminum_velocity<=0:
        raise ValueError('plate thickness and velocity must be positive')
    delay_us=2*args.plate_mm*1e-3/args.aluminum_velocity*1e6
    quiet=np.mean(common.gate(w,fs,args.noise_us),axis=1)
    t=np.arange(w.shape[1])/fs*1e6
    front_gate=(t>=args.front_gate[0])&(t<=args.front_gate[1])
    if not front_gate.any():
        raise ValueError('Front-wall gate outside waveform')
    envelope=np.abs(hilbert(w-quiet[:,None],axis=1))
    records=[]
    for i,signal in enumerate(envelope):
        fi=np.flatnonzero(front_gate)
        f_idx=int(fi[np.argmax(signal[fi])])
        center=t[f_idx]+delay_us
        ix=np.flatnonzero((t>=center-args.search_tolerance_us)&(t<=center+args.search_tolerance_us))
        if not len(ix):
            continue
        b_idx=int(ix[np.argmax(signal[ix])])
        measured=t[b_idx]-t[f_idx]
        records.append(dict(shot=i,front_us=round(float(t[f_idx]),6),back_us=round(float(t[b_idx]),6),
                            spacing_us=round(float(measured),6),thickness_mm=round(float(measured*1e-6*args.aluminum_velocity/2*1e3),5),
                            front_amplitude=round(float(signal[f_idx]),4),back_amplitude=round(float(signal[b_idx]),4)))
    if not records:
        raise ValueError('No echoes in expected time windows')
    m=np.array([r['thickness_mm'] for r in records])
    values=dict(shots=len(records),expected_spacing_us=round(delay_us,5),
                measured_spacing_us_mean=round(float(np.mean([r['spacing_us'] for r in records])),5),
                measured_thickness_mm_mean=round(float(np.mean(m)),5),
                thickness_sd_mm=round(float(np.std(m,ddof=1)) if len(m)>1 else 0,5),
                thickness_error_percent=round(float(100*(np.mean(m)/args.plate_mm-1)),3),
                note='Tentative echo identification; verify front-wall and back-wall labels')
    out=Path(args.outdir)
    out.mkdir(parents=True,exist_ok=True)
    common.write_csv(records,out/'echo_spacing_per_shot.csv')
    common.write_csv([values],out/'echo_spacing_summary.csv')
    if args.plot:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(9,3.5))
        ax.plot([r['shot'] for r in records],m,'.',ms=3)
        ax.axhline(args.plate_mm,color='gray',ls='--')
        ax.set_xlabel('Shot')
        ax.set_ylabel('Inferred aluminum thickness (mm)')
        fig.tight_layout()
        fig.savefig(out/'echo_spacing.png',dpi=160)
        plt.close(fig)
    print(values)
