import csv
import shutil
from pathlib import Path
from threading import Event

import numpy as np
from PyQt5 import QtCore, QtWidgets

from .bscan import sample_window


SCAN_SAMPLE_RATE = 60000000
SCAN_SAMPLE_COUNT = 8000


class ScanSetupPanel(QtWidgets.QWidget):
    start_requested = QtCore.pyqtSignal(dict)
    stop_requested = QtCore.pyqtSignal()

    def __init__(self, port, parent=None):
        super().__init__(parent)
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        def integer(label, value, minimum, maximum):
            field = QtWidgets.QSpinBox()
            field.setRange(minimum, maximum)
            field.setValue(value)
            form.addRow(label, field)
            return field

        def decimal(label, value, maximum):
            field = QtWidgets.QDoubleSpinBox()
            field.setRange(0.0, maximum)
            field.setDecimals(3)
            field.setSingleStep(0.5)
            field.setValue(value)
            form.addRow(label, field)
            return field

        self.width_mm = decimal('Coupon X width (mm)', 14.0, 1000.0)
        self.height_mm = decimal('Coupon Y height (mm)', 6.0, 1000.0)
        self.margin_mm = decimal('Margin per side (mm)', 1.0, 500.0)
        self.dx_mm = decimal('X spacing (mm)', 0.8, 100.0)
        self.dx_mm.setSingleStep(0.02)
        self.dy_mm = decimal('Y spacing (mm)', 0.8, 100.0)
        self.dy_mm.setSingleStep(0.02)
        self.speed_mm_s = decimal('Motor speed (mm/s)', 20.0, 1000.0)
        self.gate_start_us = decimal('Amplitude gate start (µs)', 75.0, 10000.0)
        self.gate_end_us = decimal('Amplitude gate end (µs)', 95.0, 10000.0)
        self.flaw_gate_start_us = decimal('Flaw gate start (µs)', 85.5, 10000.0)
        self.flaw_gate_end_us = decimal('Flaw gate end (µs)', 86.7, 10000.0)
        self.tof_gate_start_us = decimal('TOF gate start (µs)', 75.0, 8000 / 60)
        self.tof_gate_end_us = decimal('TOF gate end (µs)', 95.0, 8000 / 60)
        self.tof_threshold = integer('TOF minimum echo (ADC p-p)', 20, 1, 1023)
        self.bscan_gate_start_us = decimal('B-scan gate start (µs)', 60.0, SCAN_SAMPLE_COUNT * 1e6 / SCAN_SAMPLE_RATE)
        self.bscan_gate_end_us = decimal('B-scan gate end (µs)', 110.0, SCAN_SAMPLE_COUNT * 1e6 / SCAN_SAMPLE_RATE)
        self.averages = integer('A-scans per point', 1, 1, 256)
        self.settle_ms = integer('Settle time (ms)', 10, 0, 60000)

        self.gain = integer('Gain (DAC)', 460, 0, 1023)

        self.output = QtWidgets.QLineEdit('results/cscan.png')
        self.csv_out = QtWidgets.QLineEdit('results/cscan.csv')
        form.addRow('PNG output', self.output)
        form.addRow('CSV output', self.csv_out)
        self.waveforms_out = QtWidgets.QLineEdit()
        form.addRow('Waveform data (.npy)', self.waveforms_out)
        port_label = QtWidgets.QLabel(port)
        port_label.setWordWrap(True)
        form.addRow('Connected port', port_label)

        self.start_button = QtWidgets.QPushButton('Scan')
        self.stop_button = QtWidgets.QPushButton('Stop scan')
        self.stop_button.setEnabled(False)
        self.progress = QtWidgets.QLabel('Ready')
        self.progress.setWordWrap(True)
        form.addRow(self.start_button)
        form.addRow(self.stop_button)
        form.addRow(self.progress)
        self.start_button.clicked.connect(self.submit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.setLayout(form)

    def submit(self):
        settings = {
            'width_mm': self.width_mm.value(),
            'height_mm': self.height_mm.value(),
            'margin_mm': self.margin_mm.value(),
            'dx_mm': self.dx_mm.value(),
            'dy_mm': self.dy_mm.value(),
            'speed_mm_s': self.speed_mm_s.value(),
            'sample_rate': SCAN_SAMPLE_RATE,
            'gate_start_us': self.gate_start_us.value(),
            'gate_end_us': self.gate_end_us.value(),
            'flaw_gate_start_us': self.flaw_gate_start_us.value(),
            'flaw_gate_end_us': self.flaw_gate_end_us.value(),
            'tof_gate_start_us': self.tof_gate_start_us.value(),
            'tof_gate_end_us': self.tof_gate_end_us.value(),
            'tof_threshold': self.tof_threshold.value(),
            'bscan_gate_start_us': self.bscan_gate_start_us.value(),
            'bscan_gate_end_us': self.bscan_gate_end_us.value(),
            'averages': self.averages.value(),
            'settle_ms': self.settle_ms.value(),
            'gain': self.gain.value(),
            'output': self.output.text().strip(),
            'csv_out': self.csv_out.text().strip(),
            'waveforms_out': self.waveforms_out.text().strip(),
        }
        if min(settings['width_mm'], settings['height_mm'], settings['dx_mm'], settings['dy_mm']) <= 0:
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'Coupon dimensions and spacing must be positive')
            return
        if not 0 <= settings['gate_start_us'] < settings['gate_end_us']:
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'Amplitude gate end must exceed start')
            return
        if not 0 <= settings['flaw_gate_start_us'] < settings['flaw_gate_end_us']:
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'Flaw gate end must exceed start')
            return
        start = round(settings['gate_start_us'] * settings['sample_rate'] / 1e6)
        end = round(settings['gate_end_us'] * settings['sample_rate'] / 1e6)
        flaw_start = round(settings['flaw_gate_start_us'] * settings['sample_rate'] / 1e6)
        flaw_end = round(settings['flaw_gate_end_us'] * settings['sample_rate'] / 1e6)
        tof_start = round(settings['tof_gate_start_us'] * settings['sample_rate'] / 1e6)
        tof_end = round(settings['tof_gate_end_us'] * settings['sample_rate'] / 1e6)
        if not (0 <= start < end <= 8000 and 0 <= flaw_start < flaw_end <= 8000 and 0 <= tof_start < tof_end <= 8000):
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'All three gates must fit in 8000 captured samples')
            return
        try:
            sample_window(settings['bscan_gate_start_us'], settings['bscan_gate_end_us'], SCAN_SAMPLE_RATE, SCAN_SAMPLE_COUNT)
        except ValueError:
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'B-scan gate must have increasing times within the captured waveform')
            return
        if settings['speed_mm_s'] <= 0:
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'Motor speed must be positive')
            return
        if not settings['output'] or not settings['csv_out']:
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'Specify both output filenames')
            return
        if not settings['waveforms_out']:
            settings['waveforms_out'] = str(Path(settings['csv_out']).with_suffix('.bscan.npy'))
        if Path(settings['waveforms_out']).suffix.lower() != '.npy' or len({Path(settings[k]).resolve() for k in ('output', 'csv_out', 'waveforms_out')}) != 3:
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'Use three distinct output paths; waveform data must end in .npy')
            return
        self.start_requested.emit(settings)

    def set_running(self, running):
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)


class ScanWorker(QtCore.QThread):
    point_received = QtCore.pyqtSignal(object)
    scan_progress = QtCore.pyqtSignal(str)
    scan_finished = QtCore.pyqtSignal(bool, str)

    def __init__(self, probe, settings, parent=None):
        super().__init__(parent)
        self.probe = probe
        self.settings = settings
        self.stop_event = Event()
        self.waveforms_path = None
        self.applied_gain = None

    def request_stop(self):
        self.stop_event.set()
        try:
            self.probe.ser.write(b'scan stop\n')
            self.probe.ser.flush()
        except OSError:
            pass

    def run(self):
        config = self.settings
        points = None
        completed = False
        message = ''
        data = []
        waveforms = None
        try:
            if self.stop_event.is_set():
                raise RuntimeError('Scan cancelled')
            gate_start = int(round(config['gate_start_us'] * config['sample_rate'] / 1e6))
            gate_end = int(round(config['gate_end_us'] * config['sample_rate'] / 1e6))
            flaw_start = int(round(config['flaw_gate_start_us'] * config['sample_rate'] / 1e6))
            flaw_end = int(round(config['flaw_gate_end_us'] * config['sample_rate'] / 1e6))
            tof_start = round(config['tof_gate_start_us'] * config['sample_rate'] / 1e6)
            tof_end = round(config['tof_gate_end_us'] * config['sample_rate'] / 1e6)
            waveform_path = Path(config['waveforms_out'])
            waveform_path.parent.mkdir(parents=True, exist_ok=True)
            needed = config['nx'] * config['ny'] * 8000 * 2
            if shutil.disk_usage(waveform_path.parent).free < needed + 1024 * 1024:
                raise OSError(f'Insufficient space for waveform data ({needed / 1e6:.1f} MB)')
            self.probe.set_gain(config['gain'])
            self.applied_gain = config['gain']
            self.probe.arm_pulser()
            Path(config['csv_out']).parent.mkdir(parents=True, exist_ok=True)
            waveforms = np.lib.format.open_memmap(waveform_path, mode='w+', dtype='<u2',
                                                  shape=(config['ny'], config['nx'], 8000))
            self.waveforms_path = str(waveform_path)
            seen = set()
            with open(config['csv_out'], 'w', newline='') as file:
                names = ('row', 'col', 'x_mm', 'y_mm', 'dx_mm', 'dy_mm', 'amplitude_pp', 'flaw_pp', 'tof_us', 'averages')
                writer = csv.DictWriter(file, fieldnames=names)
                writer.writeheader()
                points = self.probe.scan(
                    config['nx'], config['ny'], config['dx_mm'],
                    config['dy_mm'], config['speed_mm_s'], gate_start,
                    gate_end, config['settle_ms'], waveforms=True,
                    flaw_gate_start=flaw_start, flaw_gate_end=flaw_end,
                    averages=config['averages'], tof_gate_start=tof_start, tof_gate_end=tof_end,
                    tof_threshold=config['tof_threshold'], centered=True, progress=self.scan_progress.emit,
                )
                if self.stop_event.is_set():
                    raise RuntimeError('Scan stopped before positioning')
                for point in points:
                    row, col = point['row'], point['col']
                    if not (0 <= row < config['ny'] and 0 <= col < config['nx']) or (row, col) in seen:
                        raise ValueError(f'Invalid or duplicate scan point {row}, {col}')
                    seen.add((row, col))
                    waveforms[row, col] = point['waveform']
                    if len(seen) % config['nx'] == 0:
                        waveforms.flush()
                    writer.writerow({name: point[name] for name in names})
                    file.flush()
                    data.append({name: point[name] for name in names})
                    self.point_received.emit(point)
                points = None
            if self.stop_event.is_set():
                raise RuntimeError('Scan stopped')
            from tests.scan import save_image
            save_image(data, config['output'], (config['tof_gate_start_us'], config['tof_gate_end_us']))
            completed = True
            message = f'{len(data)} points | {config["csv_out"]} | {config["output"]} | {waveform_path}'
        except Exception as exc:
            message = f'{exc} | Partial CSV: {config["csv_out"]}'
        finally:
            if points is not None:
                points.close()
            if waveforms is not None:
                try:
                    waveforms.flush()
                except OSError as exc:
                    completed = False
                    message += f' | Waveform flush failed: {exc}'
                del waveforms
            if completed or self.stop_event.is_set():
                try:
                    self.probe.arm_pulser()
                except (OSError, RuntimeError, TimeoutError) as exc:
                    message += f' | Pulser rearm failed: {exc}'
            self.scan_finished.emit(completed, message)
