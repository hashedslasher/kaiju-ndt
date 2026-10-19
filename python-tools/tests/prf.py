import csv
import time
from . import common


def arguments(parser):
    parser.add_argument('--rates',default='10,25,50,75,100')
    parser.add_argument('--seconds',type=float,default=3)
    parser.add_argument('--warmup',type=int,default=3)
    parser.add_argument('--mode',choices=('raw','envelope','alaw','oneshot'),default='raw')


def summarize(rows):
    result=[]
    for rate in sorted({int(r['requested_hz']) for r in rows}):
        group=[r for r in rows if int(r['requested_hz'])==rate]
        if len(group)<2:
            continue
        host=float(group[-1]['host_s'])-float(group[0]['host_s'])
        device=(int(group[-1]['device_us'])-int(group[0]['device_us']))/1e6
        seq=[int(r['sequence']) for r in group]
        seq_missing=sum(max(0,b-a-1) for a,b in zip(seq,seq[1:]))
        missing_report=max(0,int(group[-1]['dropped'])-int(group[0]['dropped']))
        result.append(dict(requested_hz=rate,mode=group[0]['mode'],frames=len(group),
                           actual_host_hz=round((len(group)-1)/host,3) if host>0 else 0,
                           actual_device_hz=round((len(group)-1)/device,3) if device>0 else 0,
                           receive_MB_s=round(sum(int(r['payload_bytes']) for r in group)/max(host,1e-6)/1e6,3),
                           sequence_missing=seq_missing,reported_drops_delta=missing_report))
    return result


def run(args):
    if args.csv:
        with open(args.csv,newline='') as f:
            rows=list(csv.DictReader(f))
        results=summarize(rows)
        if results:
            common.write_csv(results,common.target(args,'prf_summary'))
        return
    if args.seconds<=0:
        raise ValueError('seconds must be positive')
    rows=[]
    rates=[int(x) for x in args.rates.split(',')] if args.mode!='oneshot' else [0]
    for rate in rates:
        probe=common.device(args)
        try:
            for _ in range(args.warmup):
                probe.read_raw()
            if args.mode!='oneshot':
                probe.stream_start(args.mode,rate)
            start=time.perf_counter()
            while time.perf_counter()-start < args.seconds:
                frame=probe.read_raw() if args.mode=='oneshot' else probe.stream_frame()
                h=frame.header
                rows.append(dict(mode=args.mode,requested_hz=rate,host_s=time.perf_counter(),device_us=h.capture_timestamp_us,
                                 sequence=h.sequence,dropped=h.dropped_frames,payload_bytes=h.payload_bytes,
                                 sample_count=h.sample_count,flags=h.flags))
        finally:
            if args.mode!='oneshot':
                probe.stream_stop()
            probe.close()
    common.write_csv(rows,args.output or common.target(args,'prf_timing'))
    results=summarize(rows)
    if results:
        common.write_csv(results,common.target(args,'prf_summary'))
