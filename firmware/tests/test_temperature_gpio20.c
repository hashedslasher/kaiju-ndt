#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "temperature.h"

static uint64_t now;
static bool gpio_output;
static uint64_t falling_us;
static bool reset_sample;
static bool reading_bit;
static bool present = true;
static unsigned bit_index;
static unsigned write_index;
static uint8_t write_value;
static uint8_t scratchpad[9];
static unsigned nconverts;
static unsigned nreads;

uint64_t time_us_64(void) { return now; }
void busy_wait_us_32(uint32_t us) { now += us; }
uint32_t save_and_disable_interrupts(void) { return 0; }
void restore_interrupts(uint32_t state) { (void)state; }
void gpio_init(unsigned pin) { assert(pin == 20u); }
void gpio_put(unsigned pin, bool high) { assert(pin == 20u && !high); }
void gpio_pull_up(unsigned pin) { assert(pin == 20u); }
void gpio_set_dir(unsigned pin, bool output) {
    assert(pin == 20u);
    if (output) {
        assert(!gpio_output);
        falling_us = now;
        gpio_output = true;
        return;
    }
    if (!gpio_output) return;
    gpio_output = false;
    const uint64_t duration = now - falling_us;
    if (duration >= 480u) {
        reset_sample = true;
        write_index = 0;
        write_value = 0;
    } else if (duration <= 4u) {
        reading_bit = true;
    } else {
        assert(duration == 6u || duration == 60u);
        if (duration == 6u) write_value |= 1u << write_index;
        if (++write_index == 8u) {
            if (write_value == 0x44u) ++nconverts;
            if (write_value == 0xBEu) { ++nreads; bit_index = 0u; }
            write_index = 0;
            write_value = 0;
        }
    }
}
bool gpio_get(unsigned pin) {
    assert(pin == 20u && !gpio_output);
    if (reset_sample) {
        reset_sample = false;
        return !present;
    }
    if (reading_bit) {
        reading_bit = false;
        assert(bit_index < 72u);
        const bool result = (scratchpad[bit_index / 8u] >> (bit_index % 8u)) & 1u;
        ++bit_index;
        return result;
    }
    return true;
}
static uint8_t crc8(const uint8_t *data, unsigned n) {
    uint8_t crc = 0;
    for(unsigned i=0; i<n; ++i) {
        uint8_t value = data[i];
        for(unsigned bit=0; bit<8; ++bit) {
            const bool mix = ((crc ^ value) & 1u) != 0u;
            crc >>= 1;
            if(mix) crc ^= 0x8Cu;
            value >>= 1;
        }
    }
    return crc;
}
int main(void) {
    memcpy(scratchpad, (uint8_t[]){0x91,0x01,0x4b,0x46,0x7f,0xff,0x0c,0x10}, 8);
    scratchpad[8] = crc8(scratchpad, 8);
    float celsius = 0;
    assert(temperature_poll(&celsius) == TEMPERATURE_PENDING);
    assert(nconverts == 1);
    assert(temperature_poll(&celsius) == TEMPERATURE_PENDING);
    now += 800000u;
    assert(temperature_poll(&celsius) == TEMPERATURE_READY);
    assert(celsius > 25.05f && celsius < 25.07f);
    assert(nreads == 1);
    assert(temperature_poll(&celsius) == TEMPERATURE_PENDING);
    scratchpad[8] ^= 1u;
    now += 800000u;
    assert(temperature_poll(&celsius) == TEMPERATURE_UNAVAILABLE);
    assert(strcmp(temperature_error(), "DS18B20 scratchpad CRC mismatch") == 0);
    present = false;
    assert(temperature_poll(&celsius) == TEMPERATURE_UNAVAILABLE);
    assert(strcmp(temperature_error(), "DS18B20 presence pulse not detected") == 0);
    printf("PASS: GPIO20 bit timings, DS18B20 commands, conversion, CRC and absence\n");
}
