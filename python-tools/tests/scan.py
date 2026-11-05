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
    fig, ax = plt.subplots(figsize=(9, 6))
    plotted = ax.imshow(np.ma.masked_invalid(image), origin='lower',
                        interpolation='nearest', cmap='viridis', extent=extent,
                        aspect='equal')
    ax.set_xlabel('X (mm)' if steps_mm_x else 'X (motor steps)')
    ax.set_ylabel('Y (mm)' if steps_mm_y else 'Y (motor steps)')
    ax.set_title('Ultrasonic amplitude C-scan')
    fig.colorbar(plotted, ax=ax, label='Gated peak-to-peak amplitude (ADC counts)')
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)
    return image


def collect(points, nx, ny, csv_out, png_out, steps_mm_x=None, steps_mm_y=None):
    data = []
    seen = set()
    Path(csv_out).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_out, 'w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=(
            'row', 'col', 'x_steps', 'y_steps', 'amplitude_pp'))
        writer.writeheader()
        for point in points:
            row, col = point['row'], point['col']
            if not (0 <= row < ny and 0 <= col < nx):
                raise ValueError(f'Out of bounds pixel {row}, {col}')
            if (row, col) in seen:
                raise ValueError(f'Duplicate pixel {row}, {col}')
            seen.add((row, col))
            writer.writerow(point)
            file.flush()
            data.append(point)
    if len(seen) != nx * ny:
        raise ValueError(f'Incomplete scan: {len(seen)} / {nx * ny} pixels; partial CSV saved')
    save_image(data, png_out, steps_mm_x, steps_mm_y)
    return data


def load_csv(path):
    with open(path, newline='') as file:
        return [{key: int(row[key]) for key in
                 ('row', 'col', 'x_steps', 'y_steps', 'amplitude_pp')}
                for row in csv.DictReader(file)]


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
    if not 0 <= args.gate_start_us < args.gate_end_us:
        raise ValueError('Invalid gate times')
    from lib.device import Pic0rick
    probe = Pic0rick(port=args.port)
    try:
        sample_rate = args.sample_rate
        gate_start = int(round(args.gate_start_us * sample_rate / 1e6))
        gate_end = int(round(args.gate_end_us * sample_rate / 1e6))
        if not 0 <= gate_start < gate_end <= 8000:
            raise ValueError('Selected gate does not fit in the 8000-sample capture')
        if args.gain is not None:
            probe.set_gain(args.gain)
        probe.arm_pulser()
        points = probe.scan(args.nx, args.ny, args.dx_steps, args.dy_steps,
                            args.hz, gate_start, gate_end, args.settle_ms)
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
