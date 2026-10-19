import argparse
import importlib
from . import common

MODULES = {
    'capture': 'capture',
    'integrity': 'integrity',
    'snr': 'snr',
    'gain': 'gain',
    'tof': 'tof',
    'repeatability': 'repeatability',
    'averaging': 'averaging',
    'alignment': 'alignment',
    'bandwidth': 'bandwidth',
    'focus': 'focus',
    'contrast': 'contrast',
    'prf': 'prf',
    'gantry': 'gantry',
    'edge': 'edge',
    'selftest': 'selftest',
    'motion_noise': 'motion_noise',
}


def run(argv):
    name = argv[0][2:].replace('-', '_')
    if name not in MODULES:
        print('Available: ' + ', '.join('--' + key for key in MODULES))
        return 2
    module = importlib.import_module('.' + MODULES[name], __package__)
    parser = argparse.ArgumentParser(prog='python acq.py --' + name)
    common.arguments(parser)
    if hasattr(module, 'arguments'):
        module.arguments(parser)
    args = parser.parse_args(argv[1:])
    try:
        module.run(args)
    except (ValueError, RuntimeError, OSError, TimeoutError) as error:
        print(f'Error: {error}')
        return 1
    return 0
