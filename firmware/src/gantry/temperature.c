#include "temperature.h"
#include "hardware/gpio.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"
#include <stddef.h>
#include <stdio.h>

#define DS18B20_DQ_PIN 20u
#define DS18B20_CONVERSION_US 750000u

static bool conversion_pending;
static uint64_t conversion_started;
static const char *error_message = "not tested";
static temperature_stats_t stats;
static char scratchpad_message[128];
static bool scratchpad_seen;

static bool initialized;

static void init_bus(void)
{
    if (initialized) return;
    gpio_init(DS18B20_DQ_PIN);
    gpio_set_dir(DS18B20_DQ_PIN, GPIO_IN);
    gpio_put(DS18B20_DQ_PIN, 0);
    gpio_disable_pulls(DS18B20_DQ_PIN);
    initialized = true;
}

static void dq_low(void) { gpio_set_dir(DS18B20_DQ_PIN, GPIO_OUT); }
static void dq_release(void) { gpio_set_dir(DS18B20_DQ_PIN, GPIO_IN); }

static bool reset_bus(void)
{
    init_bus();
    ++stats.resets;
    stats.presence = false;
    stats.reset_low_us = 0;
    stats.presence_read_us = 0;
    dq_release();
    busy_wait_us_32(5u);
    stats.idle_high = gpio_get(DS18B20_DQ_PIN);
    if (!stats.idle_high) {
        ++stats.no_presence;
        error_message = "DQ stuck low at idle";
        return false;
    }
    const uint32_t irq = save_and_disable_interrupts();
    dq_low();
    const uint64_t start = time_us_64();
    busy_wait_us_32(480u);
    dq_release();
    const uint64_t released = time_us_64();
    stats.reset_low_us = (uint32_t)(released - start);
    busy_wait_us_32(70u);
    stats.presence = !gpio_get(DS18B20_DQ_PIN);
    stats.presence_read_us = (uint32_t)(time_us_64() - released);
    restore_interrupts(irq);
    busy_wait_us_32(410u);
    if (!stats.presence || !gpio_get(DS18B20_DQ_PIN)) {
        ++stats.no_presence;
        error_message = !stats.presence ? "DS18B20 presence pulse not detected" : "DQ stuck low after reset";
        return false;
    }
    return true;
}

static bool write_bit(bool bit)
{
    const uint32_t irq = save_and_disable_interrupts();
    dq_low();
    const uint64_t start = time_us_64();
    busy_wait_us_32(bit ? 6u : 60u);
    dq_release();
    if (bit) stats.write1_low_us = (uint32_t)(time_us_64() - start);
    restore_interrupts(irq);
    busy_wait_us_32(bit ? 64u : 10u);
    return true;
}

static bool read_bit(bool *bit)
{
    const uint32_t irq = save_and_disable_interrupts();
    dq_low();
    const uint64_t start = time_us_64();
    busy_wait_us_32(3u);
    dq_release();
    busy_wait_us_32(9u);
    *bit = gpio_get(DS18B20_DQ_PIN);
    stats.read_sample_us = (uint32_t)(time_us_64() - start);
    stats.sample_high = *bit;
    restore_interrupts(irq);
    busy_wait_us_32(55u);
    return true;
}

static bool write_byte(uint8_t byte)
{
    for (unsigned i = 0; i < 8u; ++i) {
        if (!write_bit((byte & 1u) != 0u)) return false;
        byte >>= 1;
    }
    return true;
}

static bool read_byte(uint8_t *byte)
{
    *byte = 0;
    for (unsigned i = 0; i < 8u; ++i) {
        bool bit;
        if (!read_bit(&bit)) return false;
        if (bit) *byte |= (uint8_t)(1u << i);
    }
    return true;
}

static uint8_t crc8(const uint8_t *bytes, unsigned count)
{
    uint8_t crc = 0;
    for (unsigned i = 0; i < count; ++i) {
        uint8_t value = bytes[i];
        for (unsigned j = 0; j < 8; ++j) {
            bool mix = ((crc ^ value) & 1u) != 0;
            crc >>= 1;
            if (mix) crc ^= 0x8Cu;
            value >>= 1;
        }
    }
    return crc;
}

static bool select_sensor(void)
{
    return reset_bus() && write_byte(0xCCu);
}

static temperature_result_t validate_scratchpad(const uint8_t data[9], float *degrees_c)
{
    const uint8_t expected_crc = crc8(data, 8);
    const int16_t raw = (int16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8));
    const float c = (float)raw / 16.0f;
    const char *reason;
    temperature_result_t result = TEMPERATURE_UNAVAILABLE;
    if (expected_crc != data[8]) {
        ++stats.crc_fail;
        reason = "crc_mismatch";
    } else if (data[5] != 0xFFu || data[7] != 0x10u || (data[4] & 0x9Fu) != 0x1Fu) {
        ++stats.invalid_data;
        reason = "scratchpad_format";
    } else if (c < -55.0f || c > 125.0f) {
        ++stats.invalid_data;
        reason = "out_of_range";
    } else if (raw == 0x0550) {
        ++stats.invalid_data;
        reason = "85C_power_on_or_actual";
    } else {
        *degrees_c = c;
        ++stats.valid;
        reason = "ok";
        result = TEMPERATURE_READY;
    }
    snprintf(scratchpad_message, sizeof scratchpad_message,
             "%s scratchpad=%02X:%02X:%02X:%02X:%02X:%02X:%02X:%02X:%02X crc_calc=%02X raw=%d",
             reason, (unsigned)data[0], (unsigned)data[1], (unsigned)data[2],
             (unsigned)data[3], (unsigned)data[4], (unsigned)data[5],
             (unsigned)data[6], (unsigned)data[7], (unsigned)data[8],
             (unsigned)expected_crc, (int)raw);
    scratchpad_seen = true;
    error_message = scratchpad_message;
    return result;
}

temperature_result_t temperature_poll(float *degrees_c)
{
    if (!degrees_c) return TEMPERATURE_UNAVAILABLE;
    if (!conversion_pending) {
        ++stats.attempts;
        if (!select_sensor() || !write_byte(0x44u)) return TEMPERATURE_UNAVAILABLE;
        conversion_started = time_us_64();
        conversion_pending = true;
        return TEMPERATURE_PENDING;
    }
    if (time_us_64() - conversion_started < DS18B20_CONVERSION_US) return TEMPERATURE_PENDING;
    conversion_pending = false;
    if (!select_sensor() || !write_byte(0xBEu)) return TEMPERATURE_UNAVAILABLE;
    uint8_t data[9];
    for (unsigned i = 0; i < 9; ++i) {
        if (!read_byte(&data[i])) return TEMPERATURE_UNAVAILABLE;
    }
    return validate_scratchpad(data, degrees_c);
}

bool temperature_test(void)
{
    ++stats.tests;
    conversion_pending = false;
    stats.write1_low_us = 0;
    stats.read_sample_us = 0;
    const bool present = reset_bus();
    if (!stats.idle_high) return false;
    bool bit;
    if (!write_bit(true) || !read_bit(&bit)) return false;
    if (present) error_message = scratchpad_seen ? scratchpad_message : "diagnostic complete; no scratchpad read yet";
    return present;
}

const char *temperature_error(void) { return error_message; }
const temperature_stats_t *temperature_stats(void) { return &stats; }
