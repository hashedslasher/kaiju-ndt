import math
import numpy as np


def sample_window(start_us, end_us, sample_rate=60000000, sample_count=8000):
    if not (sample_rate > 0 and sample_count > 0 and 0 <= start_us < end_us <= sample_count * 1e6 / sample_rate):
        raise ValueError('Invalid B-scan time window')
    start = max(0, math.floor(start_us * sample_rate / 1e6))
    end = min(sample_count, math.ceil(end_us * sample_rate / 1e6))
    if start >= end:
        raise ValueError('B-scan window is outside capture')
    return start, end


def rectify_waveforms(raw, start, end):
    values = np.asarray(raw, dtype=np.float32)
    if values.ndim not in (1, 2) or not 0 <= start < end <= values.shape[-1]:
        raise ValueError('Invalid B-scan waveform shape or window')
    baseline = values.mean(axis=-1, keepdims=True)
    return np.abs(values[..., start:end] - baseline)


def bscan_line(raw_row, valid, start, end):
    result = np.full((end - start, len(valid)), np.nan, dtype=np.float32)
    valid = np.asarray(valid, dtype=bool)
    if np.any(valid):
        result[:, valid] = rectify_waveforms(raw_row[valid], start, end).T
    return result
