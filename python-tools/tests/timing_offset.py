import csv
from pathlib import Path
import numpy as np
from scipy.signal import correlate, correlation_lags, hilbert
from . import common


def arguments(parser):
    parser.add_argument('--timing-gate', type=float, nargs=2, default=[80.0, 92.0])
    parser.add_argument('--max-lag', type=int, default=90)
    parser.add_argument('--reference-csv')


def calculate(rows, w, fs, args):
    if len(w) < 3:
        raise ValueError('Timing analysis requires at least three acquisitions')
    if args.max_lag < 1:
        raise ValueError('max-lag must be positive')
    echo = common.gate(w, fs, args.timing_gate)
    quiet = common.gate(w, fs, args.noise_us)
    baseline = np.mean(quiet, axis=1)
    clean = echo - baseline[:, None]
    reference_index = len(w) - 1
    reference = clean[reference_index] - np.mean(clean[reference_index])
    ref_envelope = np.abs(hilbert(reference))
    lag_axis = correlation_lags(clean.shape[1], len(reference), mode='full')
    valid = np.abs(lag_axis) <= args.max_lag
    search_lags = lag_axis[valid]
    record = []
    shifted = []
    for i, trace in enumerate(clean):
        centered = trace - np.mean(trace)
        corr = correlate(centered, reference, mode='full', method='fft')[valid]
        lag = int(search_lags[np.argmax(corr)])
        shifted.append(lag)
        norm = float(np.linalg.norm(centered) * np.linalg.norm(reference))
        score = float(corr.max() / norm) if norm > 0 else float('nan')
        env = np.abs(hilbert(centered))
        env_corr = correlate(env - env.mean(), ref_envelope - ref_envelope.mean(), mode='full', method='fft')[valid]
        env_lag = int(search_lags[np.argmax(env_corr)])
        noise = float(np.std(quiet[i], ddof=1))
        peak = float(np.max(np.abs(common.gate(w[i], fs, args.echo_us) - baseline[i])))
        record.append(dict(index=i, sequence=rows[i].get('sequence', ''), lag_samples=lag,
                           lag_us=round(lag / fs * 1e6, 6), envelope_lag_samples=env_lag,
                           normalized_correlation=round(score, 6), quiet_baseline=round(float(baseline[i]), 4),
                           quiet_rms=round(noise, 4), echo_peak=round(peak, 4),
                           echo_pp=round(float(np.ptp(common.gate(w[i], fs, args.echo_us))), 4),
                           snr_peak_db=round(20 * np.log10(max(peak, 1e-12) / max(noise, 1e-12)), 4),
                           clipped_samples=int(np.sum((w[i] <= 0) | (w[i] >= 1023)))))
    return record, np.array(shifted, dtype=int)


def metrics(record, fs):
    lags = np.asarray([x['lag_samples'] for x in record], dtype=int)
    baseline = np.asarray([x['quiet_baseline'] for x in record])
    rms = np.asarray([x['quiet_rms'] for x in record])
    peaks = np.asarray([x['echo_peak'] for x in record])
    snr = np.asarray([x['snr_peak_db'] for x in record])
    groups, counts = np.unique(lags, return_counts=True)
    order = np.argsort(counts)[::-1]
    last = max(1, len(lags) // 4)
    d = dict(shots=len(record), sample_rate_hz=fs, reference_shot=len(record)-1,
             lag_std_samples=round(float(np.std(lags)), 4),
             lag_std_ns=round(float(np.std(lags) / fs * 1e9), 3),
             lag_peak_to_peak_samples=int(np.ptp(lags)),
             lag_peak_to_peak_ns=round(float(np.ptp(lags) / fs * 1e9), 3),
             most_common_lags=';'.join(f'{groups[k]}:{counts[k]}' for k in order[:8]),
             envelope_disagreement_percent=round(100 * np.mean(lags != np.asarray([x['envelope_lag_samples'] for x in record])), 2),
             first_baseline=round(float(baseline[0]), 3),
             last_baseline=round(float(baseline[-1]), 3),
             baseline_last_quarter_mean=round(float(np.mean(baseline[-last:])), 3),
             baseline_last_quarter_sd=round(float(np.std(baseline[-last:], ddof=1)) if last>1 else 0, 3),
             mean_snr_peak_db=round(float(np.mean(snr)), 3),
             mean_noise_rms=round(float(np.mean(rms)), 4),
             echo_peak_cv_percent=round(float(100*np.std(peaks,ddof=1)/np.mean(peaks)) if np.mean(peaks)>0 else float('nan'), 3),
             clipped_shots=int(sum(r['clipped_samples']>0 for r in record)))
    return d


def plot(record, w, fs, args, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lag = np.asarray([r['lag_samples'] for r in record])
    env_lag = np.asarray([r['envelope_lag_samples'] for r in record])
    baseline = np.asarray([r['quiet_baseline'] for r in record])
    peaks = np.asarray([r['echo_pp'] for r in record])
    snr = np.asarray([r['snr_peak_db'] for r in record])
    fig, axs = plt.subplots(3,1,figsize=(10,8),sharex=True)
    axs[0].plot(lag, '.', ms=3, label='RF shift')
    axs[0].plot(env_lag, '.', ms=2, alpha=.55, label='Envelope shift')
    axs[0].set_ylabel('Lag (samples)')
    axs[0].legend(loc='best')
    axs[1].plot(baseline)
    axs[1].set_ylabel('Quiet baseline (ADC)')
    axs[2].plot(peaks,label='Echo P-P')
    axs[2].plot(snr,label='Peak/RMS SNR (dB)',alpha=.7)
    axs[2].legend(loc='best')
    axs[2].set_xlabel('Shot')
    fig.tight_layout()
    fig.savefig(out/'timing_and_stability.png',dpi=160)
    plt.close(fig)
    vals, counts=np.unique(lag, return_counts=True)
    fig, ax=plt.subplots(figsize=(9,3.6))
    ax.bar(vals,counts,width=.85)
    ax.set_xlabel('RF lag (samples)')
    ax.set_ylabel('Acquisitions')
    fig.tight_layout()
    fig.savefig(out/'lag_histogram.png',dpi=160)
    plt.close(fig)
    t=np.arange(w.shape[1])/fs*1e6
    selected=[0,len(w)//4,len(w)//2,3*len(w)//4,len(w)-1]
    a,b=args.timing_gate
    lo=max(0,int(a*1e-6*fs));hi=min(w.shape[1],int(np.ceil(b*1e-6*fs)))
    fig,ax=plt.subplots(figsize=(10,4))
    for i in selected:
        trace=w[i,lo:hi]-record[i]['quiet_baseline']
        ax.plot(t[lo:hi],trace,lw=.8,label=f'shot {i}, lag {lag[i]:+d}')
    ax.set_xlabel('Time (µs)')
    ax.set_ylabel('Baseline-subtracted ADC')
    ax.legend(loc='best')
    fig.tight_layout()
    fig.savefig(out/'echo_overlays.png',dpi=160)
    plt.close(fig)
    return ['timing_and_stability.png','lag_histogram.png','echo_overlays.png']


def run(args):
    rows,w,fs=common.get_data(args,'timing_offset',3)
    out=Path(args.outdir)
    out.mkdir(parents=True,exist_ok=True)
    record,lag=calculate(rows,w,fs,args)
    summary=metrics(record,fs)
    common.write_csv(record,out/'timing_per_shot.csv')
    common.write_csv([summary],out/'timing_summary.csv')
    plot(record,w,fs,args,out)
    print(summary)
    if args.reference_csv:
        other_rows,other_w,other_fs=common.load(args.reference_csv)
        other_record,_=calculate(other_rows,other_w,other_fs,args)
        other_summary=metrics(other_record,other_fs)
        other_summary['comparison']='reference'
        summary['comparison']='current'
        common.write_csv([summary,other_summary],out/'firmware_timing_comparison.csv')
