#ifndef SCAN_TOF_H
#define SCAN_TOF_H
#include <stdint.h>

static inline int32_t scan_tof_sample(const uint16_t *samples, uint32_t count,
                                      uint32_t start, uint32_t end, uint32_t threshold)
{
    if (!samples || start >= end || end > count) return -1;
    uint32_t sum = 0;
    for (uint32_t i = 0; i < count; ++i) sum += samples[i];
    uint16_t lo = UINT16_MAX, hi = 0;
    uint32_t best = start;
    int64_t max_deviation = -1;
    for (uint32_t i = start; i < end; ++i) {
        uint16_t v = samples[i];
        if (v < lo) lo = v;
        if (v > hi) hi = v;
        int64_t deviation = (int64_t)v * count - sum;
        if (deviation < 0) deviation = -deviation;
        if (deviation > max_deviation) {
            max_deviation = deviation;
            best = i;
        }
    }
    if ((uint32_t)(hi - lo) < threshold || hi == lo) return -1;
    return (int32_t)best;
}
#endif
