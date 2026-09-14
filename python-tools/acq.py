import sys
import numpy as np
from scipy import signal
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QAction
import pyqtgraph as pg
from lib.ndt_acquisition import get_probe

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
        
        
        self.parameters = menubar.addMenu('&Parameters')        
        self.gain = QAction('Gain', self)
        self.parameters.addAction(self.gain)
        
        self.pon_poff = QAction('Pon/Poff', self)
        self.parameters.addAction(self.pon_poff)

        self.window = QAction('Window', self)
        self.parameters.addAction(self.window)
        
        self.pulse_rate = QAction('Pulse Rate', self)
        self.parameters.addAction(self.pulse_rate)
        
        self.damp = QAction('Damp', self)
        self.parameters.addAction(self.damp)

        self.probe = get_probe()
        self.fs = 60e6
        self.gain = 460
        self.pon, self.poff, self.damp = 75, 75, 6000
        self.probe.dac(self.gain)
        self.start_us, self.end_us = 0, 24
        
        nyq = self.fs / 2.0
        self.b, self.a = signal.butter(2, [7.5e6 / nyq, 12.5e6 / nyq], btype='bandpass')
        
        self.plot_widget = pg.PlotWidget()
        self.setCentralWidget(self.plot_widget)
        self.plot_widget.setXRange(self.start_us, self.end_us)
        self.plot_widget.setYRange(-0.05, 1.2)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('bottom', 'Time', units='µs')
        self.plot_widget.setLabel('left', 'Amplitude')
        
        self.curve_env = self.plot_widget.plot(pen=pg.mkPen(color='white', width=2), name="Squared Envelope")
        self.curve_peaks = self.plot_widget.plot(pen=None, symbol='x', symbolPen='r', symbolBrush='r', symbolSize=12)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(20)

    def update_frame(self):
        pulses = []
        waveform_count = 1
        
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
        
        #np.savetxt("pulses.csv", pulses)

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
