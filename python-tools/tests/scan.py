import csv
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def arguments(parser):
    parser.add_argument('--nx', type=int, default=60)
    parser.add_argument('--ny', type=int, default=40)
    parser.add_argument('--dx-steps', type=int, default=40)
    parser.add_argument('--dy-steps', type=int, default=40)
    parser.add_argument('--hz', type=int, default=1000)
    parser.add_argument('--sample-rate', type=int, default=60000000)
    parser.add_argument('--gate-start-us', type=float, default=75.0)
    parser.add_argument('--gate-end-us', type=float, default=95.0)
    parser.add_argument('--flaw-gate-start-us', type=float, default=85.5)
    parser.add_argument('--flaw-gate-end-us', type=float, default=86.7)
    parser.add_argument('--averages', type=int, default=1)
    parser.add_argument('--settle-ms', type=int, default=10)
    parser.add_argument('--output', default='results/cscan.png')
    parser.add_argument('--csv-out', default='results/cscan.csv')
    parser.add_argument('--csv', default=None)
    parser.add_argument('--arm', action='store_true')
    parser.add_argument('--port', default=None)
    parser.add_argument('--gain', type=int, default=None)
    parser.add_argument('--steps-mm-x', type=float, default=None)
    parser.add_argument('--steps-mm-y', type=float, default=None)


def save_image(data, output, steps_mm_x=None, steps_mm_y=None):
    rows = sorted({point['row'] for point in data})
    cols = sorted({point['col'] for point in data})
    if not rows or not cols:
        raise ValueError('No scan points')
    if rows != list(range(len(rows))) or cols != list(range(len(cols))):
        raise ValueError('Noncontiguous scan grid')
    image = np.full((len(rows), len(cols)), np.nan)
    for point in data:
        r, c = point['row'], point['col']
        if np.isfinite(image[r, c]):
            raise ValueError(f'Duplicate scan pixel {r}, {c}')
        image[r, c] = point['amplitude_pp']
    x_by_col = [np.median([p['x_steps'] for p in data if p['col'] == i])
                for i in cols]
    y_by_row = [np.median([p['y_steps'] for p in data if p['row'] == i])
                for i in rows]
    dx = np.median(np.diff(x_by_col)) if len(cols) > 1 else 1
    dy = np.median(np.diff(y_by_row)) if len(rows) > 1 else 1
    sx = steps_mm_x or 1.0
    sy = steps_mm_y or 1.0
    extent = [(x_by_col[0] - dx / 2) / sx,
              (x_by_col[-1] + dx / 2) / sx,
              (y_by_row[0] - dy / 2) / sy,
              (y_by_row[-1] + dy / 2) / sy]
    has_flaw = any('flaw_pp' in point for point in data)
    if has_flaw and not all('flaw_pp' in point for point in data):
        raise ValueError('Incomplete flaw data')
    if has_flaw:
        flaw = np.full_like(image, np.nan)
        for point in data:
            flaw[point['row'], point['col']] = point['flaw_pp']
        fig, axes = plt.subplots(1, 2, figsize=(13, 5.3), constrained_layout=True)
    else:
        fig, ax = plt.subplots(figsize=(8, 5.3), constrained_layout=True)
        axes = [ax]
    for ax, values, title in (
        [(axes[0], image, 'Amplitude scan')]
        + ([(axes[1], flaw, 'Flaw scan')] if has_flaw else [])
    ):
        vmax = 1023 if title == 'Amplitude scan' else max(1.0, float(np.nanmax(values)))
        plotted = ax.imshow(np.ma.masked_invalid(values), origin='lower',
                            interpolation='nearest', cmap='viridis', extent=extent,
                            aspect='equal', vmin=0, vmax=vmax)
        ax.set_xlabel('X')
        ax.set_ylabel('Y')
        ax.set_title(title)
        fig.colorbar(plotted, ax=ax, label='Intensity')
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)
    return image


def collect(points, nx, ny, csv_out, png_out, steps_mm_x=None, steps_mm_y=None):
    data = []
    seen = set()
    Path(csv_out).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_out, 'w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=(
            'row', 'col', 'x_steps', 'y_steps', 'amplitude_pp', 'flaw_pp', 'averages'))
        writer.writeheader()
        for point in points:
            row, col = point['row'], point['col']
            if not (0 <= row < ny and 0 <= col < nx):
                raise ValueError(f'Out of bounds pixel {row}, {col}')
            if (row, col) in seen:
                raise ValueError(f'Duplicate pixel {row}, {col}')
            seen.add((row, col))
            record = {name: point[name] for name in
                      ('row', 'col', 'x_steps', 'y_steps', 'amplitude_pp')}
            record['flaw_pp'] = point.get('flaw_pp', '')
            record['averages'] = point.get('averages', 1)
            writer.writerow(record)
            file.flush()
            data.append(point)
    if len(seen) != nx * ny:
        raise ValueError(f'Incomplete scan: {len(seen)} / {nx * ny} pixels; partial CSV saved')
    save_image(data, png_out, steps_mm_x, steps_mm_y)
    return data


def load_csv(path):
    with open(path, newline='') as file:
        result = []
        for row in csv.DictReader(file):
            fields = ('row', 'col', 'x_steps', 'y_steps', 'amplitude_pp')
            point = {key: int(row[key]) for key in fields}
            if row.get('flaw_pp') not in (None, ''):
                point['flaw_pp'] = int(row['flaw_pp'])
            if row.get('averages') not in (None, ''):
                point['averages'] = int(row['averages'])
            result.append(point)
        return result


def run(args):
    if args.csv:
        data = load_csv(args.csv)
        if not data:
            raise ValueError('Empty input CSV')
        save_image(data, args.output, args.steps_mm_x, args.steps_mm_y)
        print(args.output)
        return
    if args.nx < 1 or args.ny < 1 or args.nx * args.ny > 100000:
        raise ValueError('Invalid scan dimensions')
    if not args.arm:
        raise ValueError('Live scanning requires --arm to explicitly enable the pulser')
    if not (0 <= args.gate_start_us < args.gate_end_us and
            0 <= args.flaw_gate_start_us < args.flaw_gate_end_us):
        raise ValueError('Invalid gate times')
    if not 1 <= args.averages <= 256:
        raise ValueError('Averages must be 1..256')
    from lib.device import Pic0rick
    probe = Pic0rick(port=args.port)
    try:
        sample_rate = args.sample_rate
        gate_start = int(round(args.gate_start_us * sample_rate / 1e6))
        gate_end = int(round(args.gate_end_us * sample_rate / 1e6))
        flaw_start = int(round(args.flaw_gate_start_us * sample_rate / 1e6))
        flaw_end = int(round(args.flaw_gate_end_us * sample_rate / 1e6))
        if not (0 <= gate_start < gate_end <= 8000 and
                0 <= flaw_start < flaw_end <= 8000):
            raise ValueError('Selected gate does not fit in the 8000-sample capture')
        if args.gain is not None:
            probe.set_gain(args.gain)
        probe.arm_pulser()
        points = probe.scan(args.nx, args.ny, args.dx_steps, args.dy_steps,
                            args.hz, gate_start, gate_end, args.settle_ms,
                            flaw_gate_start=flaw_start, flaw_gate_end=flaw_end,
                            averages=args.averages)
        try:
            data = collect(points, args.nx, args.ny, args.csv_out, args.output,
                           args.steps_mm_x, args.steps_mm_y)
        finally:
            points.close()
        print(f'{len(data)} pixels: {args.output} | {args.csv_out}')
    finally:
        try:
            probe.disarm_pulser()
        except (OSError, TimeoutError, RuntimeError):
            pass
        probe.close()
