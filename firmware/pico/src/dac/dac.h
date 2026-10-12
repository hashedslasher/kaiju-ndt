#ifndef DAC_H
#define DAC_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DAC_PIN_MOSI 15
#define DAC_PIN_CS   13
#define DAC_PIN_SCLK 14
#define DAC_CLK_HZ   2000000.0f

void dac_init(void);
void dac_data_calculation(uint16_t *data, uint16_t input, uint16_t config_bits);
void dac_write(uint16_t data);
void dac(const char *input);

#ifdef __cplusplus
}
#endif

#endif // DAC_H
