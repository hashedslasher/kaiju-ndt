import argparse
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from . import lab_suite


class CaptureTest(unittest.TestCase):
    def test_csv_capture(self):
        class Header:
            capture_timestamp_us=1000
            sequence=0
            dropped_frames=0
            flags=0
            sample_rate_hz=60000000
            sample_count=8
            negative_ns=72
            positive_ns=72
            damp_ns=6000

        class Frame:
            def __init__(self,i):
                self.header=Header()
                self.header.sequence=i
                self.header.capture_timestamp_us=i*1000

            def samples(self):
                return np.arange(8,dtype=np.uint16)

        class Probe:
            def __init__(self):
                self.i=0
                self.closed=False

            def read_raw(self):
                i=self.i
                self.i+=1
                return Frame(i)

            def close(self):
                self.closed=True

        args=argparse.Namespace(gain=200,label='good',z_mm=0,x_mm=0,y_mm=0)
        probe=Probe()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'stationary.csv'
            with patch('tests.lab_suite.common.device',return_value=probe):
                lab_suite.capture(args,path,4)
            with path.open(newline='') as f:
                rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),4)
            self.assertEqual([int(r['sequence']) for r in rows],[0,1,2,3])
            self.assertEqual([int(rows[0][f's{i}']) for i in range(8)],list(range(8)))
            self.assertTrue(probe.closed)
