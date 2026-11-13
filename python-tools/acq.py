import sys
import math
if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1].startswith('--'):
    from tests import dispatch
    sys.exit(dispatch.run(sys.argv[1:]))
import numpy as np
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QAction
import pyqtgraph as pg
from lib.device import Pic0rick
from lib.protocol import alaw_decode
from lib.scan_ui import ScanSetupPanel, ScanWorker
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt


try:
    import pygame
    from pygame._sdl2 import controller as sdl_controller
except ImportError:
    pygame = None
    sdl_controller = None


GAMEPAD_DEADZONE = 0.1
GAMEPAD_POLL_MS = 10
TANK_BOTTOM_AT_Z_ZERO_MM = 7.875 * 25.4
Z_STEPS_PER_MM = 200.0


GAMEPAD_MAX_SPEED_HZ = {"x": 2500, "y": 2500, "z": 3000}
GAMEPAD_MIN_SPEED_HZ = 100
GAMEPAD_SPEED_STEP_HZ = 50


def stick_deflection(raw_value):

    value = max(-32768, min(32767, raw_value))
    value /= 32768.0 if value < 0 else 32767.0
    magnitude = abs(value)
    if magnitude <= GAMEPAD_DEADZONE:
        return 0.0
    scaled = (magnitude - GAMEPAD_DEADZONE) / (1.0 - GAMEPAD_DEADZONE)
    return scaled if value > 0 else -scaled


def gamepad_jog_command(axis, deflection):

    if deflection == 0:
        return f"stop_{axis}"

    max_speed = int(GAMEPAD_MAX_SPEED_HZ[axis])
    if max_speed <= 0:
        return f"stop_{axis}"

    min_speed = min(GAMEPAD_MIN_SPEED_HZ, max_speed)
    travel = min(1.0, abs(deflection))
    speed = min_speed + (max_speed - min_speed) * travel

    speed = int(round(speed / GAMEPAD_SPEED_STEP_HZ)) * GAMEPAD_SPEED_STEP_HZ
    speed = max(min_speed, min(max_speed, speed))


    negative, positive = {
        "x": ("plus", "minus"),
        "y": ("minus", "plus"),
        "z": ("down", "up"),
    }[axis]
    return f"jog_{axis} {positive if deflection > 0 else negative} {speed}"


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
        self.fs =30e6
        self.gain = 460
        self.pon, self.poff, self.damp = 75, 75, 6000

        self.probe.set_gain(self.gain)
        self.probe.configure_pulse(self.pon, self.damp, self.poff)
        self.probe.arm_pulser()

        self.start_us, self.end_us = 0, 24

        self.plot_widget = pg.PlotWidget()
        self.graph_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.graph_splitter.addWidget(self.plot_widget)
        self.cscan_graph = pg.GraphicsLayoutWidget()
        self.cscan_plot = self.cscan_graph.addPlot(row=0, col=0, title='Amplitude scan')
        self.cscan_plot.setLabel('bottom', 'X')
        self.cscan_plot.setLabel('left', 'Y')
        self.cscan_plot.setAspectLocked(True)
        self.cscan_image = pg.ImageItem(axisOrder='row-major')
        self.cscan_plot.addItem(self.cscan_image)
        self.cscan_histogram = pg.HistogramLUTItem(image=self.cscan_image)
        self.cscan_histogram.gradient.loadPreset('viridis')
        self.cscan_graph.addItem(self.cscan_histogram, row=0, col=1)
        self.cscan_histogram.setLevels(0, 1023)
        self.flaw_plot = self.cscan_graph.addPlot(row=0, col=2, title='Flaw scan')
        self.flaw_plot.setLabel('bottom', 'X')
        self.flaw_plot.setLabel('left', 'Y')
        self.flaw_plot.setAspectLocked(True)
        self.flaw_image = pg.ImageItem(axisOrder='row-major')
        self.flaw_plot.addItem(self.flaw_image)
        self.flaw_histogram = pg.HistogramLUTItem(image=self.flaw_image)
        self.flaw_histogram.gradient.loadPreset('viridis')
        self.cscan_graph.addItem(self.flaw_histogram, row=0, col=3)
        self.flaw_histogram.setLevels(0, 1023)
        self.graph_splitter.addWidget(self.cscan_graph)
        self.cscan_graph.hide()
        self.setCentralWidget(self.graph_splitter)
        self.scan_grid = None
        self.flaw_grid = None
        self.scan_settings = None
        self.scan_worker = None
        self.scan_busy = False
        self.scan_previous_mode = None
        self.scan_previous_window = None

        self.scan_panel = ScanSetupPanel(self.probe.port)
        self.scan_dock = QtWidgets.QDockWidget('Scan setup', self)
        self.scan_dock.setObjectName('scanSetupDock')
        self.scan_dock.setWidget(self.scan_panel)
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

        self.plot_widget.setXRange(self.start_us, self.end_us)
        self.plot_widget.enableAutoRange(axis='y', enable=False)
        self.plot_widget.getViewBox().setMouseEnabled(x=True, y=False)
        self.y_range_initialized = False
        self.manual_y_range = None
        self.z_steps_per_mm = Z_STEPS_PER_MM
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
            "raw | fft | a-law | home | zero z | pos | yrange | z_steps_mm"
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

        self.controller_axes = {"x": 0.0, "y": 0.0, "z": 0.0}
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
        self.controller_timer.start(GAMEPAD_POLL_MS)
        self.poll_controller()

    def release_controller(self):

        self.controller_armed = False
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

        if self.scan_busy:
            self.controller_armed = False
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
                        print(f"[Controller] Connected: {sdl_controller.name_forindex(index)}")
                        break

            if self.controller is None:
                return

            x = stick_deflection(self.controller.get_axis(pygame.CONTROLLER_AXIS_LEFTX))
            y = stick_deflection(self.controller.get_axis(pygame.CONTROLLER_AXIS_LEFTY))
            z = stick_deflection(self.controller.get_axis(pygame.CONTROLLER_AXIS_RIGHTY))


            if self.cmd_input.isVisible() or not self.isActiveWindow():
                self.controller_armed = False
                self.set_controller_axes(0, 0, 0)
                return


            if not self.controller_armed:
                if (x, y, z) == (0, 0, 0):
                    self.controller_armed = True
                self.set_controller_axes(0, 0, 0)
                return

            self.set_controller_axes(x, y, z)
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
            if self.scan_busy:
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
        self.set_controller_axes(0, 0, 0)
        self.send_movement()

    def send_movement(self):
        if self.scan_busy:
            return

        def latest_down(*keys):
            down = [key for key in keys if key in self.keys_down]
            return max(down, key=lambda k: self.key_press_order.get(k, 0)) if down else None

        x = latest_down(QtCore.Qt.Key_A, QtCore.Qt.Key_D)
        y = latest_down(QtCore.Qt.Key_W, QtCore.Qt.Key_S)
        z = latest_down(QtCore.Qt.Key_J, QtCore.Qt.Key_K)


        desired = {
            "x": ("jog_x plus 2000" if x == QtCore.Qt.Key_A else
                  "jog_x minus 2000" if x == QtCore.Qt.Key_D else
                  gamepad_jog_command("x", self.controller_axes["x"])),
            "y": ("jog_y minus 2000" if y == QtCore.Qt.Key_W else
                  "jog_y plus 2000" if y == QtCore.Qt.Key_S else
                  gamepad_jog_command("y", self.controller_axes["y"])),
            "z": ("jog_z up 2000" if z == QtCore.Qt.Key_J else
                  "jog_z down 2000" if z == QtCore.Qt.Key_K else
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
                    self.probe.jog(parts[0][-1], parts[1], int(parts[2]))
            except (RuntimeError, ValueError, TimeoutError) as error:
                print(error)

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == QtCore.QEvent.ActivationChange and
                not self.isActiveWindow() and hasattr(self, "keys_down")):
            self.stop_manual_motion()

    def closeEvent(self, event):
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
        if self.scan_busy:
            return
        try:
            degrees_c = self.probe.temperature()
            if degrees_c is not None:
                self.temperature_box.setText(f'{degrees_c * 9.0 / 5.0 + 32.0:.2f} F')
        except (RuntimeError, ValueError, TimeoutError, OSError):
            self.temperature_box.clear()

    def refresh_clearance(self, reply=None):
        if self.scan_busy:
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
                z_steps = int(fields['z'])
                clearance_mm = TANK_BOTTOM_AT_Z_ZERO_MM - z_steps / self.z_steps_per_mm
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
        self.mode = mode
        self.curve.clear()
        if self.manual_y_range is None:
            self.y_range_initialized = False
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
        try:
            if cmd in ('raw', 'fft', 'a-law', 'alaw', 'envelope') and len(parts) == 1:
                self.set_capture_mode(cmd)

            elif cmd == 'gain' and len(parts) == 2:
                self.gain = int(parts[1])
                self.probe.set_gain(self.gain)

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
                if start < 0 or end <= start:
                    raise ValueError('Window must satisfy 0 <= start < end (µs)')
                self.start_us, self.end_us = start, end
                self.plot_widget.setXRange(start, end)

            elif cmd == 'yrange' and len(parts) == 3:
                low, high = float(parts[1]), float(parts[2])
                if not math.isfinite(low) or not math.isfinite(high) or high <= low:
                    raise ValueError('yrange requires finite MIN and MAX, with MIN < MAX')
                self.manual_y_range = (low, high)
                self.y_range_initialized = True
                self.plot_widget.setYRange(low, high, padding=0)

            elif cmd == 'yrange' and len(parts) == 2 and parts[1].lower() == 'auto':
                self.manual_y_range = None
                self.y_range_initialized = False

            elif cmd == 'z_steps_mm' and len(parts) == 2:
                value = float(parts[1])
                if not math.isfinite(value) or value <= 0:
                    raise ValueError('z_steps_mm must be a positive finite number')
                self.z_steps_per_mm = value
                self.refresh_clearance()
                self.statusBar().showMessage(f'Z steps/mm: {value:g}', 5000)

            elif cmd == 'pulse_rate' and len(parts) == 2:
                rate = float(parts[1])
                if not 0 < rate <= 20:
                    raise ValueError('pulse_rate must be >0 and <=20 Hz')
                self.timer.setInterval(round(1000.0 / rate))
                print(f'[Acquisition] Display refresh {rate:g} Hz')

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

            elif cmd == 'help' and len(parts) == 1:
                print('Commands: raw | fft | a-law | gain N | pon N | poff N '
                      '| damp N | window START_US END_US | pulse_rate HZ '
                      '| home | pos | zero z | z=0 | stop_all '
                      '| yrange MIN MAX | yrange auto | z_steps_mm N')
            else:
                raise ValueError(f'Unknown or incomplete command: {text}')
        except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
            print(f'[Command] {exc}')
            self.statusBar().showMessage(str(exc), 5000)

    def start_scan(self, settings):
        if self.scan_busy or (self.scan_worker is not None and self.scan_worker.isRunning()):
            return
        self.stop_manual_motion()
        self.scan_busy = True
        self.scan_settings = settings
        self.scan_previous_mode = self.mode
        self.scan_previous_window = (self.start_us, self.end_us)
        self.timer.stop()
        self.position_timer.stop()
        self.keys_down.clear()
        self.key_press_order.clear()
        self.controller_armed = False
        self.controller_axes = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.scan_panel.set_running(True)
        self.scan_axis_initialized = False
        self.scan_grid = np.full((settings['ny'], settings['nx']), np.nan, dtype=np.float32)
        self.flaw_grid = np.full_like(self.scan_grid, np.nan)
        self.cscan_image.setImage(self.scan_grid, autoLevels=False, levels=(0, 1023))
        self.flaw_image.setImage(self.flaw_grid, autoLevels=False, levels=(0, 1023))
        for image in (self.cscan_image, self.flaw_image):
            image.setRect(QtCore.QRectF(-0.5, -0.5, settings['nx'], settings['ny']))
        self.cscan_histogram.setLevels(0, 1023)
        self.flaw_histogram.setLevels(0, 1)
        for plot in (self.cscan_plot, self.flaw_plot):
            plot.setRange(xRange=(-0.5, settings['nx'] - 0.5),
                          yRange=(-0.5, settings['ny'] - 0.5), padding=0)
        self.cscan_graph.show()
        if self.height() < 700:
            self.resize(max(1250, self.width()), 750)
        self.graph_splitter.setSizes([self.height() // 2, self.height() // 2])
        self.set_capture_mode('raw')
        self.start_us = max(0, min(settings['gate_start_us'], settings['flaw_gate_start_us']) - 10.0)
        self.end_us = max(settings['gate_end_us'], settings['flaw_gate_end_us']) + 10.0
        self.plot_widget.setXRange(self.start_us, self.end_us)
        self.scan_panel.progress.setText(f'0 / {settings["nx"] * settings["ny"]} points')
        self.scan_worker = ScanWorker(self.probe, settings, self)
        self.scan_worker.point_received.connect(self.update_scan_point)
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
        self.cscan_image.setImage(self.scan_grid, autoLevels=False, levels=(0, 1023))
        flaw_values = self.flaw_grid[np.isfinite(self.flaw_grid)]
        flaw_max = max(1.0, float(np.max(flaw_values))) if flaw_values.size else 1.0
        self.flaw_image.setImage(self.flaw_grid, autoLevels=False, levels=(0, flaw_max))
        self.flaw_histogram.setLevels(0, flaw_max)
        if not hasattr(self, 'scan_axis_initialized') or not self.scan_axis_initialized:
            settings = self.scan_settings
            sx = settings['steps_mm_x'] or 1.0
            sy = settings['steps_mm_y'] or 1.0
            dx = settings['dx_steps'] / sx if settings['nx'] > 1 else 1.0
            dy = settings['dy_steps'] / sy if settings['ny'] > 1 else 1.0
            x0 = point['x_steps'] / sx - col * dx
            y0 = point['y_steps'] / sy - row * dy
            for image in (self.cscan_image, self.flaw_image):
                image.setRect(QtCore.QRectF(
                    x0 - dx / 2, y0 - dy / 2, settings['nx'] * dx, settings['ny'] * dy))
            self.cscan_plot.autoRange()
            self.flaw_plot.autoRange()
            self.scan_axis_initialized = True
        samples = point['waveform']
        sample_rate = point['sample_rate_hz']
        times = np.arange(len(samples), dtype=np.float64) * (1e6 / sample_rate)
        visible = (times >= self.start_us) & (times <= self.end_us)
        if np.any(visible):
            self.curve.setData(times[visible], samples[visible])
            if not self.y_range_initialized:
                low = float(np.min(samples[visible]))
                high = float(np.max(samples[visible]))
                margin = max(1.0, (high - low) * 0.08)
                self.plot_widget.setYRange(low - margin, high + margin, padding=0)
                self.y_range_initialized = True
        self.plot_widget.setTitle(f'Raw A-scan — point ({col + 1}, {row + 1})')
        done = np.count_nonzero(np.isfinite(self.scan_grid))
        total = self.scan_grid.size
        self.scan_panel.progress.setText(f'{done} / {total} points')
        self.statusBar().showMessage(
            f'C-scan {done}/{total} | X={point["x_steps"]} Y={point["y_steps"]} | '
            f'Amplitude={point["amplitude_pp"]} Flaw={point["flaw_pp"]} '
            f'Averages={point["averages"]}')

    def finish_scan(self, completed, message):
        self.scan_busy = False
        self.scan_panel.set_running(False)
        self.scan_panel.progress.setText(('Complete: ' if completed else 'Stopped/error: ') + message)
        self.statusBar().showMessage(message, 10000)
        self.start_us, self.end_us = self.scan_previous_window
        self.plot_widget.setXRange(self.start_us, self.end_us)
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
        if self.scan_busy:
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

        time_us = np.arange(values.size, dtype=np.float64) * (1e6 / self.fs)
        selection = (time_us >= self.start_us) & (time_us <= self.end_us)
        if not np.any(selection):
            self.curve.clear()
            self.statusBar().showMessage(
                f'Window is outside {values.size / self.fs * 1e6:.2f} µs capture',
                5000,
            )
            return

        x = time_us[selection]
        y = values[selection]
        self.curve.setData(x, y)
        if not self.y_range_initialized:
            low, high = float(np.min(y)), float(np.max(y))
            padding = max((high - low) * 0.08, 1.0)
            low = max(0.0, low - padding) if self.mode != 'raw' else low - padding
            self.plot_widget.setYRange(low, high + padding, padding=0)
            self.y_range_initialized = True



if __name__ == '__main__':
    initial_mode = sys.argv[1] if len(sys.argv) > 1 else 'fft'
    if initial_mode not in ('raw', 'fft', 'a-law'):
        sys.exit('Usage: python acq.py [raw|fft|a-law]  (or --test_name ...)')
    app = QtWidgets.QApplication(sys.argv[:1])
    window = AScanApp(initial_mode=initial_mode)
    window.show()
    sys.exit(app.exec_())

