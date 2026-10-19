import numpy as np
from . import common


def run(args):
    rows, w, fs = common.get_data(args, 'snr')
    values, amp, noise = common.snr(w, fs, args.echo_us, args.noise_us)
    result = dict(shots=len(w), mean_peak_to_rms_db=round(np.mean(values), 3),
                  std_peak_to_rms_db=round(np.std(values, ddof=1), 3) if len(values)>1 else 0,
                  mean_echo_peak=round(np.mean(amp),3), mean_noise_rms=round(np.mean(noise),3))
    print(result)
    common.save_summary(args, 'snr_summary', result)
    if args.plot:
        common.figure(args, 'snr', lambda ax: (ax.plot(values), ax.set_xlabel('Capture'), ax.set_ylabel('Peak/RMS noise (dB)')))
