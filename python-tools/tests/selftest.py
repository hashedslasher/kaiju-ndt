import re
from . import common
from lib.dsp import SELFTEST_NAMES, FLAG_SELFTEST


def run(args):
    if args.csv:
        raise ValueError('DSP selftest runs on live firmware')
    from lib.device import Pic0rick
    probe=Pic0rick(port=args.port)
    try:
        reply=probe.command('dsp selftest')
        found=re.search(r'frames=(\d+)',reply)
        if not found:
            raise RuntimeError('Firmware did not return selftest frame count')
        count=int(found.group(1))
        rows=[]
        for i in range(count):
            frame=probe.stream_frame()
            h=frame.header
            if not h.flags & FLAG_SELFTEST:
                raise RuntimeError('Received frame without selftest flag')
            rows.append(dict(index=i,case=h.selftest_case,case_name=SELFTEST_NAMES[h.selftest_case],
                             mode=h.payload_name,sequence=h.sequence,samples=h.sample_count,
                             payload_bytes=h.payload_bytes))
    finally:
        probe.close()
    common.write_csv(rows,args.output or common.target(args,'selftest'))
