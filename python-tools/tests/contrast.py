import numpy as np
from . import common


def run(args):
    rows,w,fs=common.get_data(args,'contrast',2)
    labs=np.array([r['label'].strip().lower() for r in rows])
    if not np.any(labs=='good') or not np.any(labs=='hole'):
        raise ValueError('Capture both --label good and --label hole into one CSV')
    amps=common.echo_amplitudes(w,fs,args.echo_us)
    good=amps[labs=='good'];hole=amps[labs=='hole']
    sg=good.std(ddof=1) if len(good)>1 else float('nan')
    result=dict(good_n=len(good),hole_n=len(hole),good_mean=round(good.mean(),3),hole_mean=round(hole.mean(),3),
                good_sd=round(sg,3),contrast_sd=round(abs(hole.mean()-good.mean())/sg,3) if sg>0 else float('nan'))
    print(result)
    common.save_summary(args,'contrast_summary',result)
