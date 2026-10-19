import numpy as np
from . import common


def run(args):
    rows,w,fs=common.get_data(args,'focus')
    z=np.array([float(r['z_mm']) for r in rows])
    amps=common.echo_amplitudes(w,fs,args.echo_us)
    results=[]
    for value in sorted(set(z)):
        v=amps[z==value]
        results.append(dict(z_mm=value,shots=len(v),peak_mean=round(v.mean(),3),peak_sd=round(v.std(ddof=1),3) if len(v)>1 else 0))
    common.write_csv(results,common.target(args,'focus_summary'))
    print('Highest measured echo at Z (mm):',max(results,key=lambda v:v['peak_mean'])['z_mm'])
    if args.plot:
        common.figure(args,'focus',lambda ax:(ax.plot([r['z_mm'] for r in results],[r['peak_mean'] for r in results],'o-'),ax.set_xlabel('Z (mm)'),ax.set_ylabel('Peak echo (counts)')))
