import unittest
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from lib.scan_geometry import centered_axis, centered_plan
from lib.bscan import bscan_line, rectify_waveforms, sample_window
from tests.test_modes import mock_serial_modules


GEOMETRY = 'OK units=mm microsteps=8 x_steps_per_mm=50 y_steps_per_mm=50 xmax=420.000 ymax=220.000 max_move_mm=100.000'


class CenteredBscanTests(unittest.TestCase):
    def test_coupon_and_margin(self):
        p = centered_plan(GEOMETRY, 14, 6, 1, .8, .8)
        self.assertEqual((p['nx'], p['ny']), (21, 11))
        self.assertEqual((p['home_start_x_mm'], p['home_start_y_mm']), (218, 114))
        self.assertEqual((p['home_end_x_mm'], p['home_end_y_mm']), (202, 106))
        self.assertEqual((p['x0_mm'], p['y0_mm']), (0, 0))

    def test_rounding_covers_both_sides(self):
        for size, margin, pitch in [(14.001, .12, .83), (14, 0, .8), (.021, 0, .02), (20, 0, .31)]:
            p = centered_axis(size, margin, pitch, 50, 420, 100)
            self.assertLessEqual(p['local_start_mm'], -(size/2+margin))
            self.assertGreaterEqual(p['local_end_mm'], size/2+margin)
            self.assertAlmostEqual(p['local_end_mm'] - p['local_start_mm'], (p['count']-1)*p['pitch_mm'])
        with self.assertRaises(ValueError):
            centered_plan(GEOMETRY, 420, 6, 1, .8, .8)
        with self.assertRaises(ValueError):
            centered_plan(GEOMETRY, 14, 6, 0, .001, .8)
        with self.assertRaises(ValueError):
            centered_plan('OK microsteps=8', 14, 6, 1, .8, .8)

    def test_bscan_line_and_mask(self):
        raw = np.array([[500, 600, 400, 500], [500, 500, 500, 500], [500, 550, 450, 500]], dtype=np.uint16)
        np.testing.assert_array_equal(rectify_waveforms(raw[0], 1, 3), [100, 100])
        out = bscan_line(raw, [True, False, True], 1, 3)
        np.testing.assert_array_equal(out[:, [0, 2]], [[100, 50], [100, 50]])
        self.assertTrue(np.all(np.isnan(out[:, 1])))
        self.assertEqual(sample_window(70, 100), (4200, 6000))

    def test_independent_bscan_gate(self):
        self.assertEqual(sample_window(60, 110), (3600, 6600))
        self.assertEqual(sample_window(85.5, 86.7), (5130, 5202))
        self.assertEqual(sample_window(0, 8000 / 60), (0, 8000))
        for start, end in [(90, 80), (90, 90), (-1, 20), (120, 140)]:
            with self.assertRaises(ValueError):
                sample_window(start, end)

    def test_centered_command_and_positioning_messages(self):
        with patch.dict('sys.modules', mock_serial_modules()):
            from lib.device import Pic0rick
        class SerialFake(io.BytesIO):
            timeout = 3.0
            def __init__(self):
                super().__init__(b'OK scan started nx=2 ny=2 sample_rate=60000000 dx_mm=0.800 dy_mm=0.800\r\n'
                                 b'SCAN_POSITIONING\r\nSCAN_POSITIONING\r\n'
                                 b'SCAN_POINT 0 0 0.000 0.000 10 4 85.000000\r\n'
                                 b'SCAN_POINT 0 1 0.800 0.000 11 5 85.100000\r\n'
                                 b'SCAN_POINT 1 1 0.800 0.800 12 6 85.200000\r\n'
                                 b'SCAN_POINT 1 0 0.000 0.800 13 7 85.300000\r\nSCAN_RETURN_HOME\r\nSCAN_DONE 4\r\n')
                self.commands = []
            def write(self, data): self.commands.append(data)
            def flush(self): pass
        probe = Pic0rick.__new__(Pic0rick)
        probe.ser = SerialFake()
        stages = []
        points = list(probe.scan(2, 2, .8, .8, 20, 4500, 5700, centered=True, progress=stages.append))
        self.assertEqual(stages, ['Homing X/Y', 'Positioning to scan origin', 'Positioning to scan origin', 'Returning home'])
        self.assertTrue(probe.ser.commands[0].endswith(b' centered\n'))
        self.assertEqual([p['x_mm'] for p in points], [0, .8, .8, 0])
        self.assertEqual(probe.ser.timeout, 3.0)

    def test_saved_maps_zero_origin(self):
        from tests.scan import save_image, plt
        data = [dict(row=r, col=c, x_mm=-.4+c*.8, y_mm=-.4+r*.8,
                     dx_mm=.8, dy_mm=.8, amplitude_pp=20, flaw_pp=2, tof_us=85.)
                for r in range(2) for c in range(2)]
        figures = []
        original = plt.subplots
        def record(*args, **kwargs):
            fig, axes = original(*args, **kwargs)
            figures.append(axes)
            return fig, axes
        with tempfile.TemporaryDirectory() as folder, patch.object(plt, 'subplots', side_effect=record):
            save_image(data, Path(folder) / 'scan.png')
            self.assertTrue((Path(folder) / 'scan.png').exists())
        for ax in figures[0][0]:
            np.testing.assert_allclose(ax.get_xlim(), (0, .8))
            np.testing.assert_allclose(ax.get_ylim(), (0, .8))
            self.assertEqual(ax.get_xlabel(), 'X (mm)')
