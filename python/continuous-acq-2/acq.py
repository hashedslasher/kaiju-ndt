import sys
import numpy as np
from scipy import signal
from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg
from lib.ndt_acquisition import get_probe

class AScanApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("A-scan")
        self.resize(900, 450)
        
        self.probe = get_probe()
        self.fs = 60e6
        self.gain = 450
        self.pon, self.poff, self.damp = 80, 80, 6000
        self.probe.dac(self.gain)
        self.start_us, self.end_us = 8, 12
        
        nyq = self.fs / 2.0
        self.b, self.a = signal.butter(2, [4.2e6 / nyq, 12.7e6 / nyq], btype='bandpass')
        
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
        waveform_count = 5
        for _ in range(waveform_count):
            self.probe.pulse_adc_trigger(pon=self.pon, poff=self.poff, damp=self.damp)
            C = self.probe.read()
            raw = [x.replace("b'", "") for x in str(C[2]).split(",") if len(x)]
            if raw and len(raw) > 1:
                pulses.append(np.array([(int(x, 16) - 512) / 512.0 for x in raw[:-1]], dtype=np.float32))
        
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
