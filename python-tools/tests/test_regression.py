import io
import struct
import unittest
import zlib
import numpy as np
from . import common
from lib import protocol as dsp


class DataTests(unittest.TestCase):
    def test_frames(self):
        samples=np.arange(8000,dtype='<u2')%1024
        payload=samples.tobytes()
        header=dsp.HEADER.pack(b'P0RK',1,1,16,42,8000,60000000,len(payload),12345,512.,0.,1.,75,6000,75,0,zlib.crc32(payload))
        data=header+payload
        class FakeReader:
            def __init__(self):
                self.memory=io.BytesIO(data)
            def read(self,n):
                return self.memory.read(n)
        frame=dsp.FrameReader(FakeReader()).read_frame()
        self.assertEqual(frame.header.sequence,42)
        self.assertTrue(np.array_equal(frame.samples(),samples))

    def test_snr(self):
        rng=np.random.default_rng(77)
        w=rng.normal(512,2,(64,8000))
        w[:,600:630]+=100
        fs=60e6
        base,_,_=common.snr(w,fs,[10,10.5],[20,22])
        avg=w.reshape(8,8,8000).mean(axis=1)
        averaged,_,_=common.snr(avg,fs,[10,10.5],[20,22])
        self.assertGreater(averaged.mean()-base.mean(),6)

    def test_csv_roundtrip(self):
        import tempfile
        from pathlib import Path
        rows=[{'index':0,'sample_rate_hz':60000000,'s0':512,'s1':514},
              {'index':1,'sample_rate_hz':60000000,'s0':513,'s1':511}]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'wave.csv'
            common.write_csv(rows,path)
            meta,w,fs=common.load(path)
            self.assertEqual(w.shape,(2,2))
            self.assertEqual(fs,60000000)
            self.assertEqual(w[1,1],511)

    def test_motion_commands(self):
        import sys
        import types
        if 'serial' not in sys.modules:
            ser=types.ModuleType('serial')
            tools=types.ModuleType('serial.tools')
            ports=types.ModuleType('serial.tools.list_ports')
            ports.comports=lambda:[]
            ser.tools=tools
            tools.list_ports=ports
            sys.modules['serial']=ser
            sys.modules['serial.tools']=tools
            sys.modules['serial.tools.list_ports']=ports
        from lib.device import Pic0rick
        class SerialFake:
            def __init__(self):
                self.commands=[]
            def write(self,data):
                self.commands.append(data)
            def flush(self):
                pass
            def readline(self):
                return b'OK test\r\n'
        probe=Pic0rick.__new__(Pic0rick)
        probe.ser=SerialFake()
        probe.jog('x','plus',2000)
        probe.move('z','down',500,200)
        probe.stop('all')
        self.assertEqual(probe.ser.commands,[b'jog_x plus 2000\n',b'move_z down 500 200\n',b'stop_all\n'])
        with self.assertRaises(ValueError):
            probe.move('x','plus',2000,5001)


if __name__=='__main__':
    unittest.main()
