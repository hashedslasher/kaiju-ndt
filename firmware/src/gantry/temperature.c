#include "temperature.h"

#include <stdint.h>
#include <stddef.h>

#include "hardware/gpio.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

#define DS18B20_DQ_PIN 20u
#define DS18B20_SKIP_ROM 0xCCu
#define DS18B20_CONVERT_T 0x44u
#define DS18B20_READ_SCRATCHPAD 0xBEu
#define DS18B20_CONVERSION_US 750000u

static bool initialized;
static bool conversion_pending;
static uint64_t conversion_started;
static const char *error_message = "not initialized";

static void one_wire_release(void)
{
    gpio_set_dir(DS18B20_DQ_PIN, GPIO_IN);
}

static void one_wire_low(void)
{
    gpio_set_dir(DS18B20_DQ_PIN, GPIO_OUT);
}

static void one_wire_init(void)
{
    gpio_init(DS18B20_DQ_PIN);
    gpio_put(DS18B20_DQ_PIN, 0);
    one_wire_release();
    gpio_pull_up(DS18B20_DQ_PIN);
    initialized = true;
}

static bool one_wire_reset(void)
{
    const uint32_t state = save_and_disable_interrupts();
    one_wire_low();
    busy_wait_us_32(480u);
    one_wire_release();
    busy_wait_us_32(70u);
    const bool present = !gpio_get(DS18B20_DQ_PIN);
    busy_wait_us_32(410u);
    restore_interrupts(state);
    return present && gpio_get(DS18B20_DQ_PIN);
}

static void one_wire_write_bit(bool bit)
{
    const uint32_t state = save_and_disable_interrupts();
    one_wire_low();
    if (bit) {
        busy_wait_us_32(6u);
        one_wire_release();
        busy_wait_us_32(64u);
    } else {
        busy_wait_us_32(60u);
        one_wire_release();
        busy_wait_us_32(10u);
    }
    restore_interrupts(state);
}

static bool one_wire_read_bit(void)
{
    const uint32_t state = save_and_disable_interrupts();
    one_wire_low();
    busy_wait_us_32(3u);
    one_wire_release();
    busy_wait_us_32(9u);
    const bool bit = gpio_get(DS18B20_DQ_PIN);
    busy_wait_us_32(55u);
    restore_interrupts(state);
    return bit;
}

static void one_wire_write_byte(uint8_t value)
{
    for (unsigned bit = 0; bit < 8u; ++bit) {
        one_wire_write_bit((value & 1u) != 0u);
        value >>= 1;
    }
}

static uint8_t one_wire_read_byte(void)
{
    uint8_t value = 0u;
    for (unsigned bit = 0; bit < 8u; ++bit) {
        if (one_wire_read_bit()) value |= (uint8_t)(1u << bit);
    }
    return value;
}

static uint8_t dallas_crc8(const uint8_t *data, unsigned length)
{
    uint8_t crc = 0u;
    for (unsigned i = 0; i < length; ++i) {
        uint8_t value = data[i];
        for (unsigned bit = 0; bit < 8u; ++bit) {
            const bool mix = ((crc ^ value) & 1u) != 0u;
            crc >>= 1;
            if (mix) crc ^= 0x8Cu;
            value >>= 1;
        }
    }
    return crc;
}

static bool one_wire_select(void)
{
    if (!one_wire_reset()) {
        error_message = "DS18B20 presence pulse not detected";
        return false;
    }
    one_wire_write_byte(DS18B20_SKIP_ROM);
    return true;
}

temperature_result_t temperature_poll(float *degrees_c)
{
    if (degrees_c == NULL) {
        error_message = "temperature output missing";
        return TEMPERATURE_UNAVAILABLE;
    }
    if (!initialized) one_wire_init();
    if (!conversion_pending) {
        if (!one_wire_select()) return TEMPERATURE_UNAVAILABLE;
        one_wire_write_byte(DS18B20_CONVERT_T);
        conversion_started = time_us_64();
        conversion_pending = true;
        return TEMPERATURE_PENDING;
    }
    if (time_us_64() - conversion_started < DS18B20_CONVERSION_US) {
        return TEMPERATURE_PENDING;
    }
    conversion_pending = false;
    if (!one_wire_select()) return TEMPERATURE_UNAVAILABLE;
    one_wire_write_byte(DS18B20_READ_SCRATCHPAD);
    uint8_t scratchpad[9];
    for (unsigned i = 0; i < sizeof(scratchpad); ++i) {
        scratchpad[i] = one_wire_read_byte();
    }
    if (dallas_crc8(scratchpad, 8u) != scratchpad[8]) {
        error_message = "DS18B20 scratchpad CRC mismatch";
        return TEMPERATURE_UNAVAILABLE;
    }
    const int16_t raw = (int16_t)((uint16_t)scratchpad[0] |
                                  ((uint16_t)scratchpad[1] << 8));
    *degrees_c = (float)raw / 16.0f;
    if (*degrees_c < -55.0f || *degrees_c > 125.0f) {
        error_message = "DS18B20 temperature outside valid range";
        return TEMPERATURE_UNAVAILABLE;
    }
    error_message = "ok";
    return TEMPERATURE_READY;
}

const char *temperature_error(void)
{
    return error_message;
}
