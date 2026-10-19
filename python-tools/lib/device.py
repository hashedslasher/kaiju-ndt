import os
import time
import serial
from serial.tools import list_ports
from . import dsp


class Pic0rick:
    def __init__(self, port=None, verbose=False, logging=False, log_file=None, timeout=3.0):
        name = port or os.environ.get('PIC0RICK_PORT')
        if name is None:
            ports = sorted(item.device for item in list_ports.comports())
            if not ports:
                raise OSError('No serial device found; set PIC0RICK_PORT')
            name = ports[0]
        self.ser = serial.Serial(name, baudrate=115200, timeout=timeout, write_timeout=timeout)
        self.Fech = 60e6
        self.verbose = verbose
        self.last_reply = ''
        self.reader = dsp.FrameReader(self.ser)
        time.sleep(0.25)
        self.ser.reset_input_buffer()

    def command(self, text):
        self.ser.write((text + '\n').encode('ascii'))
        self.ser.flush()
        reply = self.ser.readline().decode('ascii', 'replace').strip()
        self.last_reply = reply
        if not reply.startswith('OK '):
            raise RuntimeError(reply or f'No response to {text}')
        return reply

    def status(self):
        return dsp.parse_status(self.command('status'))

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
        choices = {'raw': 'read_raw', 'envelope': 'read_fft', 'alaw': 'acq alaw'}
        if payload not in choices:
            raise ValueError(payload)
        self.command(choices[payload])
        frame = self.reader.read_frame()
        if frame.header.payload_name != payload:
            raise ValueError(f'Unexpected frame type {frame.header.payload_name}')
        return frame

    def read_raw(self):
        return self.capture('raw')

    def read_fft(self):
        return self.capture('envelope')

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
