"""Hardware-free tests for robust pic0rick USB selection and startup."""
import types
import unittest
from unittest.mock import patch
from tests.test_modes import mock_serial_modules


class FakeSerial:
    def __init__(self, port, **kwargs):
        self.port = port
        self.timeout = kwargs['timeout']
        self.write_timeout = kwargs['write_timeout']
        self.dtr = False
        self.closed = False
        self.writes = []
        self.respond_status_after = 0
        self.status_requests = 0
        self.ok = True

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        pass

    def readline(self):
        if self.writes[-1] == b'status\n':
            self.status_requests += 1
            if self.status_requests <= self.respond_status_after:
                return b''
            if not self.ok:
                return b'NOT A PICORICK\r\n'
            return b'OK board=pic0rick firmware=dev samples=8000\r\n'
        if self.writes[-1] == b'dac write 460\n':
            return b'OK dac=460\r\n'
        return b'ERR COMMAND unknown command\r\n'

    def close(self):
        self.closed = True


def port(device, vid=None, pid=None, description=None):
    return types.SimpleNamespace(device=device, vid=vid, pid=pid,
                                 description=description or device,
                                 manufacturer='')


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        with patch.dict('sys.modules', mock_serial_modules()):
            from lib import device
        self.device = device

    def test_selects_pic0rick_instead_of_first_linux_port(self):
        p = [port('/dev/ttyS0'), port('/dev/ttyACM1', 0xCAFE, 0x4011)]
        factory = []
        def serial_factory(name, **kwargs):
            s = FakeSerial(name, **kwargs)
            factory.append(s)
            return s
        with patch.object(self.device.list_ports, 'comports', return_value=p), \
             patch.object(self.device.serial, 'Serial', side_effect=serial_factory, create=True), \
             patch.object(self.device.time, 'sleep'), \
             patch.dict('os.environ', {'PIC0RICK_PORT': ''}):
            probe = self.device.Pic0rick(timeout=0.1)
            self.assertEqual(probe.port, '/dev/ttyACM1')
            self.assertTrue(probe.ser.dtr)
            self.assertEqual(probe.ser.writes, [b'status\n'])
            self.assertEqual(probe.set_gain(460), 'OK dac=460')
            probe.close()
        self.assertTrue(factory[0].closed)

    def test_fails_with_explicit_instructions_if_no_pico_detected(self):
        with patch.object(self.device.list_ports, 'comports',
                          return_value=[port('/dev/ttyS0')]), \
             patch.dict('os.environ', {'PIC0RICK_PORT': ''}):
            with self.assertRaisesRegex(OSError, 'No pic0rick USB CDC device'):
                self.device.Pic0rick()

    def test_status_retry_after_cold_start(self):
        instances = []
        def make(name, **kwargs):
            s = FakeSerial(name, **kwargs)
            s.respond_status_after = 1
            instances.append(s)
            return s
        with patch.object(self.device.serial, 'Serial', side_effect=make, create=True), \
             patch.object(self.device.time, 'sleep'):
            d = self.device.Pic0rick(port='/dev/ttyACM0', timeout=0.1)
        self.assertEqual(instances[0].writes, [b'status\n', b'status\n'])
        d.close()

    def test_no_firmware_response_explains_issue_and_closes_port(self):
        instances = []
        def make(name, **kwargs):
            s = FakeSerial(name, **kwargs)
            s.respond_status_after = 99
            instances.append(s)
            return s
        with patch.object(self.device.serial, 'Serial', side_effect=make, create=True), \
             patch.object(self.device.time, 'sleep'):
            with self.assertRaisesRegex(ConnectionError, 'did not return a valid pic0rick firmware status'):
                self.device.Pic0rick(port='/dev/ttyACM0', timeout=0.1)
        self.assertTrue(instances[0].closed)


if __name__ == '__main__':
    unittest.main()
