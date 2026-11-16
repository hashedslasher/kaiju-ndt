import numpy as np


def waveform_y_range(mode, values, previous=None):
    if mode == 'raw':
        return (0.0, 1023.0)
    finite = np.asarray(values)[np.isfinite(values)]
    peak = max(0.0, float(finite.max())) if finite.size else 0.0
    upper = max(1.0, peak * 1.12)
    if previous is not None:
        upper = max(upper, previous[1])
    return (0.0, upper)
