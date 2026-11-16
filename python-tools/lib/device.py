import os
import math
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


class _ExactSerialView:
    def __init__(self, serial_port):
        self.serial_port = serial_port
        self.in_waiting = 0

    def read(self, count):
        return self.serial_port.read(count)


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

    def temperature(self):
        reply = self.command('temp')
        if reply == 'OK temp=pending':
            return None
        if not reply.startswith('OK temp_c='):
            raise ValueError(f'Unexpected temperature reply: {reply}')
        value = float(reply.partition('=')[2])
        if not -55.0 <= value <= 125.0:
            raise ValueError(f'Invalid temperature reading: {value}')
        return value

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

    def home(self):
        return self.command('home')

    def position(self):
        return self.command('pos')

    def zero(self, axis='z'):
        if axis not in ('x', 'y', 'z', 'all'):
            raise ValueError(axis)
        return self.command(f'pos_zero {axis}')

    def jog(self, axis, direction, speed_mm_s):
        self._validate_motion(axis, direction, speed_mm_s)
        return self.command(f'jog_mm_{axis} {direction} {float(speed_mm_s):g}')

    def move(self, axis, direction, speed_mm_s, distance_mm):
        self._validate_motion(axis, direction, speed_mm_s)
        if not math.isfinite(distance_mm) or distance_mm <= 0:
            raise ValueError('Distance must be positive and finite (mm)')
        return self.command(f'move_mm_{axis} {direction} {float(speed_mm_s):g} {float(distance_mm):g}')

    def geometry(self):
        return self.command('geometry')

    def stop(self, axis='all'):
        if axis not in ('x', 'y', 'z', 'all'):
            raise ValueError(axis)
        return self.command(f'stop_{axis}')

    def _validate_motion(self, axis, direction, speed_mm_s):
        if axis not in ('x', 'y', 'z'):
            raise ValueError(axis)
        valid = ('up', 'down') if axis == 'z' else ('plus', 'minus')
        if direction not in valid:
            raise ValueError(direction)
        if not math.isfinite(speed_mm_s) or speed_mm_s <= 0:
            raise ValueError('Speed must be positive and finite (mm/s)')

    def scan(self, nx, ny, dx_mm, dy_mm, speed_mm_s,
             gate_start, gate_end, settle_ms=10, waveforms=False,
             flaw_gate_start=0, flaw_gate_end=0, averages=1,
             tof_gate_start=None, tof_gate_end=None, tof_threshold=20, centered=False, progress=None):
        tof_gate_start = gate_start if tof_gate_start is None else tof_gate_start
        tof_gate_end = gate_end if tof_gate_end is None else tof_gate_end
        integers = (nx, ny, gate_start, gate_end, settle_ms, flaw_gate_start,
                    flaw_gate_end, averages, tof_gate_start, tof_gate_end, tof_threshold)
        if any(type(value) is not int or value < 0 for value in integers):
            raise ValueError('Scan indices and counts must be nonnegative integers')
        if not 1 <= nx <= 1000 or not 1 <= ny <= 1000 or nx * ny > 100000:
            raise ValueError('Invalid scan dimensions')
        if any(not math.isfinite(v) or v < 0 for v in (dx_mm, dy_mm, speed_mm_s)) or speed_mm_s <= 0:
            raise ValueError('Invalid metric spacing or speed')
        if (nx > 1 and dx_mm <= 0) or (ny > 1 and dy_mm <= 0):
            raise ValueError('Spacing must be positive for multi-point axes')
        if not 0 <= gate_start < gate_end <= 8000:
            raise ValueError('Amplitude gate must be inside the 8000-sample raw capture')
        if (flaw_gate_start or flaw_gate_end) and not 0 <= flaw_gate_start < flaw_gate_end <= 8000:
            raise ValueError('Flaw gate must be inside the 8000-sample raw capture')
        if not 0 <= tof_gate_start < tof_gate_end <= 8000 or not 0 <= tof_threshold <= 1023:
            raise ValueError('Invalid TOF gate or threshold')
        if not 1 <= averages <= 256 or settle_ms > 60000:
            raise ValueError('Invalid averages or settle time')
        values = (nx, ny, f'{dx_mm:g}', f'{dy_mm:g}', f'{speed_mm_s:g}',
                  gate_start, gate_end, settle_ms, flaw_gate_start, flaw_gate_end,
                  averages, tof_gate_start, tof_gate_end, tof_threshold)
        command = 'scan_mm ' + ' '.join(map(str, values))
        if waveforms:
            command += ' waveforms'
        if centered:
            command += ' centered'
        scan_frames = protocol.FrameReader(_ExactSerialView(self.ser), read_size=16384) if waveforms else None
        old_timeout = self.ser.timeout
        self.ser.timeout = max(105.0, settle_ms / 1000.0 + 30.0,
                               (100.0 if centered else max(dx_mm, dy_mm)) / speed_mm_s + 30.0)
        complete = False
        try:
            reply = self.command(command)
            fields = dict(part.split('=', 1) for part in reply.split() if '=' in part)
            actual_dx = float(fields['dx_mm'])
            actual_dy = float(fields['dy_mm'])
            received = 0
            if progress is not None:
                progress('Homing X/Y')
            while True:
                line = self.ser.readline().decode('ascii', 'replace').strip()
                if not line:
                    raise TimeoutError('Timed out waiting for scan point')
                parts = line.split()
                if parts[0] in ('SCAN_POSITIONING', 'SCAN_RETURN_HOME') and len(parts) == 1:
                    if progress is not None:
                        progress('Returning home' if parts[0] == 'SCAN_RETURN_HOME' else 'Positioning to scan origin')
                    continue
                if parts[0] == 'SCAN_POINT' and len(parts) == 8:
                    row, col = map(int, parts[1:3])
                    x, y = map(float, parts[3:5])
                    amplitude, flaw = map(int, parts[5:7])
                    tof_us = float(parts[7])
                    point = {
                        'row': row, 'col': col, 'x_mm': x, 'y_mm': y,
                        'dx_mm': actual_dx, 'dy_mm': actual_dy,
                        'amplitude_pp': amplitude, 'flaw_pp': flaw,
                        'tof_us': tof_us if tof_us >= 0 else float('nan'),
                        'averages': averages,
                    }
                    if waveforms:
                        frame = scan_frames.read_frame()
                        if (frame.header.payload_name != 'raw' or
                                frame.header.sample_count != 8000 or
                                frame.header.sample_rate_hz != 60000000 or
                                frame.header.sequence != received):
                            raise ValueError('Scan waveform does not match scan point')
                        point['waveform'] = frame.samples()
                        point['sample_rate_hz'] = frame.header.sample_rate_hz
                    received += 1
                    yield point
                elif parts[0] == 'SCAN_DONE' and len(parts) == 2:
                    if received != nx * ny or int(parts[1]) != received:
                        raise RuntimeError(f'Incomplete scan: {received}/{nx * ny}')
                    complete = True
                    return
                elif parts[0] in ('SCAN_ABORT', 'SCAN_ERROR'):
                    raise RuntimeError(line)
                elif parts[0] == 'ERR':
                    raise RuntimeError(line)
                else:
                    raise ValueError(f'Unexpected scan reply: {line}')
        finally:
            if not complete:
                try:
                    self.ser.write(b'scan stop\n')
                    self.ser.flush()
                except (OSError, serial.SerialException):
                    pass
            self.ser.timeout = old_timeout

    def close(self):
        self.ser.close()
