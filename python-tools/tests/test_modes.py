"""Hardware-free checks for firmware acquisition-mode selection and decoding."""
import io
import struct
import sys
import types
import unittest
import zlib
from unittest.mock import patch

import numpy as np
from lib import protocol


def mock_serial_modules():
    serial = types.ModuleType('serial')
    tools = types.ModuleType('serial.tools')
    list_ports = types.ModuleType('serial.tools.list_ports')
    list_ports.comports = lambda: []
    serial.tools = tools
    tools.list_ports = list_ports
    return {'serial': serial, 'serial.tools': tools, 'serial.tools.list_ports': list_ports}


class AcquisitionModeTests(unittest.TestCase):
    def test_mode_commands_use_firmware_processing(self):
        with patch.dict(sys.modules, mock_serial_modules()):
            from lib.device import Pic0rick
            class FakeReader:
                def __init__(self):
                    self.frame_type = 'raw'
                def read_frame(self):
                    return types.SimpleNamespace(header=types.SimpleNamespace(payload_name=self.frame_type))

            device = Pic0rick.__new__(Pic0rick)
            device.reader = FakeReader()
            commands = []
            device.command = commands.append

            for mode, line, expected in [
                ('raw', 'read_raw', 'raw'),
                ('fft', 'read_fft', 'envelope'),
                ('a-law', 'acq alaw', 'alaw'),
                ('alaw', 'acq alaw', 'alaw'),
                ('envelope', 'read_fft', 'envelope'),
            ]:
                device.reader.frame_type = expected
                self.assertEqual(device.capture(mode).header.payload_name, expected)
                self.assertEqual(commands[-1], line)

            with self.assertRaisesRegex(ValueError, 'Mode must'):
                device.capture('unsupported')
            device.reader.frame_type = 'raw'
            with self.assertRaisesRegex(ValueError, 'Unexpected frame type'):
                device.capture('fft')

    def test_three_frame_types_decode_correctly(self):
        examples = [
            (1, np.arange(8000, dtype='<u2')),
            (2, np.linspace(0, 256, 4096, dtype='<f4')),
            (3, np.arange(4096, dtype=np.uint8)),
        ]
        for frame_type, data in examples:
            with self.subTest(frame_type=frame_type):
                payload = data.tobytes()
                header = protocol.HEADER.pack(
                    b'P0RK', 1, frame_type, 0, 1, len(data), 60000000,
                    len(payload), 123, 512.0, 280.0, 512.0,
                    75, 6000, 75, 0, zlib.crc32(payload),
                )
                decoded = protocol.FrameReader(io.BytesIO(header + payload)).read_frame()
                np.testing.assert_array_equal(decoded.samples(), data)

    def test_alaw_decompression_uses_frame_reference(self):
        compressed = np.array([0, 255], dtype=np.uint8)
        np.testing.assert_allclose(protocol.alaw_decode(compressed, 640.0),
                                   [0.0, 640.0], rtol=1e-6, atol=1e-4)
        np.testing.assert_allclose(protocol.alaw_decode(compressed, 100.0),
                                   [0.0, 100.0], rtol=1e-6, atol=1e-4)


if __name__ == '__main__':
    unittest.main()
