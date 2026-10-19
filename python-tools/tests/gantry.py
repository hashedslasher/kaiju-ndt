import csv
import numpy as np
from . import common


def arguments(parser):
    parser.add_argument('--motor-steps',type=int,default=200)
    parser.add_argument('--microsteps',type=int,default=16)
    parser.add_argument('--belt-pitch',type=float,default=2.0)
    parser.add_argument('--teeth',type=int,default=16)
    parser.add_argument('--gear-ratio',type=float,default=1.0)
    parser.add_argument('--screw-lead',type=float)


def run(args):
    denom=args.screw_lead if args.screw_lead else args.belt_pitch*args.teeth
    spmm=args.motor_steps*args.microsteps*args.gear_ratio/denom
    print(dict(steps_per_mm=round(spmm,5),nominal_increment_mm=round(1/spmm,7)))
    if not args.csv:
        return
    with open(args.csv,newline='') as f:
        rows=list(csv.DictReader(f))
    expected=np.array([float(r['commanded_mm']) for r in rows])
    actual=np.array([float(r['measured_mm']) for r in rows])
    error=actual-expected
    results=dict(n=len(rows),mae_mm=round(np.mean(np.abs(error)),5),max_abs_error_mm=round(np.max(np.abs(error)),5),
                 signed_bias_mm=round(np.mean(error),5))
    direction=np.array([r.get('direction','').strip().lower() for r in rows])
    rep=[]
    for v in sorted(set(expected)):
        for d in sorted(set(direction)):
            match=(expected==v)&(direction==d)
            if match.sum()>=2:
                rep.append(actual[match].std(ddof=1))
    if rep:
        results['worst_same_direction_sd_mm']=round(max(rep),5)
    hysteresis=[]
    for v in sorted(set(expected)):
        matched=expected==v
        dirs=sorted(set(direction[matched]))
        if len(dirs)>=2:
            means=[np.mean(actual[matched & (direction==d)]) for d in dirs]
            hysteresis.append(max(means)-min(means))
    if hysteresis:
        results['worst_direction_offset_mm']=round(max(hysteresis),5)
    if len(set(expected))>=2:
        slope,offset=np.polyfit(expected,actual,1)
        results['scale_error_percent']=round(100*(slope-1),5)
    print(results)
    common.save_summary(args,'gantry_summary',results)
    if args.plot:
        common.figure(args,'gantry',lambda ax:(ax.scatter(expected,error),ax.set_xlabel('Commanded (mm)'),ax.set_ylabel('Measured minus commanded (mm)')))
