import argparse
import csv
import json
import contextlib
import io
from datetime import datetime, timezone
from pathlib import Path

from . import common


def arguments(parser):
    parser.set_defaults(shots=500, gain=200, negative_ns=72, positive_ns=72,
                        damp_ns=6000, echo_us=[80.0, 95.0], noise_us=[112.0, 125.0],
                        outdir='results/lab_suite', label='good')
    parser.add_argument('--timing-gate', type=float, nargs=2, default=[80.0, 92.0])
    parser.add_argument('--max-lag', type=int, default=90)
    parser.add_argument('--reference-csv')
    parser.add_argument('--prf-seconds', type=float, default=5.0)
    parser.add_argument('--skip-prf', action='store_true')
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--stream-rates', default='')
    parser.add_argument('--gain-levels', default='')
    parser.add_argument('--gain-per-level', type=int, default=24)
    parser.add_argument('--focus-z-values', default='')
    parser.add_argument('--focus-shots', type=int, default=32)
    parser.add_argument('--contrast-capture', action='store_true')
    parser.add_argument('--motion-noise-capture', action='store_true')
    parser.add_argument('--stage-shots', type=int, default=64)
    parser.add_argument('--gain-csv')
    parser.add_argument('--focus-csv')
    parser.add_argument('--contrast-csv')
    parser.add_argument('--motion-noise-csv')
    parser.add_argument('--prf-csv')
    parser.add_argument('--skip-acquire', action='store_true')


def capture(args, path, shots, gain=None, label=None, z=None):
    args.gain = args.gain if gain is None else gain
    args.label = args.label if label is None else label
    args.z_mm = args.z_mm if z is None else z
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    probe=common.device(args)
    try:
        with path.open('w', newline='') as f:
            writer=None
            for index in range(shots):
                row=common.frame_row(probe.read_raw(),args,index)
                if writer is None:
                    writer=csv.DictWriter(f,fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)
                if (index+1)%100==0:
                    f.flush()
                    print(f'{index+1}/{shots} captured')
    finally:
        probe.close()
    print(path)
    return path


def stage_capture(args,path,settings):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    probe=common.device(args)
    try:
        with path.open('w',newline='') as f:
            writer=None
            index=0
            for description, label, z, gain, count in settings:
                probe.disarm_pulser()
                input(description + '  Press Enter when stationary and ready: ')
                args.label=label
                args.z_mm=z
                args.gain=gain
                probe.set_gain(gain)
                probe.arm_pulser()
                for _ in range(count):
                    row=common.frame_row(probe.read_raw(),args,index)
                    if writer is None:
                        writer=csv.DictWriter(f,fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    index+=1
                f.flush()
    finally:
        probe.close()
    print(path)
    return path


def invoke(name, args, csv_path, dest, changes=None):
    import importlib
    module=importlib.import_module('.'+name,__package__)
    copied=argparse.Namespace(**vars(args))
    if hasattr(module, 'arguments'):
        module_parser=argparse.ArgumentParser(add_help=False)
        module.arguments(module_parser)
        for name, value in vars(module_parser.parse_args([])).items():
            if not hasattr(copied, name):
                setattr(copied, name, value)
    copied.csv=str(csv_path) if csv_path else None
    copied.outdir=str(dest)
    copied.plot=True
    for k,v in (changes or {}).items():
        setattr(copied,k,v)
    log=Path(dest)/'execution.log'
    log.parent.mkdir(parents=True,exist_ok=True)
    capture_out=io.StringIO()
    try:
        with contextlib.redirect_stdout(capture_out):
            module.run(copied)
    finally:
        log.write_text(capture_out.getvalue())


def run(args):
    if args.shots<3 or args.prf_seconds<=0:
        raise ValueError('shots must be at least 3 and prf-seconds must be positive')
    if args.echo_us[0]>=args.echo_us[1] or args.noise_us[0]>=args.noise_us[1]:
        raise ValueError('Gate start must precede end')
    root=Path(args.outdir)
    root.mkdir(parents=True,exist_ok=True)
    raw=root/'raw'
    raw.mkdir(parents=True,exist_ok=True)
    if args.csv:
        dataset=Path(args.csv).resolve()
    elif args.skip_acquire:
        dataset=raw/'stationary.csv'
        if not dataset.exists():
            raise ValueError('No saved stationary.csv; specify --csv or capture first')
    else:
        dataset=capture(args,raw/'stationary.csv',args.shots)
    config=dict(created_utc=datetime.now(timezone.utc).isoformat(), source_csv=str(dataset),
                sample='Aluminum plate, nominal 6.11 mm', water_path_mm=63.0,
                probe='10 MHz spherical focus 3 inch, nominal element diameter 11 mm',
                material_longitudinal_velocity_m_s_assumed=6320.0,
                water_velocity_m_s_assumed=1480.0,
                focus_mm_in_water=76.2,
                expected_frontwall_us=2*.063/1480*1e6,
                expected_thickness_echo_interval_us=2*.00611/6320*1e6,
                pulse_negative_ns=args.negative_ns,pulse_positive_ns=args.positive_ns,
                damping_ns=args.damp_ns,gain_setting=args.gain,echo_gate_us=args.echo_us,
                noise_gate_us=args.noise_us,timing_gate_us=args.timing_gate,
                capture_shots=args.shots,prf_seconds=args.prf_seconds)
    (root/'configuration.json').write_text(json.dumps(config,indent=2)+'\n')
    status=[]
    def run_stage(name, dataset, options=None):
        print(name)
        try:
            invoke(name,args,dataset,root/'analysis'/name,options)
            print(f'{name}: OK')
            status.append(dict(test=name,status='ok',source_csv=str(dataset),error=''))
        except (ValueError,RuntimeError,TimeoutError,OSError,IndexError,KeyError,ZeroDivisionError) as ex:
            print(f'{name}: {ex}')
            status.append(dict(test=name,status='failed',source_csv=str(dataset),error=str(ex)))
    for name in ('integrity','snr','repeatability','averaging','alignment',
                 'timing_offset','bandwidth','bandwidth_individual','tof','echo_spacing'):
        opts={'timing_gate':args.timing_gate,'max_lag':args.max_lag,'reference_csv':args.reference_csv} if name=='timing_offset' else {'max_lag':args.max_lag} if name=='alignment' else None
        run_stage(name,dataset,opts)
    if not args.skip_prf and not args.csv and not args.skip_acquire:
        try:
            invoke('prf',args,None,root/'analysis'/'prf_oneshot',
                   dict(mode='oneshot',seconds=args.prf_seconds,warmup=0,output=str(raw/'prf_oneshot.csv')))
            status.append(dict(test='prf_oneshot',status='ok',source_csv=str(raw/'prf_oneshot.csv'),error=''))
        except (ValueError,RuntimeError,OSError,TimeoutError) as ex:
            print(f'prf_oneshot: {ex}')
            status.append(dict(test='prf_oneshot',status='failed',source_csv='',error=str(ex)))
    if args.selftest and not args.csv:
        run_stage('selftest',None)
    if args.stream_rates and not args.csv:
        rates=[int(v) for v in args.stream_rates.split(',')]
        if any(r<1 or r>100 for r in rates):
            raise ValueError('Streaming rate must be in 1..100 Hz, firmware cap does not establish safety')
        try:
            invoke('prf',args,None,root/'analysis'/'prf_stream',
                   dict(mode='raw',rates=args.stream_rates,seconds=args.prf_seconds,
                        warmup=0,output=str(raw/'prf_stream.csv')))
            status.append(dict(test='prf_stream',status='ok',source_csv=str(raw/'prf_stream.csv'),error=''))
        except (ValueError,RuntimeError,OSError,TimeoutError) as ex:
            print(f'prf_stream: {ex}')
            status.append(dict(test='prf_stream',status='failed',source_csv='',error=str(ex)))
    if args.gain_levels and not args.csv:
        try:
            invoke('gain',args,None,root/'analysis'/'gain',
                   dict(levels=args.gain_levels,per_level=args.gain_per_level,
                        output=str(raw/'gain_sweep.csv')))
            status.append(dict(test='gain',status='ok',source_csv=str(raw/'gain_sweep.csv'),error=''))
        except (ValueError,RuntimeError,OSError,TimeoutError) as ex:
            print(f'gain: {ex}')
            status.append(dict(test='gain',status='failed',source_csv='',error=str(ex)))
    if args.focus_z_values and not args.csv:
        values=[float(v) for v in args.focus_z_values.split(',')]
        settings=[(f'Manually position probe at measured Z = {v} mm',
                   'good',v,args.gain,args.focus_shots) for v in values]
        focus_path=stage_capture(args,raw/'focus_z.csv',settings)
        run_stage('focus',focus_path)
        run_stage('tof',focus_path,dict(velocity=1480.0))
    if args.contrast_capture and not args.csv:
        settings=[('Position above KNOWN GOOD aluminum or reference', 'good',args.z_mm,args.gain,args.stage_shots),
                  ('Position above KNOWN DEFECT or other distinct reference', 'hole',args.z_mm,args.gain,args.stage_shots)]
        path=stage_capture(args,raw/'contrast.csv',settings)
        run_stage('contrast',path)
    if args.motion_noise_capture and not args.csv:
        settings=[('Set motors disabled, probe stationary', 'motors_off',args.z_mm,args.gain,args.stage_shots),
                  ('Set motors enabled but do not move', 'motors_on',args.z_mm,args.gain,args.stage_shots)]
        path=stage_capture(args,raw/'motion_noise.csv',settings)
        run_stage('motion_noise',path)
    for name, source in (('gain',args.gain_csv),('focus',args.focus_csv),
                         ('contrast',args.contrast_csv),('motion_noise',args.motion_noise_csv),
                         ('prf',args.prf_csv)):
        if source:
            run_stage(name,source)
    if args.csv:
        print('Offline mode: stage-specific tests run when their labeled CSV files are supplied')
    common.write_csv(status,root/'test_status.csv')
    print(f'Results: {root}')
    if any(item['status']=='failed' for item in status):
        failed=', '.join(item['test'] for item in status if item['status']=='failed')
        raise RuntimeError(f'Finished with failed tests: {failed}')
