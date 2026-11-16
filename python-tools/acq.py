import sys
import math
if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] in ('--i2c-test', '--temp-test', '--temp-stats'):
    from lib.device import Pic0rick
    if len(sys.argv) != 2:
        sys.exit('Usage: python acq.py --i2c-test | --temp-test | --temp-stats')
    probe = None
    try:
        probe = Pic0rick(timeout=3.0)
        command = {'--i2c-test': 'i2c test', '--temp-test': 'temp test', '--temp-stats': 'temp stats'}[sys.argv[1]]
        print(f'[Diagnostic] {probe.command(command)}')
    except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
        sys.exit(f'[Diagnostic] {exc}')
    finally:
        if probe is not None:
            probe.close()
    sys.exit(0)
if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1].startswith('--'):
    from tests import dispatch
    sys.exit(dispatch.run(sys.argv[1:]))
import numpy as np
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QAction
import pyqtgraph as pg
from lib.device import Pic0rick
from lib.protocol import alaw_decode
from lib.gamepad import GamepadFilter, POLL_MS, jog_command as gamepad_jog_command
from lib.scan_ui import ScanSetupPanel, ScanWorker
from lib.scan_geometry import centered_plan
from lib.bscan import sample_window, rectify_waveforms, bscan_line
from lib.plot_ranges import waveform_y_range
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt


try:
    import pygame
    from pygame._sdl2 import controller as sdl_controller
except ImportError:
    pygame = None
    sdl_controller = None


TANK_BOTTOM_AT_Z_ZERO_MM = 7.875 * 25.4


class OverlayLineEdit(QtWidgets.QLineEdit):
    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.clear()
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)


class AScanApp(QtWidgets.QMainWindow):
    def __init__(self, initial_mode="fft"):
        super().__init__()

        self.setWindowTitle("A-scan")
        self.resize(900, 450)

        menubar = self.menuBar()
        self.file_menu = menubar.addMenu('&File')

        self.exit_action = QAction('Exit', self)
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)

        self.save_image = QAction('Save Image', self)
        self.file_menu.addAction(self.save_image)

        self.probe = Pic0rick()
        self.fs = 60e6
        self.gain = 460
        self.pon, self.poff, self.damp = 75, 75, 6000

        self.probe.set_gain(self.gain)
        self.probe.configure_pulse(self.pon, self.damp, self.poff)
        self.probe.arm_pulser()

        self.start_us, self.end_us = 0, 24

        self.plot_widget = pg.PlotWidget()
        self.graph_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.graph_splitter.addWidget(self.plot_widget)
        self.bscan_panel = QtWidgets.QWidget()
        b_layout = QtWidgets.QVBoxLayout(self.bscan_panel)
        b_layout.setContentsMargins(0, 0, 0, 0)
        b_controls = QtWidgets.QHBoxLayout()
        b_controls.addWidget(QtWidgets.QLabel('B-scan row'))
        self.bscan_row_select = QtWidgets.QSpinBox()
        self.bscan_row_select.setRange(1, 1)
        self.bscan_row_select.setEnabled(False)
        self.bscan_row_select.valueChanged.connect(self.select_bscan_row)
        b_controls.addWidget(self.bscan_row_select)
        b_controls.addStretch()
        b_layout.addLayout(b_controls)
        self.bscan_graph = pg.GraphicsLayoutWidget()
        self.bscan_plot = self.bscan_graph.addPlot(row=0, col=0, title='B-scan')
        self.bscan_plot.setLabel('bottom', 'X', units='mm')
        self.bscan_plot.setLabel('left', 'Time', units='µs')
        self.bscan_plot.getAxis('bottom').enableAutoSIPrefix(False)
        self.bscan_plot.getAxis('left').enableAutoSIPrefix(False)
        self.bscan_plot.getViewBox().invertY(True)
        self.bscan_plot.getViewBox().setLimits(xMin=0)
        self.bscan_image = pg.ImageItem(axisOrder='row-major')
        self.bscan_plot.addItem(self.bscan_image)
        self.bscan_histogram = pg.HistogramLUTItem(image=self.bscan_image)
        self.bscan_histogram.gradient.loadPreset('viridis')
        self.bscan_graph.addItem(self.bscan_histogram, row=0, col=1)
        b_layout.addWidget(self.bscan_graph)
        self.graph_splitter.addWidget(self.bscan_panel)
        self.bscan_panel.hide()
        self.bscan_volume = None
        self.bscan_data = None
        self.bscan_current_row = None
        self.cscan_graph = pg.GraphicsLayoutWidget()
        self.cscan_plot = self.cscan_graph.addPlot(row=0, col=0, title='Amplitude scan')
        self.cscan_plot.setLabel('bottom', 'X', units='mm')
        self.cscan_plot.setLabel('left', 'Y', units='mm')
        self.cscan_plot.setAspectLocked(True)
        self.cscan_image = pg.ImageItem(axisOrder='row-major')
        self.cscan_plot.addItem(self.cscan_image)
        self.cscan_histogram = pg.HistogramLUTItem(image=self.cscan_image)
        self.cscan_histogram.gradient.loadPreset('viridis')
        self.cscan_graph.addItem(self.cscan_histogram, row=0, col=1)
        self.cscan_histogram.setLevels(0, 1023)
        self.flaw_plot = self.cscan_graph.addPlot(row=0, col=2, title='Flaw scan')
        self.flaw_plot.setLabel('bottom', 'X', units='mm')
        self.flaw_plot.setLabel('left', 'Y', units='mm')
        self.flaw_plot.setAspectLocked(True)
        self.flaw_image = pg.ImageItem(axisOrder='row-major')
        self.flaw_plot.addItem(self.flaw_image)
        self.flaw_histogram = pg.HistogramLUTItem(image=self.flaw_image)
        self.flaw_histogram.gradient.loadPreset('viridis')
        self.cscan_graph.addItem(self.flaw_histogram, row=0, col=3)
        self.flaw_histogram.setLevels(0, 1023)
        self.tof_plot = self.cscan_graph.addPlot(row=0, col=4, title='TOF scan (µs)')
        self.tof_plot.setLabel('bottom', 'X', units='mm')
        self.tof_plot.setLabel('left', 'Y', units='mm')
        self.tof_plot.setAspectLocked(True)
        self.tof_image = pg.ImageItem(axisOrder='row-major')
        self.tof_plot.addItem(self.tof_image)
        self.tof_histogram = pg.HistogramLUTItem(image=self.tof_image)
        self.tof_histogram.gradient.loadPreset('viridis')
        self.cscan_graph.addItem(self.tof_histogram, row=0, col=5)
        for plot in (self.cscan_plot, self.flaw_plot, self.tof_plot):
            plot.getAxis('bottom').enableAutoSIPrefix(False)
            plot.getAxis('left').enableAutoSIPrefix(False)
            plot.getViewBox().setLimits(xMin=0, yMin=0)
        self.graph_splitter.addWidget(self.cscan_graph)
        self.cscan_graph.hide()
        self.setCentralWidget(self.graph_splitter)
        self.scan_grid = None
        self.flaw_grid = None
        self.tof_grid = None
        self.scan_settings = None
        self.scan_worker = None
        self.scan_busy = False
        self.goto_busy = False
        self.goto_timer = QtCore.QTimer(self)
        self.goto_timer.timeout.connect(self.poll_goto)
        self.scan_previous_mode = None
        self.scan_previous_window = None

        self.scan_panel = ScanSetupPanel(self.probe.port)
        self.scan_panel.gain.setValue(self.gain)
        self.scan_dock = QtWidgets.QDockWidget('Scan setup', self)
        self.scan_dock.setObjectName('scanSetupDock')
        scan_scroll = QtWidgets.QScrollArea()
        scan_scroll.setWidgetResizable(True)
        scan_scroll.setWidget(self.scan_panel)
        self.scan_dock.setWidget(scan_scroll)
        self.scan_dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.scan_dock)
        self.scan_dock.hide()
        self.toolbar = self.addToolBar('Scan')
        self.toolbar.setMovable(False)
        self.scan_setup_action = self.scan_dock.toggleViewAction()
        self.scan_setup_action.setText('Scan setup')
        self.toolbar.addAction(self.scan_setup_action)
        self.temperature_box = QtWidgets.QLineEdit(self)
        self.temperature_box.setReadOnly(True)
        self.temperature_box.setAlignment(QtCore.Qt.AlignCenter)
        self.temperature_box.setFixedWidth(80)
        self.temperature_box.setFocusPolicy(QtCore.Qt.NoFocus)
        self.toolbar.addWidget(self.temperature_box)
        self.temperature_timer = QtCore.QTimer(self)
        self.temperature_timer.timeout.connect(self.refresh_temperature)
        self.temperature_timer.start(1100)
        self.scan_panel.start_requested.connect(self.start_scan)
        self.scan_panel.stop_requested.connect(self.stop_scan)

        self.plot_widget.setXRange(self.start_us, self.end_us, padding=0)
        self.plot_widget.enableAutoRange(axis='y', enable=False)
        self.plot_widget.enableAutoRange(axis='x', enable=False)
        self.plot_widget.getAxis('bottom').enableAutoSIPrefix(False)
        self.plot_widget.getAxis('left').enableAutoSIPrefix(False)
        self.plot_widget.getViewBox().setMouseEnabled(x=True, y=False)
        self.y_range_initialized = False
        self.manual_y_range = None
        self.auto_y_range = None
        self.mode_y_ranges = {}
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('bottom', 'Time', units='µs')
        self.plot_widget.setLabel('left', 'Envelope', units='ADC counts')

        self.curve = self.plot_widget.plot(
            pen=pg.mkPen(color='white', width=2)
        )
        self.mode = None
        self.set_capture_mode(initial_mode)

        self.clearance_label = QtWidgets.QLabel('Bottom clearance: set Z=0', self.plot_widget)
        self.clearance_label.setStyleSheet('''
            QLabel {
                background-color: rgba(0, 0, 0, 185);
                color: white;
                padding: 6px 10px;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
            }
        ''')
        self.clearance_label.adjustSize()
        self.position_clearance_label()
        self.plot_widget.installEventFilter(self)

        self.position_timer = QtCore.QTimer(self)
        self.position_timer.timeout.connect(self.refresh_clearance)
        self.position_timer.start(350)
        self.refresh_clearance()

        self.cmd_input = OverlayLineEdit(self)
        self.cmd_input.setPlaceholderText(
            "raw | fft | a-law | home | goto 0,0 | zero z | pos | yrange | geometry"
        )

        self.cmd_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(0, 0, 0, 180);
                color: #FFFFFF;
                border: 1px solid #FFFFFF;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 14px;
                font-family: monospace;
            }
        """)

        self.cmd_input.hide()
        self.cmd_input.returnPressed.connect(self.handle_command)

        self.movement_keys = {
            QtCore.Qt.Key_W,
            QtCore.Qt.Key_A,
            QtCore.Qt.Key_S,
            QtCore.Qt.Key_D,
            QtCore.Qt.Key_J,
            QtCore.Qt.Key_K,
        }
        self.keys_down = set()
        self.key_press_order = {}
        self.next_key_press = 0
        self.last_movement_commands = {
            "x": "stop_x",
            "y": "stop_y",
            "z": "stop_z",
        }

        self.controller_axes = {"x": 0, "y": 0, "z": 0}
        self.controller_filter = GamepadFilter()
        self.controller_armed = False
        self.controller = None
        self.controller_enabled = False
        self.init_controller()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(1)

    def init_controller(self):

        if pygame is None:
            return

        try:
            pygame.display.init()
            sdl_controller.init()
        except pygame.error as exc:
            print(f"[Controller] Input unavailable: {exc}")
            return

        self.controller_enabled = True
        self.controller_timer = QtCore.QTimer(self)
        self.controller_timer.timeout.connect(self.poll_controller)
        self.controller_timer.start(POLL_MS)
        self.poll_controller()

    def release_controller(self):

        self.controller_armed = False
        self.controller_filter.reset()
        if self.controller is not None:
            self.controller.quit()
            self.controller = None
        self.set_controller_axes(0, 0, 0)

    def set_controller_axes(self, x, y, z):
        directions = {"x": x, "y": y, "z": z}
        if directions != self.controller_axes:
            self.controller_axes = directions
            self.send_movement()

    def poll_controller(self):

        if not self.controller_enabled:
            return

        if self.scan_busy or self.goto_busy:
            self.controller_armed = False
            self.controller_filter.reset()
            return

        try:
            pygame.event.pump()
            pygame.event.clear()

            if self.controller is not None and not self.controller.attached():
                print("[Controller] Disconnected")
                self.release_controller()
                return

            if self.controller is None:
                for index in range(sdl_controller.get_count()):
                    if sdl_controller.is_controller(index):
                        self.controller = sdl_controller.Controller(index)
                        self.controller_armed = False
                        self.controller_filter.reset()
                        print(f"[Controller] Connected: {sdl_controller.name_forindex(index)}")
                        break

            if self.controller is None:
                return

            raw_x = self.controller.get_axis(pygame.CONTROLLER_AXIS_LEFTX)
            raw_y = self.controller.get_axis(pygame.CONTROLLER_AXIS_LEFTY)
            raw_z = self.controller.get_axis(pygame.CONTROLLER_AXIS_RIGHTY)

            if self.cmd_input.isVisible() or not self.isActiveWindow() or self.keys_down:
                self.controller_armed = False
                self.controller_filter.reset()
                self.set_controller_axes(0, 0, 0)
                return

            if not self.controller_armed:
                if self.controller_filter.neutral(raw_x, raw_y, raw_z):
                    self.controller_armed = True
                self.set_controller_axes(0, 0, 0)
                return

            self.set_controller_axes(*self.controller_filter.update(raw_x, raw_y, raw_z))
        except (pygame.error, OSError) as exc:
            print(f"[Controller] Read error: {exc}")
            self.release_controller()

    def keyPressEvent(self, event):
        key = event.key()

        if key == QtCore.Qt.Key_Colon or event.text() == ':':
            self.stop_manual_motion()
            self.center_command_prompt()
            self.cmd_input.show()
            self.cmd_input.setFocus()
            event.accept()
            return

        if key in self.movement_keys:
            if self.scan_busy or self.goto_busy:
                event.accept()
                return
            if event.isAutoRepeat():
                event.accept()
                return

            self.keys_down.add(key)
            self.next_key_press += 1
            self.key_press_order[key] = self.next_key_press
            self.send_movement()

            event.accept()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        key = event.key()

        if key in self.movement_keys:
            if not event.isAutoRepeat():
                was_down = key in self.keys_down
                self.keys_down.discard(key)
                self.key_press_order.pop(key, None)

                if was_down:
                    self.send_movement()

            event.accept()
            return

        super().keyReleaseEvent(event)

    def stop_manual_motion(self):

        self.keys_down.clear()
        self.key_press_order.clear()
        self.controller_armed = False
        self.controller_filter.reset()
        self.set_controller_axes(0, 0, 0)
        self.send_movement()

    def send_movement(self):
        if self.scan_busy or self.goto_busy:
            return

        def latest_down(*keys):
            down = [key for key in keys if key in self.keys_down]
            return max(down, key=lambda k: self.key_press_order.get(k, 0)) if down else None

        x = latest_down(QtCore.Qt.Key_A, QtCore.Qt.Key_D)
        y = latest_down(QtCore.Qt.Key_W, QtCore.Qt.Key_S)
        z = latest_down(QtCore.Qt.Key_J, QtCore.Qt.Key_K)


        desired = {
            "x": ("jog_mm_x plus 40" if x == QtCore.Qt.Key_A else
                  "jog_mm_x minus 40" if x == QtCore.Qt.Key_D else
                  gamepad_jog_command("x", self.controller_axes["x"])),
            "y": ("jog_mm_y minus 40" if y == QtCore.Qt.Key_W else
                  "jog_mm_y plus 40" if y == QtCore.Qt.Key_S else
                  gamepad_jog_command("y", self.controller_axes["y"])),
            "z": ("jog_mm_z up 10" if z == QtCore.Qt.Key_J else
                  "jog_mm_z down 10" if z == QtCore.Qt.Key_K else
                  gamepad_jog_command("z", self.controller_axes["z"])),
        }

        changed = []
        for axis, command in desired.items():
            if self.last_movement_commands[axis] != command:
                changed.append(command)
                self.last_movement_commands[axis] = command

        for command in changed:
            parts = command.split()
            try:
                if parts[0].startswith("stop_"):
                    self.probe.stop(parts[0][-1])
                else:
                    self.probe.jog(parts[0][-1], parts[1], float(parts[2]))
            except (RuntimeError, ValueError, TimeoutError) as error:
                print(error)

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == QtCore.QEvent.ActivationChange and
                not self.isActiveWindow() and hasattr(self, "keys_down")):
            if self.goto_busy:
                self.cancel_goto()
            self.stop_manual_motion()

    def closeEvent(self, event):
        if self.goto_busy:
            self.cancel_goto()
            if self.goto_busy:
                event.ignore()
                return
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.stop_scan()
            if not self.scan_worker.wait(5000):
                event.ignore()
                self.statusBar().showMessage('Waiting for scan to stop', 5000)
                return
        self.position_timer.stop()
        self.temperature_timer.stop()
        self.timer.stop()
        if self.controller_enabled:
            self.controller_timer.stop()
        self.stop_manual_motion()
        if self.controller_enabled:
            self.release_controller()
            sdl_controller.quit()
            pygame.display.quit()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.center_command_prompt()

    def eventFilter(self, watched, event):
        if watched is self.plot_widget and event.type() == QtCore.QEvent.Resize:
            self.position_clearance_label()
        return super().eventFilter(watched, event)

    def position_clearance_label(self):
        self.clearance_label.move(
            max(0, self.plot_widget.width() - self.clearance_label.width() - 14), 14
        )

    def refresh_temperature(self):
        if self.scan_busy or self.goto_busy:
            return
        try:
            degrees_c = self.probe.temperature()
            if degrees_c is not None:
                self.temperature_box.setText(f'{degrees_c * 9.0 / 5.0 + 32.0:.2f} F')
        except (RuntimeError, ValueError, TimeoutError, OSError):
            self.temperature_box.clear()

    def refresh_clearance(self, reply=None):
        if self.scan_busy or self.goto_busy:
            return
        try:
            if reply is None:
                reply = self.probe.position()
            fields = dict(part.split('=', 1) for part in reply.split() if '=' in part)
            if 'z' not in fields or 'homed' not in fields:
                raise ValueError(f'Unexpected position reply: {reply}')
            if fields['homed'].split('/')[-1] != '1':
                message = 'Bottom clearance: set Z=0'
            else:
                if fields.get('units') != 'mm':
                    raise ValueError('Flash matching metric firmware')
                clearance_mm = TANK_BOTTOM_AT_Z_ZERO_MM - float(fields['z'])
                approximate = fields.get('exact', '1/1/1').split('/')[-1] != '1'
                message = f'Bottom clearance: {"~" if approximate else ""}{clearance_mm:.1f} mm'
            self.clearance_label.setText(message)
        except (RuntimeError, ValueError, TimeoutError, OSError) as exc:
            self.clearance_label.setText('Bottom clearance: unavailable')
            print(f'[Gantry] Position update failed: {exc}')
        self.clearance_label.adjustSize()
        self.position_clearance_label()

    def center_command_prompt(self):
        w, h = 340, 38
        x = (self.width() - w) // 2
        y = (self.height() - h) // 2
        self.cmd_input.setGeometry(x, y, w, h)

    def check_pico_messages(self):
        while self.probe.ser.in_waiting > 0:
            try:
                line = self.probe.ser.readline().decode(errors='ignore').strip()
                if line:
                    int(line)
                    continue
            except ValueError:
                print(f"[PICO] {line}")

    def set_capture_mode(self, mode):
        """Select the mode executed by firmware for subsequent captures."""
        aliases = {'raw': 'raw', 'fft': 'fft', 'envelope': 'fft',
                   'a-law': 'a-law', 'alaw': 'a-law'}
        mode = aliases.get(mode.lower())
        if mode is None:
            raise ValueError('Mode must be raw, fft, or a-law')
        if self.mode is not None and not self.scan_busy:
            self.mode_y_ranges[self.mode] = self.manual_y_range
        self.mode = mode
        self.curve.clear()
        self.manual_y_range = None if self.scan_busy else self.mode_y_ranges.get(mode)
        self.reset_waveform_range()
        if mode == 'raw':
            label = 'Raw'
            self.plot_widget.setLabel('left', 'ADC value', units='counts')
        elif mode == 'fft':
            label = 'FFT / Hilbert envelope'
            self.plot_widget.setLabel('left', 'Envelope', units='ADC counts')
        else:
            label = 'A-law envelope'
            self.plot_widget.setLabel('left', 'Envelope', units='ADC counts')
        self.plot_widget.setTitle(label)
        self.statusBar().showMessage(f'Acquisition mode: {mode}')
        print(f'[Acquisition] {label}')

    def reset_waveform_range(self):
        self.auto_y_range = None
        self.y_range_initialized = False
        limits = self.manual_y_range or ((0.0, 1023.0) if self.mode == 'raw' else (0.0, 1.0))
        self.plot_widget.setYRange(*limits, padding=0)
        self.plot_widget.enableAutoRange(axis='y', enable=False)

    def plot_waveform(self, samples, sample_rate):
        if sample_rate <= 0:
            self.curve.clear()
            return False
        times = np.arange(len(samples), dtype=np.float64) * (1e6 / sample_rate)
        visible = (times >= self.start_us) & (times <= self.end_us)
        if not np.any(visible):
            self.curve.clear()
            return False
        values = np.asarray(samples)[visible]
        self.curve.setData(times[visible], values)
        if self.manual_y_range is None:
            limits = waveform_y_range(self.mode, values, self.auto_y_range)
            if limits != self.auto_y_range:
                self.plot_widget.setYRange(*limits, padding=0)
                self.auto_y_range = limits
            self.y_range_initialized = True
        return True

    def handle_command(self):
        text = self.cmd_input.text().strip()
        self.cmd_input.hide()
        self.cmd_input.clear()
        if not text:
            return

        parts = text.replace(',', ' ').split()
        cmd = parts[0].lower()
        if self.scan_busy:
            if cmd in ('stop', 'stop_all'):
                self.stop_scan()
            else:
                self.statusBar().showMessage('Scan active: use Stop scan', 5000)
            return
        if self.goto_busy:
            if cmd in ('stop', 'stop_all'):
                self.cancel_goto()
            else:
                self.statusBar().showMessage('Positioning active: use stop_all', 5000)
            return
        try:
            if cmd in ('raw', 'fft', 'a-law', 'alaw', 'envelope') and len(parts) == 1:
                self.set_capture_mode(cmd)

            elif cmd == 'gain' and len(parts) == 2:
                gain = int(parts[1])
                self.probe.set_gain(gain)
                self.gain = gain
                self.scan_panel.gain.setValue(gain)
                if self.manual_y_range is None:
                    self.reset_waveform_range()

            elif cmd in ('pon', 'poff', 'pon/poff') and len(parts) == 2:
                val = int(parts[1])
                self.pon = val
                self.poff = val
                self.probe.configure_pulse(self.pon, self.damp, self.poff)

            elif cmd == 'damp' and len(parts) == 2:
                self.damp = int(parts[1])
                self.probe.configure_pulse(self.pon, self.damp, self.poff)

            elif cmd == 'window' and len(parts) == 3:
                start, end = float(parts[1]), float(parts[2])
                if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                    raise ValueError('Window must satisfy 0 <= start < end (µs)')
                self.start_us, self.end_us = start, end
                self.plot_widget.setXRange(start, end, padding=0)
                if self.manual_y_range is None:
                    self.reset_waveform_range()

            elif cmd == 'yrange' and len(parts) == 3:
                low, high = float(parts[1]), float(parts[2])
                if not math.isfinite(low) or not math.isfinite(high) or high <= low:
                    raise ValueError('yrange requires finite MIN and MAX, with MIN < MAX')
                self.manual_y_range = (low, high)
                self.mode_y_ranges[self.mode] = self.manual_y_range
                self.y_range_initialized = True
                self.plot_widget.setYRange(low, high, padding=0)

            elif cmd == 'yrange' and len(parts) == 2 and parts[1].lower() == 'auto':
                self.manual_y_range = None
                self.mode_y_ranges[self.mode] = None
                self.reset_waveform_range()

            elif cmd == 'geometry' and len(parts) == 1:
                reply = self.probe.geometry()
                print(f'[Gantry] {reply}')
                self.statusBar().showMessage(reply, 5000)

            elif cmd in ('jog_x', 'jog_y', 'jog_z') and len(parts) == 3:
                print(self.probe.jog(cmd[-1], parts[1], float(parts[2])))

            elif cmd in ('move_x', 'move_y', 'move_z') and len(parts) == 4:
                print(self.probe.move(cmd[-1], parts[1], float(parts[2]), float(parts[3])))

            elif cmd == 'pulse_rate' and len(parts) == 2:
                rate = float(parts[1])
                if not 0 < rate <= 20:
                    raise ValueError('pulse_rate must be >0 and <=20 Hz')
                self.timer.setInterval(round(1000.0 / rate))
                print(f'[Acquisition] Display refresh {rate:g} Hz')

            elif cmd == 'goto' and len(parts) == 3 and parts[1:] == ['0', '0']:
                self.goto_scan_origin()

            elif cmd == 'home' and len(parts) == 1:
                reply = self.probe.home()
                print(f'[Gantry] {reply}')
                self.statusBar().showMessage('X/Y homing started', 5000)

            elif cmd == 'pos' and len(parts) == 1:
                reply = self.probe.position()
                self.refresh_clearance(reply)
                print(f'[Gantry] {reply}')
                self.statusBar().showMessage(reply, 5000)

            elif (cmd in ('z=0', 'zero_z') and len(parts) == 1) or (cmd in ('zero', 'pos_zero') and len(parts) == 2 and parts[1].lower() == 'z'):
                reply = self.probe.zero('z')
                self.refresh_clearance()
                print(f'[Gantry] {reply}')
                self.statusBar().showMessage('Z position set to 0', 5000)

            elif cmd in ('stop', 'stop_all') and len(parts) == 1:
                reply = self.probe.stop('all')
                print(f'[Gantry] {reply}')
                self.statusBar().showMessage('Motors stopped', 5000)

            elif (cmd == 'i2c' and parts[1:] == ['test']) or (cmd == 'tmc' and len(parts) >= 2) or (cmd == 'temp' and parts[1:] in (['test'], ['stats'])):
                reply = self.probe.command(' '.join(parts))
                print(f'[Diagnostic] {reply}')
                self.statusBar().showMessage(reply, 5000)

            elif cmd == 'help' and len(parts) == 1:
                print('Commands: raw | fft | a-law | gain N | pon N | poff N '
                      '| damp N | window START_US END_US | pulse_rate HZ '
                      '| home | goto 0,0 | pos | zero z | z=0 | stop_all '
                      '| yrange MIN MAX | yrange auto | geometry | jog_x/y/z DIR MM_S | move_x/y/z DIR MM_S MM | i2c test | tmc status | tmc setup | temp test | temp stats')
            else:
                raise ValueError(f'Unknown or incomplete command: {text}')
        except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
            print(f'[Command] {exc}')
            self.statusBar().showMessage(str(exc), 5000)

    def goto_scan_origin(self):
        self.stop_manual_motion()
        panel = self.scan_panel
        plan = centered_plan(self.probe.geometry(), panel.width_mm.value(), panel.height_mm.value(),
                             panel.margin_mm.value(), panel.dx_mm.value(), panel.dy_mm.value())
        speed = panel.speed_mm_s.value()
        if speed <= 0:
            raise ValueError('Scan motor speed must be positive')
        x, y = plan['home_start_x_mm'], plan['home_start_y_mm']
        try:
            reply = self.probe.command(f'goto_xy {x:.3f} {y:.3f} {speed:g}')
        except (TimeoutError, OSError):
            try:
                self.probe.stop('all')
            except (RuntimeError, ValueError, TimeoutError, OSError):
                pass
            raise
        self.goto_busy = True
        self.scan_panel.start_button.setEnabled(False)
        self.goto_timer.start(100)
        print(f'[Gantry] {reply}')
        self.statusBar().showMessage('Moving to scan origin (0,0)')

    def finish_goto(self, message):
        self.goto_timer.stop()
        self.goto_busy = False
        self.scan_panel.start_button.setEnabled(True)
        self.controller_armed = False
        print(f'[Gantry] {message}')
        self.statusBar().showMessage(message, 5000)

    def cancel_goto(self):
        try:
            self.probe.stop('all')
        except (RuntimeError, ValueError, TimeoutError, OSError) as exc:
            print(f'[Gantry] Stop not confirmed: {exc}')
            self.statusBar().showMessage(f'Stop not confirmed: {exc}', 5000)
            return
        self.finish_goto('Positioning stopped')

    def poll_goto(self):
        try:
            reply = self.probe.command('goto_status')
            fields = dict(part.split('=', 1) for part in reply.split() if '=' in part)
            state = fields.get('goto')
            if state == 'moving':
                return
            if state == 'done':
                self.finish_goto('At scan origin (0,0)')
            elif state == 'failed':
                self.finish_goto(f'Positioning failed: {fields.get("error", "unknown")}')
            else:
                raise ValueError(f'Unexpected positioning reply: {reply}')
        except (RuntimeError, ValueError, TimeoutError, OSError) as exc:
            print(f'[Gantry] Positioning status failed: {exc}')
            self.cancel_goto()

    def start_scan(self, settings):
        if self.goto_busy:
            self.statusBar().showMessage('Positioning active: use stop_all', 5000)
            return
        if self.scan_busy or (self.scan_worker is not None and self.scan_worker.isRunning()):
            return
        self.stop_manual_motion()
        try:
            plan = centered_plan(self.probe.geometry(), settings['width_mm'], settings['height_mm'],
                                 settings['margin_mm'], settings['dx_mm'], settings['dy_mm'])
            settings = {**settings, **plan}
            bscan_start, bscan_end = sample_window(settings['bscan_gate_start_us'], settings['bscan_gate_end_us'], settings['sample_rate'])
        except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
            QtWidgets.QMessageBox.warning(self, 'Scan setup', str(exc))
            return
        self.bscan_volume = None
        self.scan_busy = True
        self.scan_settings = settings
        self.scan_previous_mode = self.mode
        self.mode_y_ranges[self.mode] = self.manual_y_range
        self.scan_previous_window = (self.start_us, self.end_us)
        self.timer.stop()
        self.position_timer.stop()
        self.keys_down.clear()
        self.key_press_order.clear()
        self.controller_armed = False
        self.controller_filter.reset()
        self.controller_axes = {"x": 0, "y": 0, "z": 0}
        self.scan_panel.set_running(True)
        self.scan_axis_initialized = False
        self.scan_grid = np.full((settings['ny'], settings['nx']), np.nan, dtype=np.float32)
        self.flaw_grid = np.full_like(self.scan_grid, np.nan)
        self.tof_grid = np.full_like(self.scan_grid, np.nan)
        tof_levels = (settings['tof_gate_start_us'], settings['tof_gate_end_us'])
        self.tof_image.setImage(self.tof_grid, autoLevels=False, levels=tof_levels)
        self.tof_histogram.setLevels(*tof_levels)
        self.cscan_image.setImage(self.scan_grid, autoLevels=False, levels=(0, 1023))
        self.flaw_image.setImage(self.flaw_grid, autoLevels=False, levels=(0, 1023))
        for image in (self.cscan_image, self.flaw_image, self.tof_image):
            dx, dy = settings['dx_mm'] or 0.02, settings['dy_mm'] or 0.02
            image.setRect(QtCore.QRectF(settings['x0_mm'] - dx / 2, settings['y0_mm'] - dy / 2,
                                         settings['nx'] * dx, settings['ny'] * dy))
        self.cscan_histogram.setLevels(0, 1023)
        self.flaw_histogram.setLevels(0, 1)
        for plot in (self.cscan_plot, self.flaw_plot, self.tof_plot):
            plot.setRange(xRange=(0, max(dx/2, (settings['nx'] - 1)*dx)),
                          yRange=(0, max(dy/2, (settings['ny'] - 1)*dy)), padding=0, disableAutoRange=True)
        self.cscan_graph.show()
        if self.height() < 700:
            self.resize(max(1500, self.width()), 750)
        self.bscan_panel.show()
        self.graph_splitter.setSizes([self.height() // 3] * 3)
        self.set_capture_mode('raw')
        self.start_us = max(0, min(settings['gate_start_us'], settings['flaw_gate_start_us'], settings['tof_gate_start_us']) - 15.0)
        self.end_us = min(8000 / 60.0, max(settings['gate_end_us'], settings['flaw_gate_end_us'], settings['tof_gate_end_us']) + 15.0)
        self.start_us = min(self.start_us, settings['bscan_gate_start_us'])
        self.end_us = max(self.end_us, settings['bscan_gate_end_us'])
        self.plot_widget.setXRange(self.start_us, self.end_us, padding=0)
        self.bscan_start, self.bscan_end = bscan_start, bscan_end
        self.bscan_current_row = None
        self.bscan_row_select.setEnabled(False)
        self.bscan_row_select.blockSignals(True)
        self.bscan_row_select.setRange(1, settings['ny'])
        self.bscan_row_select.setValue(1)
        self.bscan_row_select.blockSignals(False)
        self.bscan_data = np.full((self.bscan_end - self.bscan_start, settings['nx']), np.nan, dtype=np.float32)
        self.render_bscan(0, reset_levels=True)
        self.scan_panel.progress.setText(f'Homing X/Y | Bottom left: {settings["home_start_x_mm"]:.2f}, {settings["home_start_y_mm"]:.2f} mm from home | {settings["nx"] * settings["ny"]} points')
        self.scan_worker = ScanWorker(self.probe, settings, self)
        self.scan_worker.point_received.connect(self.update_scan_point)
        self.scan_worker.scan_progress.connect(self.scan_panel.progress.setText)
        self.scan_worker.scan_finished.connect(self.finish_scan)
        self.scan_worker.finished.connect(self.scan_thread_ended)
        self.scan_worker.start()
        self.statusBar().showMessage('C-scan in progress')

    def stop_scan(self):
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.request_stop()
            self.scan_panel.stop_button.setEnabled(False)
            self.statusBar().showMessage('Stopping C-scan')

    def update_scan_point(self, point):
        if self.scan_grid is None or self.scan_settings is None:
            return
        row, col = point['row'], point['col']
        if not (0 <= row < self.scan_grid.shape[0] and
                0 <= col < self.scan_grid.shape[1]):
            return
        self.scan_grid[row, col] = point['amplitude_pp']
        self.flaw_grid[row, col] = point['flaw_pp']
        self.tof_grid[row, col] = point['tof_us']
        self.tof_image.setImage(self.tof_grid, autoLevels=False)
        self.cscan_image.setImage(self.scan_grid, autoLevels=False, levels=(0, 1023))
        flaw_values = self.flaw_grid[np.isfinite(self.flaw_grid)]
        flaw_max = max(1.0, float(np.max(flaw_values))) if flaw_values.size else 1.0
        self.flaw_image.setImage(self.flaw_grid, autoLevels=False, levels=(0, flaw_max))
        self.flaw_histogram.setLevels(0, flaw_max)
        if not hasattr(self, 'scan_axis_initialized') or not self.scan_axis_initialized:
            settings = self.scan_settings
            dx = point['dx_mm'] or 0.02
            dy = point['dy_mm'] or 0.02
            x0 = point['x_mm'] - col * dx
            y0 = point['y_mm'] - row * dy
            for image in (self.cscan_image, self.flaw_image, self.tof_image):
                image.setRect(QtCore.QRectF(
                    x0 - dx / 2, y0 - dy / 2, settings['nx'] * dx, settings['ny'] * dy))
            for plot in (self.cscan_plot, self.flaw_plot, self.tof_plot):
                plot.setRange(xRange=(0, max(dx/2, (settings['nx'] - 1)*dx)),
                              yRange=(0, max(dy/2, (settings['ny'] - 1)*dy)), padding=0, disableAutoRange=True)
            self.scan_axis_initialized = True
        if self.bscan_current_row != row:
            self.bscan_current_row = row
            self.bscan_data.fill(np.nan)
            self.bscan_row_select.blockSignals(True)
            self.bscan_row_select.setValue(row + 1)
            self.bscan_row_select.blockSignals(False)
        self.bscan_data[:, col] = rectify_waveforms(point['waveform'], self.bscan_start, self.bscan_end)
        self.render_bscan(row)
        self.plot_waveform(point['waveform'], point['sample_rate_hz'])
        self.plot_widget.setTitle(f'Raw A-scan — point ({col + 1}, {row + 1})')
        done = np.count_nonzero(np.isfinite(self.scan_grid))
        total = self.scan_grid.size
        self.scan_panel.progress.setText(f'{done} / {total} points')
        self.statusBar().showMessage(
            f'C-scan {done}/{total} | X={point["x_mm"]:.3f} mm Y={point["y_mm"]:.3f} mm | '
            f'Amplitude={point["amplitude_pp"]} Flaw={point["flaw_pp"]} '
            f'TOF={point["tof_us"]:.3f} µs Averages={point["averages"]}')

    def render_bscan(self, row, reset_levels=False):
        settings = self.scan_settings
        dx = settings['dx_mm']
        dt = 1e6 / settings['sample_rate']
        x0 = settings['x0_mm']
        y = settings['y0_mm'] + row * settings['dy_mm']
        if reset_levels:
            self.bscan_image.setImage(self.bscan_data, autoLevels=False, levels=(0, 1023))
            self.bscan_histogram.setLevels(0, 1023)
        else:
            self.bscan_image.setImage(self.bscan_data, autoLevels=False)
        self.bscan_image.setRect(QtCore.QRectF(x0 - dx/2, (self.bscan_start - 0.5)*dt,
                                                settings['nx']*dx, (self.bscan_end-self.bscan_start)*dt))
        self.bscan_plot.setTitle(f'B-scan — Y = {y:.3f} mm | row {row + 1}/{settings["ny"]}')
        if reset_levels:
            self.bscan_plot.setRange(xRange=(0, max(dx/2, (settings['nx']-1)*dx)),
                                     yRange=(max(0, (self.bscan_start-.5)*dt), (self.bscan_end-.5)*dt), padding=0, disableAutoRange=True)

    def select_bscan_row(self, row_number):
        if self.scan_busy or self.bscan_volume is None:
            return
        row = row_number - 1
        self.bscan_data = bscan_line(self.bscan_volume[row], np.isfinite(self.scan_grid[row]),
                                     self.bscan_start, self.bscan_end)
        self.render_bscan(row)

    def finish_scan(self, completed, message):
        self.scan_busy = False
        self.scan_panel.set_running(False)
        applied_gain = getattr(self.scan_worker, 'applied_gain', None)
        if applied_gain is not None:
            self.gain = applied_gain
            self.scan_panel.gain.setValue(applied_gain)
        path = getattr(self.scan_worker, 'waveforms_path', None)
        if path and self.scan_grid is not None and np.any(np.isfinite(self.scan_grid)):
            try:
                self.bscan_volume = np.load(path, mmap_mode='r', allow_pickle=False)
                self.bscan_row_select.setEnabled(True)
            except (OSError, ValueError) as exc:
                print(f'[B-scan] {exc}')
        self.scan_panel.progress.setText(('Complete: ' if completed else 'Stopped/error: ') + message)
        self.statusBar().showMessage(message, 10000)
        self.start_us, self.end_us = self.scan_previous_window
        self.plot_widget.setXRange(self.start_us, self.end_us, padding=0)
        self.mode = None  # Do not save the temporary scan range as a manual setting.
        self.set_capture_mode(self.scan_previous_mode)
        self.position_timer.start(350)
        self.timer.start()
        if not completed:
            print(f'[Scan] {message}')

    def scan_thread_ended(self):
        worker = self.scan_worker
        self.scan_worker = None
        if worker is not None:
            worker.deleteLater()

    def update_frame(self):
        """Only request and plot firmware output. No Python-side signal DSP."""
        if self.scan_busy or self.goto_busy:
            return
        try:
            frame = self.probe.capture(self.mode)
        except (RuntimeError, ValueError, TimeoutError, OSError) as exc:
            print(f'[Acquisition] {exc}')
            self.statusBar().showMessage(f'Capture error: {exc}', 5000)
            return

        self.fs = frame.header.sample_rate_hz
        if self.fs <= 0:
            print('[Acquisition] Frame has invalid sampling rate')
            return

        if self.mode == 'a-law':
            values = alaw_decode(frame.samples(), frame.header.alaw_reference)
        else:
            values = frame.samples()

        if not self.plot_waveform(values, self.fs):
            self.statusBar().showMessage(
                f'Window is outside {values.size / self.fs * 1e6:.2f} µs capture', 5000)



if __name__ == '__main__':
    initial_mode = sys.argv[1] if len(sys.argv) > 1 else 'fft'
    if initial_mode not in ('raw', 'fft', 'a-law'):
        sys.exit('Usage: python acq.py [raw|fft|a-law]  (or --test_name ...)')
    app = QtWidgets.QApplication(sys.argv[:1])
    window = AScanApp(initial_mode=initial_mode)
    window.show()
    sys.exit(app.exec_())

