import csv
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


FIELDS = ('row', 'col', 'x_mm', 'y_mm', 'dx_mm', 'dy_mm', 'amplitude_pp', 'flaw_pp', 'tof_us', 'averages')


def arguments(parser):
    parser.add_argument('--width-mm', type=float, default=14.0)
    parser.add_argument('--height-mm', type=float, default=6.0)
    parser.add_argument('--margin-mm', type=float, default=1.0)
    parser.add_argument('--nx', type=int, default=None, help='Legacy current-position mode; requires --ny')
    parser.add_argument('--ny', type=int, default=None, help='Legacy current-position mode; requires --nx')
    parser.add_argument('--dx-mm', type=float, default=0.8)
    parser.add_argument('--dy-mm', type=float, default=0.8)
    parser.add_argument('--speed-mm-s', type=float, default=20.0)
    parser.add_argument('--gate-start-us', type=float, default=75.0)
    parser.add_argument('--gate-end-us', type=float, default=95.0)
    parser.add_argument('--flaw-gate-start-us', type=float, default=85.5)
    parser.add_argument('--flaw-gate-end-us', type=float, default=86.7)
    parser.add_argument('--tof-gate-start-us', type=float, default=75.0)
    parser.add_argument('--tof-gate-end-us', type=float, default=95.0)
    parser.add_argument('--tof-threshold', type=int, default=20)
    parser.add_argument('--averages', type=int, default=1)
    parser.add_argument('--settle-ms', type=int, default=10)
    parser.add_argument('--output', default='results/cscan.png')
    parser.add_argument('--csv-out', default='results/cscan.csv')
    parser.add_argument('--csv', default=None)
    parser.add_argument('--arm', action='store_true')
    parser.add_argument('--port', default=None)
    parser.add_argument('--gain', type=int, default=None)
    parser.add_argument('--legacy-steps-per-mm', type=float, default=None,
                        help='Required for replay of old step-coordinate CSVs; 50 for standard 1/8 XY')


def save_image(data, output, tof_levels=None):
    rows = sorted({p['row'] for p in data})
    cols = sorted({p['col'] for p in data})
    if not rows or not cols:
        raise ValueError('No scan points')
    if rows != list(range(len(rows))) or cols != list(range(len(cols))):
        raise ValueError('Noncontiguous scan grid')
    fields = [('amplitude_pp', 'Amplitude scan', 'Intensity (ADC p-p)'),
              ('flaw_pp', 'Flaw scan', 'Intensity (ADC p-p)'),
              ('tof_us', 'TOF scan', 'Time (µs)')]
    fields = [f for f in fields if any(f[0] in p for p in data)]
    grids = {key: np.full((len(rows), len(cols)), np.nan) for key, _, _ in fields}
    seen = set()
    for p in data:
        r, c = p['row'], p['col']
        if (r, c) in seen:
            raise ValueError(f'Duplicate scan pixel {r}, {c}')
        seen.add((r, c))
        for key, _, _ in fields:
            grids[key][r, c] = p.get(key, np.nan)
    x = [np.median([p['x_mm'] for p in data if p['col'] == c]) for c in cols]
    y = [np.median([p['y_mm'] for p in data if p['row'] == r]) for r in rows]
    dx = float(np.median(np.diff(x))) if len(cols) > 1 else data[0].get('dx_mm', 0.02) or 0.02
    dy = float(np.median(np.diff(y))) if len(rows) > 1 else data[0].get('dy_mm', 0.02) or 0.02
    x_span, y_span = x[-1] - x[0], y[-1] - y[0]
    extent = [-dx/2, x_span+dx/2, -dy/2, y_span+dy/2]
    fig, axes = plt.subplots(1, len(fields), figsize=(6.5*len(fields), 5.3), constrained_layout=True, squeeze=False)
    for ax, (key, title, label) in zip(axes[0], fields):
        values = grids[key]
        valid = values[np.isfinite(values)]
        if key == 'tof_us':
            low, high = tof_levels or ((float(valid.min()), float(valid.max())) if valid.size else (0.0, 1.0))
            if high <= low:
                high = low + 1/60
        else:
            low, high = 0, 1023 if key == 'amplitude_pp' else max(1, float(valid.max())) if valid.size else 1
        plotted = ax.imshow(np.ma.masked_invalid(values), origin='lower', interpolation='nearest',
                            cmap='viridis', extent=extent, aspect='equal', vmin=low, vmax=high)
        ax.set_xlim(0, max(dx/2, x_span))
        ax.set_ylim(0, max(dy/2, y_span))
        ax.set_xlabel('X (mm)')
        ax.set_ylabel('Y (mm)')
        ax.set_title(title)
        fig.colorbar(plotted, ax=ax, label=label)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)
    return grids['amplitude_pp']


def collect(points, nx, ny, csv_out, png_out, tof_levels=None):
    data = []
    seen = set()
    Path(csv_out).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_out, 'w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for point in points:
            row, col = point['row'], point['col']
            if not (0 <= row < ny and 0 <= col < nx):
                raise ValueError(f'Out of bounds pixel {row}, {col}')
            if (row, col) in seen:
                raise ValueError(f'Duplicate pixel {row}, {col}')
            seen.add((row, col))
            writer.writerow({name: point.get(name, '') for name in FIELDS})
            file.flush()
            data.append(point)
    if len(seen) != nx * ny:
        raise ValueError(f'Incomplete scan: {len(seen)} / {nx * ny} pixels; partial CSV saved')
    save_image(data, png_out, tof_levels)
    return data


def load_csv(path, legacy_steps_per_mm=None):
    with open(path, newline='') as file:
        result = []
        for row in csv.DictReader(file):
            point = {key: int(row[key]) for key in ('row', 'col', 'amplitude_pp')}
            if row.get('x_mm') not in (None, '') and row.get('y_mm') not in (None, ''):
                point.update(x_mm=float(row['x_mm']), y_mm=float(row['y_mm']))
            else:
                if legacy_steps_per_mm is None or not np.isfinite(legacy_steps_per_mm) or legacy_steps_per_mm <= 0:
                    raise ValueError('Legacy step-coordinate CSV needs --legacy-steps-per-mm (e.g. 50 at 1/8 microstepping)')
                point.update(x_mm=int(row['x_steps']) / legacy_steps_per_mm,
                             y_mm=int(row['y_steps']) / legacy_steps_per_mm)
            for key in ('flaw_pp', 'averages'):
                if row.get(key) not in (None, ''):
                    point[key] = int(row[key])
            for key in ('tof_us', 'dx_mm', 'dy_mm'):
                if row.get(key) not in (None, ''):
                    point[key] = float(row[key])
            result.append(point)
        return result


def run(args):
    if args.csv:
        data = load_csv(args.csv, args.legacy_steps_per_mm)
        save_image(data, args.output)
        print(args.output)
        return
    if not args.arm:
        raise ValueError('Live scanning requires --arm to explicitly enable the pulser')
    centered = args.nx is None and args.ny is None
    if not centered and (args.nx is None or args.ny is None or not (1 <= args.nx <= 1000 and 1 <= args.ny <= 1000 and args.nx*args.ny <= 100000)):
        raise ValueError('Legacy grid requires both --nx and --ny with valid dimensions')
    gates = [(args.gate_start_us, args.gate_end_us),
             (args.flaw_gate_start_us, args.flaw_gate_end_us),
             (args.tof_gate_start_us, args.tof_gate_end_us)]
    indices = [(round(start*60), round(end*60)) for start, end in gates]
    if not all(0 <= start < end <= 8000 for start, end in indices):
        raise ValueError('All three gates must fit in the 8000-sample capture at 60 MHz')
    if not 1 <= args.averages <= 256 or not 1 <= args.tof_threshold <= 1023:
        raise ValueError('Invalid averages or minimum TOF echo amplitude')
    from lib.device import Pic0rick
    probe = Pic0rick(port=args.port)
    try:
        if centered:
            from lib.scan_geometry import centered_plan
            plan = centered_plan(probe.geometry(), args.width_mm, args.height_mm, args.margin_mm, args.dx_mm, args.dy_mm)
            args.nx, args.ny = plan['nx'], plan['ny']
            args.dx_mm, args.dy_mm = plan['dx_mm'], plan['dy_mm']
            print(f'Centered scan: {args.nx} x {args.ny} points; bottom left {plan["home_start_x_mm"]:.2f}, {plan["home_start_y_mm"]:.2f} mm from home')
        if args.gain is not None:
            probe.set_gain(args.gain)
        probe.arm_pulser()
        points = probe.scan(args.nx, args.ny, args.dx_mm, args.dy_mm,
                            args.speed_mm_s, *indices[0], args.settle_ms,
                            flaw_gate_start=indices[1][0], flaw_gate_end=indices[1][1],
                            averages=args.averages, tof_gate_start=indices[2][0],
                            tof_gate_end=indices[2][1], tof_threshold=args.tof_threshold, centered=centered, progress=print)
        try:
            data = collect(points, args.nx, args.ny, args.csv_out, args.output, gates[2])
        finally:
            points.close()
        print(f'{len(data)} pixels: {args.output} | {args.csv_out}')
    finally:
        try:
            probe.disarm_pulser()
        except (OSError, TimeoutError, RuntimeError):
            pass
        probe.close()
