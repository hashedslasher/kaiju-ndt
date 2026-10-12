#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>

#include "dac.h"
#include "dac.pio.h"

static PIO dac_pio = pio1;
static uint dac_sm = 3;
static uint dac_offset;
static uint16_t dac_value;

void dac_init(void)
{
    dac_offset = pio_add_program(dac_pio, &dac_spi_program);
    dac_program_init(dac_pio, dac_sm, dac_offset,
                     DAC_PIN_MOSI, DAC_PIN_SCLK, DAC_CLK_HZ);

    gpio_init(DAC_PIN_CS);
    gpio_set_dir(DAC_PIN_CS, GPIO_OUT);
    gpio_put(DAC_PIN_CS, 1);
}

void dac_data_calculation(uint16_t *data, uint16_t input, uint16_t config_bits)
{
    *data = (uint16_t)((input << 2) | config_bits);
}

void dac_write(uint16_t data)
{
    dac_wait_idle(dac_pio, dac_sm);
    gpio_put(DAC_PIN_CS, 0);
    dac_put(dac_pio, dac_sm, data);
    dac_wait_idle(dac_pio, dac_sm);
    gpio_put(DAC_PIN_CS, 1);
}

void dac(const char *input)
{
    printf("DAC writing started\n");
    dac_data_calculation(&dac_value, (uint16_t)atoi(input), 0x3000);
    dac_write(dac_value);
    printf("DAC writing ended\n");
}
