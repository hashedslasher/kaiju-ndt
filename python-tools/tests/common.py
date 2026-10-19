import csv
import math
import time
from pathlib import Path
import numpy as np


def arguments(parser):
    parser.add_argument('--csv')
    parser.add_argument('--output')
    parser.add_argument('--port')
    parser.add_argument('--shots', type=int, default=128)
    parser.add_argument('--gain', type=int, default=460)
    parser.add_argument('--negative-ns', type=int, default=75)
    parser.add_argument('--positive-ns', type=int, default=75)
    parser.add_argument('--damp-ns', type=int, default=6000)
    parser.add_argument('--order', choices=('pos-first', 'neg-first'), default='pos-first')
    parser.add_argument('--label', default='good')
    parser.add_argument('--x-mm', type=float, default=0.0)
    parser.add_argument('--y-mm', type=float, default=0.0)
    parser.add_argument('--z-mm', type=float, default=0.0)
    parser.add_argument('--echo-us', type=float, nargs=2, default=[8.0, 12.0])
    parser.add_argument('--noise-us', type=float, nargs=2, default=[20.0, 24.0])
    parser.add_argument('--outdir', default='results')
    parser.add_argument('--plot', action='store_true')


def target(args, name, ext='csv'):
    folder = Path(args.outdir)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f'{name}_{time.strftime("%Y%m%d_%H%M%S")}.{ext}'


def device(args):
    from lib.device import Pic0rick
    probe = Pic0rick(port=args.port)
    probe.set_gain(args.gain)
    probe.configure_pulse(args.negative_ns, args.damp_ns, args.positive_ns, args.order)
    probe.arm_pulser()
    return probe


def frame_row(frame, args, index):
    h = frame.header
    return dict(index=index, host_s=time.time(), device_us=h.capture_timestamp_us,
                sequence=h.sequence, dropped=h.dropped_frames, flags=h.flags,
                sample_rate_hz=h.sample_rate_hz, sample_count=h.sample_count,
                gain=args.gain, negative_ns=h.negative_ns, positive_ns=h.positive_ns,
                damp_ns=h.damp_ns, label=args.label, x_mm=args.x_mm,
                y_mm=args.y_mm, z_mm=args.z_mm,
                **{f's{i}': int(v) for i, v in enumerate(frame.samples())})


def write_csv(rows, path, append=False):
    rows = list(rows)
    if not rows:
        raise ValueError('No data to save')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.exists() and path.stat().st_size > 0
    if append and existing:
        with path.open(newline='') as f:
            existing_header = next(csv.reader(f))
        if existing_header != list(rows[0]):
            raise ValueError('CSV schema mismatch (sample count or columns changed)')
    with path.open('a' if append else 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        if not append or not existing:
            writer.writeheader()
        writer.writerows(rows)
    print(path)


def load(path):
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError('CSV has no records')
    columns = [key for key in rows[0] if key.startswith('s') and key[1:].isdigit()]
    columns.sort(key=lambda s: int(s[1:]))
    if not columns:
        raise ValueError('CSV has no waveform columns')
    waveforms = np.asarray([[float(row[c]) for c in columns] for row in rows], dtype=np.float64)
    fs = np.asarray([float(row['sample_rate_hz']) for row in rows])
    if not np.allclose(fs, fs[0]):
        raise ValueError('Different sample rates present')
    return rows, waveforms, fs[0]


def get_data(args, name, min_shots=1):
    if args.csv:
        return load(args.csv)
    if args.shots < min_shots:
        raise ValueError(f'{name} requires at least {min_shots} shots')
    p = device(args)
    try:
        rows = [frame_row(p.read_raw(), args, i) for i in range(args.shots)]
    finally:
        p.close()
    write_csv(rows, args.output or target(args, name), append=False)
    return extract(rows)


def extract(rows):
    sample_keys = sorted((k for k in rows[0] if k.startswith('s') and k[1:].isdigit()), key=lambda s: int(s[1:]))
    waveforms = np.array([[row[k] for k in sample_keys] for row in rows], dtype=np.float64)
    fs = float(rows[0]['sample_rate_hz'])
    return rows, waveforms, fs


def gate(w, fs, bounds):
    a = max(0, int(math.floor(bounds[0] * 1e-6 * fs)))
    b = min(w.shape[-1], int(math.ceil(bounds[1] * 1e-6 * fs)))
    if b <= a:
        raise ValueError(f'Empty gate {bounds}; trace duration {w.shape[-1] / fs * 1e6:.2f} us')
    return w[..., a:b]


def peaks(w, fs, bounds):
    window = gate(w, fs, bounds)
    return np.max(np.abs(window - np.median(window, axis=-1, keepdims=True)), axis=-1)


def echo_amplitudes(w, fs, bounds, baseline=None):
    e = gate(w, fs, bounds)
    if baseline is None:
        baseline = np.median(w, axis=-1)
    return np.max(np.abs(e - np.asarray(baseline)[..., None]), axis=-1)


def snr(w, fs, echo_bounds, noise_bounds):
    n = gate(w, fs, noise_bounds)
    sigma = np.std(n, axis=-1, ddof=1)
    amp = echo_amplitudes(w, fs, echo_bounds, np.mean(n, axis=-1))
    return 20 * np.log10(np.maximum(amp, 1e-12) / np.maximum(sigma, 1e-12)), amp, sigma


def save_summary(args, name, results):
    path = target(args, name)
    write_csv([results], path)


def figure(args, name, draw):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    draw(ax)
    fig.tight_layout()
    path = target(args, name, 'png')
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print(path)
