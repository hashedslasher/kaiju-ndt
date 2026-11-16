#include "bridge.h"
#include "gantry_units.h"

#include <stdio.h>
#include <string.h>

#include "hardware/gpio.h"
#include "pico/stdlib.h"
#include "sc16is750.h"
#include "trinamic.h"

#define TMC_GCONF 0x00u
#define TMC_SLAVECONF 0x03u
#define TMC_IOIN 0x06u
#define TMC_CHOPCONF 0x6Cu

static const uint8_t motor_address[TMC_COUNT] = {0, 1, 2, 0, 2};
static const char *const motor_names[TMC_COUNT] = {"x1", "x2", "y1", "y2", "z"};
static TMC2209_t drivers[TMC_COUNT];
static SC16IS750_t serial_bridge;
static bool motor_online[TMC_COUNT];
static bool ready;
static uint8_t output_state = BRIDGE_GPIO_ENABLE;
#define MOTOR_GPIO_DIR 0xF0u
static char last_error[160] = "uninitialized";

static bool fail(const char *reason)
{
    snprintf(last_error, sizeof(last_error), "%s", reason);
    return false;
}

static bool fail_sc(const char *operation)
{
    snprintf(last_error, sizeof(last_error), "%s phase=%s reg=0x%02X ch=%u sel=0x%02X I2C=%d", operation,
             serial_bridge.last_phase ? serial_bridge.last_phase : "setup",
             serial_bridge.last_selector >> 3, (serial_bridge.last_selector >> 1) & 1u,
             serial_bridge.last_selector, serial_bridge.last_error);
    ready = false;
    memset(motor_online, 0, sizeof(motor_online));
    return false;
}

static bool sc_write(uint8_t channel, uint8_t reg, uint8_t value)
{
    if (!SC16IS750_WriteRegisterChecked(&serial_bridge, channel, reg, value))
        return fail_sc("SC I2C write failed");
    return true;
}

static bool sc_read(uint8_t channel, uint8_t reg, uint8_t *value)
{
    if (!SC16IS750_ReadRegisterChecked(&serial_bridge, channel, reg, value))
        return fail_sc("SC I2C register read failed");
    return true;
}

bool bridge_init(void)
{
    ready = false;
    memset(motor_online, 0, sizeof(motor_online));
    output_state = BRIDGE_GPIO_ENABLE;
    gpio_init(BRIDGE_IRQ_PIN);
    gpio_set_dir(BRIDGE_IRQ_PIN, GPIO_IN);
    gpio_pull_up(BRIDGE_IRQ_PIN);

    SC16IS750_init(&serial_bridge, SC16IS750_PROTOCOL_I2C,
                   BRIDGE_I2C_ADDRESS, SC16IS750_DUAL_CHANNEL);
    SC16IS750_begin(&serial_bridge, BRIDGE_UART_BAUD, BRIDGE_UART_BAUD,
                    BRIDGE_CRYSTAL_HZ);
    if (serial_bridge.last_error)
        return fail_sc("SC initialization failed");

    if (!sc_write(SC16IS750_CHANNEL_A, SC16IS750_REG_IOINTENA, 0) ||
        !sc_write(SC16IS750_CHANNEL_A, SC16IS750_REG_IOCONTROL, 0x00u) ||
        !sc_write(SC16IS750_CHANNEL_A, SC16IS750_REG_IOSTATE, output_state) ||
        !sc_write(SC16IS750_CHANNEL_A, SC16IS750_REG_IODIR, MOTOR_GPIO_DIR) ||
        !sc_write(SC16IS750_CHANNEL_A, SC16IS750_REG_IOINTENA, BRIDGE_GPIO_LIMIT_Y))
        return false;

    tmc_uart_init(&serial_bridge);
    for (unsigned i = 0; i < TMC_COUNT; ++i) {
        TMC2209_SetDefaults(&drivers[i]);
        drivers[i].config.motor.id = i;
        drivers[i].config.motor.axis = i == TMC_Z ? 2u : i >= TMC_Y1 ? 1u : 0u;
        drivers[i].config.motor.address = motor_address[i];
        drivers[i].config.microsteps = GANTRY_MICROSTEPS;
    }
    ready = true;
    snprintf(last_error, sizeof(last_error), "ok");
    return true;
}

bool bridge_setup_motors(void)
{
    if (!bridge_init()) return false;
    for (unsigned i = TMC_X1; i < TMC_COUNT; ++i) {
        if (!tmc_configure_8_microsteps((tmc_motor_t)i)) return false;
    }
    return ready && tmc_all_online();
}

bool bridge_i2c_test(uint8_t *iocontrol, uint32_t *hz)
{
    if (!SC16IS750_Probe(&serial_bridge, iocontrol)) {
        *hz = serial_bridge.actual_hz;
        return fail_sc("SC probe failed");
    }
    *hz = serial_bridge.actual_hz;
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
    if (!sc_write(SC16IS750_CHANNEL_A, SC16IS750_REG_IOSTATE, next)) return false;
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
    const uint8_t mask = axis == 0u ? BRIDGE_GPIO_DIR_X :
                         axis == 1u ? BRIDGE_GPIO_DIR_Y : BRIDGE_GPIO_DIR_Z;
    return update_outputs(mask, level);
}

bool bridge_gpio_read(uint8_t *state)
{
    return ready && state && sc_read(SC16IS750_CHANNEL_A, SC16IS750_REG_IOSTATE, state);
}

bool bridge_irq_asserted(void)
{
    return !gpio_get(BRIDGE_IRQ_PIN);
}

bool tmc_read(tmc_motor_t motor, uint8_t reg, uint32_t *value)
{
    if (!ready || motor >= TMC_COUNT || !value || reg > 0x7Fu)
        return fail("invalid TMC read request");
    TMC2209_datagram_t descriptor = {0};
    descriptor.addr.value = reg;
    if (!TMC2209_ReadRegister(&drivers[motor], &descriptor)) {
        if (!tmc_uart_last_ok()) {
            if (serial_bridge.last_error) return fail_sc(tmc_uart_last_error());
            return fail(tmc_uart_last_error());
        }
        return fail("TMC reply CRC/format invalid");
    }
    *value = descriptor.payload.value;
    return true;
}

bool tmc_write(tmc_motor_t motor, uint8_t reg, uint32_t value)
{
    if (!ready || motor >= TMC_COUNT || reg > 0x7Fu)
        return fail("invalid TMC write request");
    TMC2209_datagram_t descriptor = {0};
    descriptor.addr.value = reg;
    descriptor.payload.value = value;
    if (!TMC2209_WriteRegister(&drivers[motor], &descriptor) ||
        !tmc_uart_last_ok()) {
        if (serial_bridge.last_error) return fail_sc(tmc_uart_last_error());
        return fail(tmc_uart_last_error());
    }
    return true;
}

bool tmc_configure_8_microsteps(tmc_motor_t motor)
{
    if (motor >= TMC_COUNT || !ready) return fail("SC bridge offline");
    motor_online[motor] = false;
    uint32_t ioin, gconf, chopconf, verify;
    if (!tmc_write(motor, TMC_SLAVECONF, 2u << 8)) return false;
    if (!tmc_read(motor, TMC_IOIN, &ioin)) return false;
    if ((ioin >> 24) != 0x21u) return fail("TMC IOIN unexpected version");
    if (!tmc_read(motor, TMC_GCONF, &gconf) ||
        !tmc_read(motor, TMC_CHOPCONF, &chopconf)) return false;
    gconf |= (1u << 6) | (1u << 7);
    chopconf = (chopconf & ~((0xFu << 24) | (1u << 29))) | (GANTRY_MRES << 24);
    if (!tmc_write(motor, TMC_GCONF, gconf) ||
        !tmc_write(motor, TMC_CHOPCONF, chopconf) ||
        !tmc_read(motor, TMC_GCONF, &verify)) return false;
    if ((verify & ((1u << 6) | (1u << 7))) != ((1u << 6) | (1u << 7)))
        return fail("TMC GCONF verification failed");
    if (!tmc_read(motor, TMC_CHOPCONF, &verify)) return false;
    if (((verify >> 24) & 0xFu) != GANTRY_MRES || (verify & (1u << 29)))
        return fail("TMC microstep verification failed");
    motor_online[motor] = true;
    snprintf(last_error, sizeof(last_error), "ok");
    return true;
}

bool tmc_motor_online(tmc_motor_t motor)
{
    return motor < TMC_COUNT && motor_online[motor];
}

bool tmc_all_online(void)
{
    for (unsigned i = 0; i < TMC_COUNT; ++i)
        if (!motor_online[i]) return false;
    return true;
}

bool tmc_xy_online(void)
{
    return motor_online[TMC_X1] && motor_online[TMC_X2] &&
           motor_online[TMC_Y1] && motor_online[TMC_Y2];
}

bool tmc_motion_ready(unsigned axis)
{
    return axis < 3u && ready && tmc_all_online();
}

const char *tmc_motor_name(tmc_motor_t motor)
{
    return motor < TMC_COUNT ? motor_names[motor] : "invalid";
}

bool tmc_motor_from_name(const char *name, tmc_motor_t *motor)
{
    if (!name || !motor) return false;
    for (unsigned i = 0; i < TMC_COUNT; ++i)
        if (strcmp(name, motor_names[i]) == 0) {
            *motor = (tmc_motor_t)i;
            return true;
        }
    return false;
}
