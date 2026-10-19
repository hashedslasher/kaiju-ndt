import numpy as np
from scipy.signal import hilbert
from . import common


def run(args):
    rows, w, fs = common.get_data(args, 'repeatability', 3)
    n = common.gate(w, fs, args.noise_us)
    baseline = np.mean(n, axis=-1)
    echo = common.gate(w, fs, args.echo_us) - baseline[:, None]
    envelope = np.abs(hilbert(echo, axis=-1))
    peaks = np.max(envelope, axis=-1)
    i = np.argmax(envelope, axis=-1)
    tof = args.echo_us[0] + i / fs * 1e6
    result = dict(shots=len(w), amplitude_cv_percent=round(100*np.std(peaks,ddof=1)/np.mean(peaks),4),
                  amplitude_mean=round(np.mean(peaks),4), tof_mean_us=round(np.mean(tof),5),
                  tof_sd_us=round(np.std(tof,ddof=1),5))
    print(result)
    common.save_summary(args,'repeatability_summary',result)
    if args.plot:
        common.figure(args,'repeatability',lambda ax:(ax.plot(tof),ax.set_ylabel('Envelope peak TOF (us)'),ax.set_xlabel('Capture')))
