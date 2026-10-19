import numpy as np
from . import common


def run(args):
    rows, w, fs = common.get_data(args, 'integrity')
    seq = np.array([int(r['sequence']) for r in rows])
    gaps = sum(max(0, int(diff)-1) for diff in np.diff(seq))
    drops = int(rows[-1]['dropped']) - int(rows[0]['dropped'])
    clipped = 100 * np.mean((w <= 0) | (w >= 1023))
    values = dict(frames=len(w), sample_count=w.shape[1], sample_rate_hz=fs, sequence_gaps=gaps,
                  firmware_drop_delta=drops, clipped_percent=round(clipped, 5),
                  min_adc=int(w.min()), max_adc=int(w.max()))
    print(values)
    common.save_summary(args, 'integrity_summary', values)
