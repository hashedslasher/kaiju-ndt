import sys
if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1].startswith('--'):
    from tests import dispatch
    sys.exit(dispatch.run(sys.argv[1:]))
import numpy as np
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QAction
import pyqtgraph as pg
from lib.device import Pic0rick
from lib.protocol import alaw_decode
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
        "y": ("plus", "minus"),
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
        self.setCentralWidget(self.plot_widget)

        self.plot_widget.setXRange(self.start_us, self.end_us)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('bottom', 'Time', units='µs')
        self.plot_widget.setLabel('left', 'Envelope', units='ADC counts')

        self.curve = self.plot_widget.plot(
            pen=pg.mkPen(color='white', width=2)
        )
        self.mode = None
        self.set_capture_mode(initial_mode)

        self.cmd_input = OverlayLineEdit(self)
        self.cmd_input.setPlaceholderText(
            "raw | fft | a-law | gain N | window start end | pulse_rate Hz"
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
        self.timer.start(1000)

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
            "y": ("jog_y plus 2000" if y == QtCore.Qt.Key_W else
                  "jog_y minus 2000" if y == QtCore.Qt.Key_S else
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

            elif cmd == 'pulse_rate' and len(parts) == 2:
                rate = float(parts[1])
                if not 0 < rate <= 20:
                    raise ValueError('pulse_rate must be >0 and <=20 Hz')
                self.timer.setInterval(round(1000.0 / rate))
                print(f'[Acquisition] Display refresh {rate:g} Hz')

            elif cmd == 'help' and len(parts) == 1:
                print('Commands: raw | fft | a-law | gain N | pon N | poff N '
                      '| damp N | window START_US END_US | pulse_rate HZ')
            else:
                raise ValueError(f'Unknown or incomplete command: {text}')
        except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
            print(f'[Command] {exc}')
            self.statusBar().showMessage(str(exc), 5000)

    def update_frame(self):
        """Only request and plot firmware output. No Python-side signal DSP."""
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
        low, high = float(np.min(y)), float(np.max(y))
        padding = max((high - low) * 0.08, 1.0)
        if self.mode != 'raw':
            low = max(0.0, low - padding)
        else:
            low -= padding
        self.plot_widget.setYRange(low, high + padding, padding=0)



if __name__ == '__main__':
    initial_mode = sys.argv[1] if len(sys.argv) > 1 else 'fft'
    if initial_mode not in ('raw', 'fft', 'a-law'):
        sys.exit('Usage: python acq.py [raw|fft|a-law]  (or --test_name ...)')
    app = QtWidgets.QApplication(sys.argv[:1])
    window = AScanApp(initial_mode=initial_mode)
    window.show()
    sys.exit(app.exec_())

