import csv
import tempfile
import unittest
from pathlib import Path

from .scan import collect, load_csv


class ScanDualTests(unittest.TestCase):
    def test_dual_map(self):
        pts = [
            {'row': 0, 'col': 0, 'x_mm': 0.0, 'y_mm': 0.0, 'amplitude_pp': 220, 'flaw_pp': 4, 'averages': 16, 'tof_us': 86.0, 'dx_mm': 0.8, 'dy_mm': 0.8},
            {'row': 0, 'col': 1, 'x_mm': 0.8, 'y_mm': 0.0, 'amplitude_pp': 100, 'flaw_pp': 135, 'averages': 16, 'tof_us': 86.0, 'dx_mm': 0.8, 'dy_mm': 0.8},
        ]
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / 'dual.csv'
            png_path = Path(folder) / 'dual.png'
            collect(pts, 2, 1, csv_path, png_path)
            self.assertTrue(png_path.exists())
            self.assertEqual(load_csv(csv_path), pts)

    def test_legacy_csv_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / 'legacy.csv'
            csv_path.write_text('row,col,x_steps,y_steps,amplitude_pp\n0,0,0,0,400\n')
            self.assertEqual(load_csv(csv_path, 50)[0]['amplitude_pp'], 400)


if __name__ == '__main__':
    unittest.main()
