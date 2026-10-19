import numpy as np
from scipy.signal import correlate, correlation_lags
from . import common


def arguments(parser):
    parser.add_argument('--max-lag',type=int,default=12)


def run(args):
    rows,w,fs=common.get_data(args,'alignment',2)
    gate=common.gate(w,fs,args.echo_us)
    ref=gate[0]-np.mean(gate[0])
    out=[]
    for i,trace in enumerate(gate):
        trace=trace-np.mean(trace)
        cor=correlate(trace,ref,mode='full',method='fft')
        lags=correlation_lags(len(trace),len(ref),mode='full')
        selected=np.abs(lags)<=args.max_lag
        lag=int(lags[selected][np.argmax(cor[selected])])
        out.append(dict(capture=i,lag_samples=lag,lag_ns=round(lag/fs*1e9,3),sequence=rows[i]['sequence']))
    common.write_csv(out,common.target(args,'alignment_summary'))
    arr=np.array([r['lag_samples'] for r in out])
    print(dict(max_abs_lag_samples=int(np.abs(arr).max()),std_lag_samples=round(np.std(arr),3)))
    if args.plot:
        common.figure(args,'alignment',lambda ax:(ax.plot(arr,'.-'),ax.set_ylabel('Lag (samples)'),ax.set_xlabel('Capture')))
