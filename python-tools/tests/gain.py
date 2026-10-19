import numpy as np
from . import common


def arguments(parser):
    parser.add_argument('--levels',default='100,200,300,400,460,500')
    parser.add_argument('--per-level',type=int,default=8)


def run(args):
    if args.csv:
        rows,w,fs=common.load(args.csv)
    else:
        probe=common.device(args)
        rows=[]
        try:
            for gain in [int(n) for n in args.levels.split(',')]:
                probe.set_gain(gain)
                args.gain=gain
                for i in range(args.per_level):
                    rows.append(common.frame_row(probe.read_raw(),args,len(rows)))
        finally:
            probe.close()
        common.write_csv(rows,args.output or common.target(args,'gain'))
        rows,w,fs=common.extract(rows)
    amplitudes=common.echo_amplitudes(w,fs,args.echo_us)
    levels=sorted({int(r['gain']) for r in rows})
    results=[]
    for gain in levels:
        index=np.array([int(r['gain'])==gain for r in rows])
        results.append(dict(gain_dac=gain,shots=int(index.sum()),mean_peak=round(np.mean(amplitudes[index]),3),
                            clipped_percent=round(100*np.mean((w[index]<=0)|(w[index]>=1023)),4)))
    common.write_csv(results,common.target(args,'gain_summary'))
    if args.plot:
        common.figure(args,'gain',lambda ax:(ax.plot(levels,[r['mean_peak'] for r in results],'o-'),ax.set_xlabel('DAC setting'),ax.set_ylabel('Gated peak (counts)')))
