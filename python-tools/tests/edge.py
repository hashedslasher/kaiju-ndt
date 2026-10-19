import numpy as np
from . import common


def arguments(parser):
    parser.add_argument('--range-mm',type=float,nargs=2)
    parser.add_argument('--axis',choices=('x','y'),default='x')


def run(args):
    rows,w,fs=common.get_data(args,'edge',3)
    x=np.array([float(r[f'{args.axis}_mm']) for r in rows])
    a=common.echo_amplitudes(w,fs,args.echo_us)
    xx=np.array(sorted(set(x)))
    yy=np.array([a[x==v].mean() for v in xx])
    if args.range_mm:
        keep=(xx>=args.range_mm[0])&(xx<=args.range_mm[1])
        xx,yy=xx[keep],yy[keep]
    if len(xx)<3:
        raise ValueError('Need at least 3 unique positions in edge range')
    descending=yy[-1]<yy[0]
    norm=(yy-yy.min())/(yy.max()-yy.min()) if yy.max()!=yy.min() else np.zeros_like(yy)
    if descending:
        norm=1-norm
    norm=np.maximum.accumulate(norm)
    if norm[0]>0.1 or norm[-1]<0.9:
        raise ValueError('Chosen edge does not span 10%-90%')
    x10=np.interp(.1,norm,xx);x90=np.interp(.9,norm,xx)
    result=dict(axis=args.axis,edge_10_mm=round(x10,5),edge_90_mm=round(x90,5),width_10_90_mm=round(abs(x90-x10),5))
    print(result)
    common.save_summary(args,'edge_summary',result)
    if args.plot:
        common.figure(args,'edge',lambda ax:(ax.plot(xx,yy,'o-'),ax.set_xlabel(args.axis+' (mm)'),ax.set_ylabel('Gated amplitude (counts)')))
