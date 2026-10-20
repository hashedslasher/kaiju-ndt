import os
import time
import serial
from serial.tools import list_ports
from . import protocol


# USB VID/PID from firmware/src/dsp/usb_descriptors.c. Never select an
# arbitrary first serial port: it may belong to a modem, debugger or driver.
PIC0RICK_USB_VID = 0xCAFE
PIC0RICK_USB_PID = 0x4011


def find_pic0rick_port():
    ports = list(list_ports.comports())
    matches = [
        item.device for item in ports
        if ((getattr(item, 'vid', None), getattr(item, 'pid', None)) ==
            (PIC0RICK_USB_VID, PIC0RICK_USB_PID))
        or 'pic0rick' in str(getattr(item, 'description', '')).lower()
        or 'pic0rick' in str(getattr(item, 'manufacturer', '')).lower()
    ]
    if len(matches) == 1:
        return matches[0]
    available = ', '.join(
        f'{item.device} ({getattr(item, "description", "unknown")})'
        for item in ports
    ) or 'none'
    if matches:
        raise OSError(
            f'Multiple pic0rick serial ports detected: {", ".join(matches)}. '
            'Specify PIC0RICK_PORT=/dev/ttyACM0 or --port when supported.'
        )
    raise OSError(
        'No pic0rick USB CDC device (VID:PID CAFE:4011) detected. '
        f'Visible serial ports: {available}. '
        'Check the USB cable, firmware, and `python -m serial.tools.list_ports -v`. '
        'If your firmware uses a different USB ID, set PIC0RICK_PORT to its port.'
    )


class Pic0rick:
    def __init__(self, port=None, verbose=False, logging=False, log_file=None, timeout=3.0):
        name = port or os.environ.get('PIC0RICK_PORT') or find_pic0rick_port()
        self.port = name
        self.ser = serial.Serial(name, baudrate=115200, timeout=timeout, write_timeout=timeout)
        self.Fech = 60e6
        self.verbose = verbose
        self.last_reply = ''
        self.reader = protocol.FrameReader(self.ser)
        try:
            # TinyUSB's CDC ready state depends on the host asserting DTR.
            self.ser.dtr = True
            time.sleep(0.35)
            self.ser.reset_input_buffer()
            last_error = None
            # A cold-starting board may miss the first command. Probe only
            # with read-only status; never auto-retry motor/pulser commands.
            for _ in range(2):
                try:
                    protocol.parse_status(self.command('status'))
                    break
                except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                    last_error = exc
                    time.sleep(0.25)
            else:
                raise ConnectionError(
                    f'Port {name} opened but did not return a valid pic0rick '
                    f'firmware status. Last error: {last_error}. '
                    'Verify the RP2350 DSP firmware is running, the port is '
                    'correct, and no other serial program is using it.'
                )
        except BaseException:
            self.ser.close()
            raise

    def command(self, text):
        self.ser.write((text + '\n').encode('ascii'))
        self.ser.flush()
        reply = self.ser.readline().decode('ascii', 'replace').strip()
        self.last_reply = reply
        if not reply:
            raise TimeoutError(
                f'No response from {self.port if hasattr(self, "port") else "serial device"} '
                f'to {text!r}. Check USB connection / active firmware.'
            )
        if not reply.startswith('OK '):
            raise RuntimeError(f'Firmware rejected {text!r}: {reply}')
        return reply

    def status(self):
        return protocol.parse_status(self.command('status'))

    def version(self):
        return self.command('version')

    def set_gain(self, value):
        if not 0 <= int(value) <= 1023:
            raise ValueError('Gain DAC value must be 0..1023')
        return self.command(f'dac write {int(value)}')

    def dac(self, value):
        return self.set_gain(value)

    def configure_pulse(self, negative_ns, damp_ns, positive_ns, order='pos-first'):
        if order not in ('pos-first', 'neg-first'):
            raise ValueError(order)
        return self.command(f'pulse config {int(negative_ns)} {int(damp_ns)} {int(positive_ns)} {order}')

    def arm_pulser(self):
        return self.command('pulser arm')

    def disarm_pulser(self):
        return self.command('pulser disarm')

    def capture(self, payload='raw'):
        """Request one already-formatted capture from the Pico 2.

        User-facing 'fft' means the firmware's FFT-based Hilbert envelope,
        not a frequency-domain spectrum. 'a-law' is that envelope compressed.
        No bandpass, FFT, Hilbert transform, or averaging runs on the host.
        """
        modes = {
            'raw': ('read_raw', 'raw'),
            'fft': ('read_fft', 'envelope'),
            'envelope': ('read_fft', 'envelope'),
            'a-law': ('acq alaw', 'alaw'),
            'alaw': ('acq alaw', 'alaw'),
        }
        try:
            command, expected = modes[payload.lower()]
        except (KeyError, AttributeError):
            raise ValueError("Mode must be raw, fft, or a-law") from None
        self.command(command)
        frame = self.reader.read_frame()
        if frame.header.payload_name != expected:
            raise ValueError(
                f'Unexpected frame type {frame.header.payload_name}; expected {expected}'
            )
        return frame

    def read_raw(self):
        return self.capture('raw')

    def read_fft(self):
        return self.capture('fft')

    def read_alaw(self):
        return self.capture('a-law')

    def stream_start(self, payload, rate):
        if payload not in ('raw', 'envelope', 'alaw'):
            raise ValueError(payload)
        return self.command(f'stream start {payload} {int(rate)}')

    def stream_frame(self):
        return self.reader.read_frame()

    def stream_stop(self):
        self.ser.write(b'stream stop\n')
        self.ser.flush()

    def jog(self, axis, direction, frequency):
        self._validate_motion(axis, direction, frequency)
        return self.command(f'jog_{axis} {direction} {int(frequency)}')

    def move(self, axis, direction, frequency, steps):
        self._validate_motion(axis, direction, frequency)
        if not 1 <= int(steps) <= 5000:
            raise ValueError('Firmware finite moves allow 1..5000 steps')
        return self.command(f'move_{axis} {direction} {int(frequency)} {int(steps)}')

    def stop(self, axis='all'):
        if axis not in ('x', 'y', 'z', 'all'):
            raise ValueError(axis)
        return self.command(f'stop_{axis}')

    def _validate_motion(self, axis, direction, frequency):
        if axis not in ('x', 'y', 'z'):
            raise ValueError(axis)
        valid = ('up', 'down') if axis == 'z' else ('plus', 'minus')
        if direction not in valid:
            raise ValueError(direction)
        if not 1 <= int(frequency) <= 50000:
            raise ValueError('Frequency must be 1..50000 Hz')

    def close(self):
        self.ser.close()
