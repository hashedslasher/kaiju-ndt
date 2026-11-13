import csv
from pathlib import Path
from threading import Event

import numpy as np
from PyQt5 import QtCore, QtWidgets


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

        self.nx = integer('X points', 60, 1, 1000)
        self.ny = integer('Y points', 40, 1, 1000)
        self.dx_steps = integer('X spacing (steps)', 40, 0, 5000)
        self.dy_steps = integer('Y spacing (steps)', 40, 0, 5000)
        self.hz = integer('Motor speed (Hz)', 1000, 1, 50000)
        self.sample_rate = integer('Sample rate (Hz)', 60000000, 1, 1000000000)
        rate_note = QtWidgets.QLabel('ADC is fixed at 60 MHz. This value converts gate times to samples.')
        rate_note.setWordWrap(True)
        form.addRow(rate_note)
        self.gate_start_us = decimal('Amplitude gate start (µs)', 75.0, 10000.0)
        self.gate_end_us = decimal('Amplitude gate end (µs)', 95.0, 10000.0)
        self.flaw_gate_start_us = decimal('Flaw gate start (µs)', 85.5, 10000.0)
        self.flaw_gate_end_us = decimal('Flaw gate end (µs)', 86.7, 10000.0)
        self.averages = integer('A-scans per point', 1, 1, 256)
        self.flaw_gate_start_us.setToolTip('Start after the front-wall echo, before the back-wall echo')
        self.flaw_gate_end_us.setToolTip('End before the back-wall echo')
        self.settle_ms = integer('Settle time (ms)', 10, 0, 60000)

        gain_row = QtWidgets.QWidget()
        gain_layout = QtWidgets.QHBoxLayout(gain_row)
        gain_layout.setContentsMargins(0, 0, 0, 0)
        self.gain_override = QtWidgets.QCheckBox('Override')
        self.gain = QtWidgets.QSpinBox()
        self.gain.setRange(0, 1023)
        self.gain.setValue(460)
        self.gain.setEnabled(False)
        self.gain_override.toggled.connect(self.gain.setEnabled)
        gain_layout.addWidget(self.gain_override)
        gain_layout.addWidget(self.gain)
        form.addRow('Gain (DAC)', gain_row)

        self.steps_mm_x = decimal('X steps/mm (0 = steps)', 0.0, 1000000.0)
        self.steps_mm_y = decimal('Y steps/mm (0 = steps)', 0.0, 1000000.0)
        self.output = QtWidgets.QLineEdit('results/cscan.png')
        self.csv_out = QtWidgets.QLineEdit('results/cscan.csv')
        form.addRow('PNG output', self.output)
        form.addRow('CSV output', self.csv_out)
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
            'nx': self.nx.value(),
            'ny': self.ny.value(),
            'dx_steps': self.dx_steps.value(),
            'dy_steps': self.dy_steps.value(),
            'hz': self.hz.value(),
            'sample_rate': self.sample_rate.value(),
            'gate_start_us': self.gate_start_us.value(),
            'gate_end_us': self.gate_end_us.value(),
            'flaw_gate_start_us': self.flaw_gate_start_us.value(),
            'flaw_gate_end_us': self.flaw_gate_end_us.value(),
            'averages': self.averages.value(),
            'settle_ms': self.settle_ms.value(),
            'gain': self.gain.value() if self.gain_override.isChecked() else None,
            'steps_mm_x': self.steps_mm_x.value() or None,
            'steps_mm_y': self.steps_mm_y.value() or None,
            'output': self.output.text().strip(),
            'csv_out': self.csv_out.text().strip(),
        }
        if settings['nx'] * settings['ny'] > 100000:
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'Maximum 100,000 scan points')
            return
        if (settings['nx'] > 1 and settings['dx_steps'] == 0 or
                settings['ny'] > 1 and settings['dy_steps'] == 0):
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'Spacing must be positive for multi-point axes')
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
        if not (0 <= start < end <= 8000 and 0 <= flaw_start < flaw_end <= 8000):
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'Both gates must fit in 8000 captured samples')
            return
        if not settings['output'] or not settings['csv_out']:
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'Specify both output filenames')
            return
        if Path(settings['output']).resolve() == Path(settings['csv_out']).resolve():
            QtWidgets.QMessageBox.warning(self, 'Scan setup', 'PNG and CSV paths must be different')
            return
        self.start_requested.emit(settings)

    def set_running(self, running):
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)


class ScanWorker(QtCore.QThread):
    point_received = QtCore.pyqtSignal(object)
    scan_finished = QtCore.pyqtSignal(bool, str)

    def __init__(self, probe, settings, parent=None):
        super().__init__(parent)
        self.probe = probe
        self.settings = settings
        self.stop_event = Event()

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
        try:
            if self.stop_event.is_set():
                raise RuntimeError('Scan cancelled')
            gate_start = int(round(config['gate_start_us'] * config['sample_rate'] / 1e6))
            gate_end = int(round(config['gate_end_us'] * config['sample_rate'] / 1e6))
            flaw_start = int(round(config['flaw_gate_start_us'] * config['sample_rate'] / 1e6))
            flaw_end = int(round(config['flaw_gate_end_us'] * config['sample_rate'] / 1e6))
            if config['gain'] is not None:
                self.probe.set_gain(config['gain'])
            self.probe.arm_pulser()
            Path(config['csv_out']).parent.mkdir(parents=True, exist_ok=True)
            with open(config['csv_out'], 'w', newline='') as file:
                names = ('row', 'col', 'x_steps', 'y_steps', 'amplitude_pp', 'flaw_pp', 'averages')
                writer = csv.DictWriter(file, fieldnames=names)
                writer.writeheader()
                points = self.probe.scan(
                    config['nx'], config['ny'], config['dx_steps'],
                    config['dy_steps'], config['hz'], gate_start,
                    gate_end, config['settle_ms'], waveforms=True,
                    flaw_gate_start=flaw_start, flaw_gate_end=flaw_end,
                    averages=config['averages'],
                )
                for point in points:
                    if self.stop_event.is_set():
                        raise RuntimeError('Scan stopped')
                    writer.writerow({name: point[name] for name in names})
                    file.flush()
                    data.append({name: point[name] for name in names})
                    self.point_received.emit(point)
                points = None
            if self.stop_event.is_set():
                raise RuntimeError('Scan stopped')
            from tests.scan import save_image
            save_image(data, config['output'], config['steps_mm_x'], config['steps_mm_y'])
            completed = True
            message = f'{len(data)} points | {config["csv_out"]} | {config["output"]}'
        except Exception as exc:
            message = f'{exc} | Partial CSV: {config["csv_out"]}'
        finally:
            if points is not None:
                points.close()
            if completed or self.stop_event.is_set():
                try:
                    self.probe.arm_pulser()
                except (OSError, RuntimeError, TimeoutError) as exc:
                    message += f' | Pulser rearm failed: {exc}'
            self.scan_finished.emit(completed, message)
