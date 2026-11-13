#ifndef U4RK_DSP2_H
#define U4RK_DSP2_H

#include <stdbool.h>
#include <stdint.h>

#define U4RK_DSP2_MAX_AVERAGES 256u

bool u4rk_dsp2_begin(uint32_t samples, uint32_t averages);
bool u4rk_dsp2_add(const uint16_t *dma_samples, uint32_t samples);
bool u4rk_dsp2_finish(uint16_t *output, uint32_t samples);

#endif
