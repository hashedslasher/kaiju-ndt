#include "dsp2.h"

#include <string.h>

#include "u4rk.h"

static uint32_t accumulator[U4RK_RAW_SAMPLE_COUNT];
static uint32_t active_samples;
static uint32_t requested_averages;
static uint32_t completed_averages;

bool u4rk_dsp2_begin(uint32_t samples, uint32_t averages) {
    if (samples == 0 || samples > U4RK_RAW_SAMPLE_COUNT ||
        averages == 0 || averages > U4RK_DSP2_MAX_AVERAGES) return false;
    memset(accumulator, 0, samples * sizeof(accumulator[0]));
    active_samples = samples;
    requested_averages = averages;
    completed_averages = 0;
    return true;
}

bool u4rk_dsp2_add(const uint16_t *dma_samples, uint32_t samples) {
    if (!dma_samples || samples != active_samples ||
        completed_averages >= requested_averages) return false;
    for (uint32_t i = 0; i < samples; ++i)
        accumulator[i] += (dma_samples[i] >> 1) & 0x3ffu;
    ++completed_averages;
    return true;
}

bool u4rk_dsp2_finish(uint16_t *output, uint32_t samples) {
    if (!output || samples != active_samples ||
        completed_averages != requested_averages) return false;
    for (uint32_t i = 0; i < samples; ++i)
        output[i] = (uint16_t)((accumulator[i] + requested_averages / 2u) /
                               requested_averages);
    return true;
}
