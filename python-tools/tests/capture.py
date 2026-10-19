from . import common


def arguments(parser):
    parser.add_argument('--append', action='store_true')


def run(args):
    if args.csv:
        raise ValueError('Use --output to capture, --csv for analysis')
    probe = common.device(args)
    try:
        rows = [common.frame_row(probe.read_raw(), args, i) for i in range(args.shots)]
    finally:
        probe.close()
    common.write_csv(rows, args.output or common.target(args, 'capture'), args.append)
