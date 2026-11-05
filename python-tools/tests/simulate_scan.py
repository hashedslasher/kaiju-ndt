import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.scan import collect


def fake_points(nx, ny, dx_steps, dy_steps):
    rng = np.random.default_rng(42)
    holes = ((0.32 * (nx - 1), 0.35 * (ny - 1), 0.12 * min(nx, ny)),
             (0.73 * (nx - 1), 0.68 * (ny - 1), 0.16 * min(nx, ny)))
    for row in range(ny):
        columns = range(nx) if row % 2 == 0 else range(nx - 1, -1, -1)
        for col in columns:
            amp = 260.0
            for cx, cy, radius in holes:
                amp -= 180.0 * np.exp(-0.5 * (((col - cx)**2 +
                                                (row - cy)**2) / radius**2))
            yield {'row': row, 'col': col,
                   'x_steps': col * dx_steps,
                   'y_steps': row * dy_steps,
                   'amplitude_pp': int(max(0, amp + rng.normal(0, 5)))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--nx', type=int, default=60)
    parser.add_argument('--ny', type=int, default=40)
    parser.add_argument('--dx-steps', type=int, default=40)
    parser.add_argument('--dy-steps', type=int, default=40)
    parser.add_argument('--output', default='results/demo_cscan.png')
    parser.add_argument('--csv-out', default='results/demo_cscan.csv')
    args = parser.parse_args()
    collect(fake_points(args.nx, args.ny, args.dx_steps, args.dy_steps),
            args.nx, args.ny, args.csv_out, args.output)
    print(args.output)
    print(args.csv_out)


if __name__ == '__main__':
    main()
