import io
import math
import unittest
import zlib
from unittest.mock import patch

import numpy as np
from lib import protocol
from lib.plot_ranges import waveform_y_range
from tests.test_modes import mock_serial_modules


class MetricScanTests(unittest.TestCase):
    def test_scan_metric_protocol(self):
        with patch.dict('sys.modules', mock_serial_modules()):
            from lib.device import Pic0rick
        raw = np.arange(8000, dtype='<u2') % 1024
        payload = raw.tobytes()
        frame = protocol.HEADER.pack(b'P0RK', 1, 1, 16, 0, 8000, 60000000,
                    len(payload), 0, 512., 0., 1., 75, 6000, 75, 0, zlib.crc32(payload)) + payload
        class SerialFake(io.BytesIO):
            timeout = 3.0
            def __init__(self):
                super().__init__(b'OK scan started nx=2 ny=1 sample_rate=60000000 dx_mm=0.820 dy_mm=0.800\r\n'
                                 b'SCAN_POINT 0 0 10.000 20.000 120 12 85.500000\r\n' + frame +
                                 b'SCAN_POINT 0 1 10.820 20.000 30 20 -1.000000\r\n' +
                                 protocol.HEADER.pack(b'P0RK', 1, 1, 16, 1, 8000, 60000000,
                                    len(payload), 0, 512., 0., 1., 75, 6000, 75, 0, zlib.crc32(payload)) + payload +
                                 b'SCAN_DONE 2\r\n')
                self.commands = []
            def write(self, data):
                self.commands.append(data)
            def flush(self):
                pass
        probe = Pic0rick.__new__(Pic0rick)
        probe.ser = SerialFake()
        points = list(probe.scan(2, 1, 0.819, 0.8, 20, 4500, 5700, 50,
                                 waveforms=True, flaw_gate_start=5100, flaw_gate_end=5200,
                                 averages=16, tof_gate_start=5000, tof_gate_end=5300,
                                 tof_threshold=30))
        self.assertEqual(probe.ser.commands, [b'scan_mm 2 1 0.819 0.8 20 4500 5700 50 5100 5200 16 5000 5300 30 waveforms\n'])
        self.assertEqual(points[0]['dx_mm'], 0.82)
        self.assertEqual(points[0]['tof_us'], 85.5)
        self.assertTrue(math.isnan(points[1]['tof_us']))
        self.assertEqual(points[1]['x_mm'], 10.82)
        np.testing.assert_array_equal(points[1]['waveform'], raw)
        self.assertEqual(probe.ser.timeout, 3.0)

    def test_raw_stable_across_adc_offset_changes(self):
        for data in ([800, 900], [300, 320], [0, 1023]):
            self.assertEqual(waveform_y_range('raw', data), (0, 1023))

    def test_envelope_zero_visible_and_scale_stable(self):
        old = waveform_y_range('fft', [50, 80])
        self.assertEqual(old[0], 0)
        self.assertEqual(waveform_y_range('fft', [0, 1], old), old)
        self.assertGreater(waveform_y_range('fft', [200], old)[1], old[1])
        self.assertLess(waveform_y_range('fft', [0, 1])[1], old[1])
        self.assertEqual(waveform_y_range('a-law', [0, float('nan')]), (0, 1))
