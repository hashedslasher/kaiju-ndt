#include "bridge.h"

#include <string.h>

#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "pico/stdlib.h"

#define SC_RHR 0x00u
#define SC_THR 0x00u
#define SC_IER 0x01u
#define SC_FCR 0x02u
#define SC_LSR 0x05u
#define SC_LCR 0x03u
#define SC_SPR 0x07u
#define SC_TXLVL 0x08u
#define SC_RXLVL 0x09u
#define SC_IODIR 0x0Au
#define SC_IOSTATE 0x0Bu
#define SC_IOINTENA 0x0Cu
#define SC_IOCONTROL 0x0Eu
#define SC_DLL 0x00u
#define SC_DLH 0x01u

#define TMC_GCONF 0x00u
#define TMC_SLAVECONF 0x03u
#define TMC_IOIN 0x06u
#define TMC_CHOPCONF 0x6Cu
#define TMC_REPLY_TIMEOUT_US 30000u

static const uint8_t motor_channel[TMC_COUNT] = {0, 0, 0, 1, 1};
static const uint8_t motor_address[TMC_COUNT] = {0, 1, 2, 0, 1};
static const char *const motor_names[TMC_COUNT] = {"x1", "x2", "y1", "y2", "z"};
static bool motor_online[TMC_COUNT];
static bool ready;
static uint8_t output_state = BRIDGE_GPIO_ENABLE;
static const char *last_error = "uninitialized";

static bool fail(const char *why)
{
    last_error = why;
    return false;
}

static uint8_t sc_subaddress(uint8_t channel, uint8_t reg)
{
    return (uint8_t)((reg << 3) | (channel << 1));
}

static bool sc_write_bytes(uint8_t channel, uint8_t reg, const uint8_t *data, size_t size)
{
    if (size > 64u) return fail("SC write too long");
    uint8_t buf[65];
    buf[0] = sc_subaddress(channel, reg);
    memcpy(buf + 1, data, size);
    if (i2c_write_timeout_us(i2c0, BRIDGE_I2C_ADDRESS, buf, size + 1,
                             false, 3000u) != (int)(size + 1u)) {
        return fail("SC I2C write failed");
    }
    return true;
}

static bool sc_read_bytes(uint8_t channel, uint8_t reg, uint8_t *data, size_t size)
{
    uint8_t address = sc_subaddress(channel, reg);
    if (i2c_write_timeout_us(i2c0, BRIDGE_I2C_ADDRESS, &address, 1, true,
                             3000u) != 1) {
        return fail("SC I2C register select failed");
    }
    if (i2c_read_timeout_us(i2c0, BRIDGE_I2C_ADDRESS, data, size, false,
                            3000u) != (int)size) {
        return fail("SC I2C read failed");
    }
    return true;
}

static bool sc_write(uint8_t channel, uint8_t reg, uint8_t value)
{
    return sc_write_bytes(channel, reg, &value, 1);
}

static bool sc_read(uint8_t channel, uint8_t reg, uint8_t *value)
{
    return sc_read_bytes(channel, reg, value, 1);
}

static bool sc_uart_setup(uint8_t channel)
{
    const uint32_t divisor = (BRIDGE_CRYSTAL_HZ + 8u * BRIDGE_UART_BAUD) /
                              (16u * BRIDGE_UART_BAUD);
    if (divisor == 0u || divisor > 65535u) return fail("invalid SC UART divisor");
    if (!sc_write(channel, SC_IER, 0u) ||
        !sc_write(channel, SC_LCR, 0x80u) ||
        !sc_write(channel, SC_DLL, (uint8_t)divisor) ||
        !sc_write(channel, SC_DLH, (uint8_t)(divisor >> 8)) ||
        !sc_write(channel, SC_LCR, 0x03u) ||
        !sc_write(channel, SC_FCR, 0x07u)) {
        return false;
    }
    return true;
}

bool bridge_init(void)
{
    ready = false;
    memset(motor_online, 0, sizeof(motor_online));
    output_state = BRIDGE_GPIO_ENABLE;
    i2c_init(i2c0, 400000u);
    gpio_set_function(BRIDGE_I2C_SDA_PIN, GPIO_FUNC_I2C);
    gpio_set_function(BRIDGE_I2C_SCL_PIN, GPIO_FUNC_I2C);
    gpio_pull_up(BRIDGE_I2C_SDA_PIN);
    gpio_pull_up(BRIDGE_I2C_SCL_PIN);
    gpio_init(BRIDGE_IRQ_PIN);
    gpio_set_dir(BRIDGE_IRQ_PIN, GPIO_IN);
    gpio_pull_up(BRIDGE_IRQ_PIN);

    uint8_t previous_scratch;
    if (!sc_read(0u, SC_SPR, &previous_scratch) ||
        !sc_write(0u, SC_SPR, 0xA5u)) {
        return false;
    }
    uint8_t scratch;
    if (!sc_read(0u, SC_SPR, &scratch) || scratch != 0xA5u ||
        !sc_write(0u, SC_SPR, previous_scratch)) {
        return fail("SC scratch register check failed");
    }

    if (!sc_write(0u, SC_IOINTENA, 0u) ||
        !sc_write(0u, SC_IOCONTROL, 0x01u) ||
        !sc_write(0u, SC_IOSTATE, output_state) ||
        !sc_write(0u, SC_IODIR, 0xF0u) ||
        !sc_write(0u, SC_IOINTENA, BRIDGE_GPIO_LIMIT_Y) ||
        !sc_uart_setup(0u) || !sc_uart_setup(1u)) {
        return false;
    }
    ready = true;
    last_error = "ok";
    return true;
}

bool bridge_ready(void)
{
    return ready;
}

const char *bridge_error(void)
{
    return last_error;
}

static bool update_outputs(uint8_t mask, bool high)
{
    if (!ready) return fail("SC bridge not initialized");
    uint8_t next = high ? (uint8_t)(output_state | mask) :
                          (uint8_t)(output_state & ~mask);
    if (next == output_state) return true;
    if (!sc_write(0u, SC_IOSTATE, next)) return false;
    output_state = next;
    return true;
}

bool bridge_set_enable(bool enabled)
{
    return update_outputs(BRIDGE_GPIO_ENABLE, !enabled);
}

bool bridge_set_direction(unsigned axis, bool level)
{
    if (axis > 2u) return fail("invalid motor axis");
    uint8_t mask = axis == 0u ? BRIDGE_GPIO_DIR_X :
                   axis == 1u ? BRIDGE_GPIO_DIR_Y : BRIDGE_GPIO_DIR_Z;
    return update_outputs(mask, level);
}

bool bridge_gpio_read(uint8_t *state)
{
    return ready && state && sc_read(0u, SC_IOSTATE, state);
}

bool bridge_irq_asserted(void)
{
    return gpio_get(BRIDGE_IRQ_PIN) == 0;
}

static uint8_t tmc_crc(const uint8_t *data, size_t length)
{
    uint8_t crc = 0u;
    for (size_t i = 0; i < length; ++i) {
        uint8_t b = data[i];
        for (unsigned bit = 0; bit < 8u; ++bit) {
            bool carry = ((crc >> 7) ^ b) & 1u;
            crc = (uint8_t)(crc << 1);
            if (carry) crc ^= 0x07u;
            b >>= 1;
        }
    }
    return crc;
}

static bool sc_drain_rx(uint8_t channel)
{
    uint8_t remaining;
    if (!sc_read(channel, SC_RXLVL, &remaining)) return false;
    while (remaining) {
        uint8_t discard;
        if (!sc_read(channel, SC_RHR, &discard)) return false;
        --remaining;
    }
    return true;
}

static bool sc_wait_tx_idle(uint8_t channel)
{
    const uint64_t deadline = time_us_64() + 10000u;
    while (time_us_64() < deadline) {
        uint8_t lsr;
        if (!sc_read(channel, SC_LSR, &lsr)) return false;
        if ((lsr & 0x40u) != 0u) return true;
    }
    return fail("SC UART transmit timeout");
}

static bool sc_transmit(uint8_t channel, const uint8_t *data, size_t len)
{
    if (!sc_drain_rx(channel)) return false;
    uint8_t space;
    if (!sc_read(channel, SC_TXLVL, &space) || space < len) {
        return fail("SC UART transmit FIFO full");
    }
    return sc_write_bytes(channel, SC_THR, data, len) &&
           sc_wait_tx_idle(channel);
}

bool tmc_read(tmc_motor_t motor, uint8_t reg, uint32_t *value)
{
    if (!ready || motor >= TMC_COUNT || !value || reg > 0x7Fu) return false;
    const uint8_t channel = motor_channel[motor];
    const uint8_t address = motor_address[motor];
    uint8_t query[4] = {0x05u, address, reg, 0u};
    query[3] = tmc_crc(query, 3u);
    if (!sc_transmit(channel, query, sizeof(query))) return false;

    uint8_t window[8] = {0};
    size_t used = 0u;
    const uint64_t deadline = time_us_64() + TMC_REPLY_TIMEOUT_US;
    while (time_us_64() < deadline) {
        uint8_t available;
        if (!sc_read(channel, SC_RXLVL, &available)) return false;
        if (!available) {
            tight_loop_contents();
            continue;
        }
        while (available--) {
            uint8_t byte;
            if (!sc_read(channel, SC_RHR, &byte)) return false;
            if (used < sizeof(window)) {
                window[used++] = byte;
            } else {
                memmove(window, window + 1u, sizeof(window) - 1u);
                window[sizeof(window) - 1u] = byte;
            }
            if (used == sizeof(window) && window[0] == 0x05u &&
                window[1] == 0xFFu && window[2] == reg &&
                window[7] == tmc_crc(window, 7u)) {
                *value = ((uint32_t)window[3] << 24) |
                         ((uint32_t)window[4] << 16) |
                         ((uint32_t)window[5] << 8) | window[6];
                sleep_us(150u);
                return true;
            }
        }
    }
    return fail("TMC UART reply timeout or CRC mismatch");
}

bool tmc_write(tmc_motor_t motor, uint8_t reg, uint32_t value)
{
    if (!ready || motor >= TMC_COUNT || reg > 0x7Fu) return false;
    uint8_t packet[8] = {
        0x05u, motor_address[motor], (uint8_t)(reg | 0x80u),
        (uint8_t)(value >> 24), (uint8_t)(value >> 16),
        (uint8_t)(value >> 8), (uint8_t)value, 0u
    };
    packet[7] = tmc_crc(packet, 7u);
    if (!sc_transmit(motor_channel[motor], packet, sizeof(packet))) return false;
    sleep_us(150u);
    return true;
}

bool tmc_configure_8_microsteps(tmc_motor_t motor)
{
    uint32_t ioin, gconf, chopconf, verify;
    if (!tmc_write(motor, TMC_SLAVECONF, 2u << 8) ||
        !tmc_read(motor, TMC_IOIN, &ioin) || (ioin >> 24) != 0x21u ||
        !tmc_read(motor, TMC_GCONF, &gconf) ||
        !tmc_read(motor, TMC_CHOPCONF, &chopconf)) {
        motor_online[motor] = false;
        return fail("TMC driver not responding or unexpected version");
    }
    gconf |= (1u << 6) | (1u << 7);
    chopconf = (chopconf & ~(0xFu << 24)) | (5u << 24);
    if (!tmc_write(motor, TMC_GCONF, gconf) ||
        !tmc_write(motor, TMC_CHOPCONF, chopconf) ||
        !tmc_read(motor, TMC_GCONF, &verify) ||
        (verify & ((1u << 6) | (1u << 7))) != ((1u << 6) | (1u << 7)) ||
        !tmc_read(motor, TMC_CHOPCONF, &verify) ||
        ((verify >> 24) & 0xFu) != 5u) {
        motor_online[motor] = false;
        return fail("TMC configuration write verification failed");
    }
    motor_online[motor] = true;
    last_error = "ok";
    return true;
}

bool tmc_motor_online(tmc_motor_t motor)
{
    return motor < TMC_COUNT && motor_online[motor];
}

bool tmc_all_online(void)
{
    for (unsigned i = 0; i < TMC_COUNT; ++i) {
        if (!motor_online[i]) return false;
    }
    return true;
}

const char *tmc_motor_name(tmc_motor_t motor)
{
    return motor < TMC_COUNT ? motor_names[motor] : "invalid";
}

bool tmc_motor_from_name(const char *name, tmc_motor_t *motor)
{
    if (!name || !motor) return false;
    for (unsigned i = 0; i < TMC_COUNT; ++i) {
        if (strcmp(name, motor_names[i]) == 0) {
            *motor = (tmc_motor_t)i;
            return true;
        }
    }
    return false;
}
