import sys
import numpy as np
from scipy import signal
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QAction
import pyqtgraph as pg
from lib.ndt_acquisition import get_probe


class OverlayLineEdit(QtWidgets.QLineEdit):
    """Command prompt"""
    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.clear()
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)


class AScanApp(QtWidgets.QMainWindow):
    def __init__(self):
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

        self.probe = get_probe()
        self.fs = 60e6
        self.gain = 500
        self.pon, self.poff, self.damp = 35, 35, 8000
        self.probe.dac(self.gain)
        self.start_us, self.end_us = 0, 90
        
        nyq = self.fs / 2.0
        self.b, self.a = signal.butter(2, [8e6 / nyq, 13e6 / nyq], btype='bandpass')
        
        self.plot_widget = pg.PlotWidget()
        self.setCentralWidget(self.plot_widget)
        self.plot_widget.setXRange(self.start_us, self.end_us)
        self.plot_widget.setYRange(-0.05, 1.2)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('bottom', 'Time', units='µs')
        self.plot_widget.setLabel('left', 'Amplitude')
        
        self.curve_env = self.plot_widget.plot(pen=pg.mkPen(color='white', width=2), name="Squared Envelope")
        self.curve_peaks = self.plot_widget.plot(pen=None, symbol='x', symbolPen='r', symbolBrush='r', symbolSize=12)

        self.cmd_input = OverlayLineEdit(self)
        self.cmd_input.setPlaceholderText("gain, damp, pon, poff, window start end")
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

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(5)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Colon or event.text() == ':':
            self.center_command_prompt()
            self.cmd_input.show()
            self.cmd_input.setFocus()
            event.accept()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.center_command_prompt()

    def center_command_prompt(self):
        w, h = 340, 38
        x = (self.width() - w) // 2
        y = (self.height() - h) // 2
        self.cmd_input.setGeometry(x, y, w, h)

    def handle_command(self):
        text = self.cmd_input.text().strip()
        self.cmd_input.hide()
        self.cmd_input.clear()
        if not text:
            return

        parts = text.replace(',', ' ').split()
        cmd = parts[0].lower()

        try:
            if cmd == "gain" and len(parts) >= 2:
                self.gain = int(parts[1])
                self.probe.dac(self.gain)
            elif cmd in ("pon", "poff", "pon/poff") and len(parts) >= 2:
                val = int(parts[1])
                self.pon = val
                self.poff = val
            elif cmd == "damp" and len(parts) >= 2:
                self.damp = int(parts[1])
            elif cmd == "window" and len(parts) >= 3:
                self.start_us = float(parts[1])
                self.end_us = float(parts[2])
                self.plot_widget.setXRange(self.start_us, self.end_us)
            elif cmd == "pulse_rate" and len(parts) >= 2:
                self.waveform_count = int(parts[1])
        except ValueError:
            pass

    def update_frame(self):
        pulses = []
        waveform_count = 10
        
        SAMPLE_COUNT = 8000
        BYTES_PER_PULSE = SAMPLE_COUNT * 2 
        
        for _ in range(waveform_count):
            self.probe.ser.reset_input_buffer()
            
            cmd = f"start acq {self.pon} {self.poff} {self.damp}\n"
            self.probe.ser.write(bytearray(cmd, 'ascii'))
            self.probe.ser.flush()
            
            raw_bytes = self.probe.ser.read(BYTES_PER_PULSE)
            
            if len(raw_bytes) == BYTES_PER_PULSE:
                raw_ints = np.frombuffer(raw_bytes, dtype=np.uint16)
                shifted_ints = (raw_ints >> 1) & 0x3FF
                normalized = (shifted_ints.astype(np.float32) - 512.0) / 512.0
                pulses.append(normalized)
            else:
                print(f"Expected {BYTES_PER_PULSE} bytes, got {len(raw_bytes)}")
        
        if len(pulses) < waveform_count:
            return

        sig = np.mean(pulses, axis=0)
        sig_filtered = signal.filtfilt(self.b, self.a, sig)

        envelope = np.abs(signal.hilbert(sig_filtered))
        env_norm = envelope / (np.max(envelope) + 1e-9)
        env_squared = env_norm ** 2
        
        t = np.arange(len(sig)) / self.fs * 1e6   
        mask = (t >= self.start_us) & (t <= self.end_us)
        t_zoom, env_zoom = t[mask], env_squared[mask]

        if env_zoom.size == 0:
            return

        peaks, _ = signal.find_peaks(
            env_zoom,
            height=0.15,
            distance=int(0.4e-6 * self.fs),
            prominence=0.08
        )

        self.curve_env.setData(t_zoom, env_zoom)


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = AScanApp()
    window.show()
    sys.exit(app.exec_())
