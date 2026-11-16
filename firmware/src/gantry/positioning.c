#include "positioning.h"
#include <stddef.h>

#include "motors.h"
#include "bridge.h"
#include "hardware/gpio.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

static volatile int32_t position_steps[3] = {0, 0, 0};
static volatile bool position_exact[3] = {false, false, false};
static volatile bool position_homed[3] = {false, false, false};
static volatile bool position_homing[3] = {false, false, false};
static bool limit_y_valid;
static bool limit_y_active;
static uint64_t last_limit_y_poll_us;

static const int32_t min_position[3] = {
    X_MIN_POSITION_STEPS, Y_MIN_POSITION_STEPS, Z_MIN_POSITION_STEPS
};
static const int32_t max_position[3] = {
    X_MAX_POSITION_STEPS, Y_MAX_POSITION_STEPS, Z_MAX_POSITION_STEPS
};

static bool switch_pressed(uint gpio)
{
#if LIMIT_SWITCH_ACTIVE_LOW
    return gpio_get(gpio) == 0;
#else
    return gpio_get(gpio) != 0;
#endif
}

bool positioning_toward_zero_dir(position_axis_t axis)
{
    return axis == POSITION_AXIS_Y ? Y_DIR_TOWARD_ZERO : X_DIR_TOWARD_ZERO;
}

bool positioning_dir_increases_coord(position_axis_t axis, bool dir_bit)
{
    if (axis == POSITION_AXIS_X || axis == POSITION_AXIS_Y) {
        return dir_bit != positioning_toward_zero_dir(axis);
    }
    return dir_bit;
}

bool positioning_dir_for_coordinate(position_axis_t axis, bool positive)
{
    if (axis == POSITION_AXIS_X || axis == POSITION_AXIS_Y) {
        return positive != positioning_toward_zero_dir(axis);
    }
    return positive;
}

bool positioning_switch_active(position_axis_t axis)
{
    if (axis == POSITION_AXIS_X) return switch_pressed(LIMIT_PIN_X);
    if (axis == POSITION_AXIS_Y) return limit_y_valid && limit_y_active;
    return false;
}

bool positioning_limit_blocked(position_axis_t axis, bool dir_bit)
{
    if (axis == POSITION_AXIS_Y && !limit_y_valid) return true;
    return (axis == POSITION_AXIS_X || axis == POSITION_AXIS_Y) &&
           dir_bit == positioning_toward_zero_dir(axis) &&
           positioning_switch_active(axis);
}

void positioning_begin_homing(position_axis_t axis)
{
    if (axis != POSITION_AXIS_X && axis != POSITION_AXIS_Y) return;
    const uint32_t saved = save_and_disable_interrupts();
    position_steps[axis] = 0;
    position_exact[axis] = true;
    position_homed[axis] = false;
    position_homing[axis] = true;
    restore_interrupts(saved);
}

void positioning_cancel_homing(position_axis_t axis)
{
    if (axis != POSITION_AXIS_X && axis != POSITION_AXIS_Y) return;
    position_homing[axis] = false;
}

uint32_t positioning_steps_available(position_axis_t axis, bool dir_bit)
{
    if (axis > POSITION_AXIS_Z ||
        (axis == POSITION_AXIS_Y && !limit_y_valid) ||
        positioning_limit_blocked(axis, dir_bit)) {
        return 0;
    }
    const bool increasing = positioning_dir_increases_coord(axis, dir_bit);
    if (!position_homed[axis]) {
        if (axis == POSITION_AXIS_Z) return UINT32_MAX;
        if (!position_homing[axis] || increasing) return 0;
        const int64_t searched = -(int64_t)position_steps[axis];
        if (searched >= HOME_SEARCH_MAX_STEPS) return 0;
        return (uint32_t)((int64_t)HOME_SEARCH_MAX_STEPS - searched);
    }
    const int32_t pos = position_steps[axis];
    int64_t room = increasing ?
        (int64_t)max_position[axis] - pos :
        (int64_t)pos - min_position[axis];
    if (!position_exact[axis]) {
        room -= POSITION_UNCERTAINTY_STEPS;
    }
    return room > 0 ? (uint32_t)room : 0u;
}

uint32_t positioning_manual_jog_steps_available(position_axis_t axis, bool dir_bit)
{
    if (axis == POSITION_AXIS_Y && !limit_y_valid) return 0u;
    if (axis > POSITION_AXIS_Y || position_homed[axis]) {
        return positioning_steps_available(axis, dir_bit);
    }
    if (position_homing[axis] || positioning_limit_blocked(axis, dir_bit)) {
        return 0u;
    }
    const int64_t pos = position_steps[axis];
    const int64_t room = positioning_dir_increases_coord(axis, dir_bit) ?
        (int64_t)UNHOMED_JOG_RANGE_STEPS - pos :
        (int64_t)UNHOMED_JOG_RANGE_STEPS + pos;
    return room > 0 ? (uint32_t)room : 0u;
}

void positioning_add_steps(position_axis_t axis, bool dir_bit,
                           uint32_t steps, bool exact)
{
    if (axis > POSITION_AXIS_Z) return;
    const bool increasing = positioning_dir_increases_coord(axis, dir_bit);
    position_steps[axis] += increasing ? (int32_t)steps : -(int32_t)steps;
    if (!exact) position_exact[axis] = false;
}

int32_t positioning_get_steps(position_axis_t axis)
{
    if (axis > POSITION_AXIS_Z) {
        return 0;
    }
    const uint32_t saved = save_and_disable_interrupts();
    const int32_t base = position_steps[axis];
    bool inflight_exact;
    const int32_t inflight = motor_inflight_step_delta(axis, &inflight_exact);
    restore_interrupts(saved);
    return base + inflight;
}

bool positioning_is_exact(position_axis_t axis)
{
    if (axis > POSITION_AXIS_Z || !position_exact[axis]) {
        return false;
    }
    bool inflight_exact;
    (void)motor_inflight_step_delta(axis, &inflight_exact);
    return inflight_exact;
}

bool positioning_is_homed(position_axis_t axis)
{
    return axis <= POSITION_AXIS_Z && position_homed[axis];
}

void positioning_set_zero(position_axis_t axis)
{
    if (axis > POSITION_AXIS_Z) {
        return;
    }
    const uint32_t saved = save_and_disable_interrupts();
    position_steps[axis] = 0;
    position_exact[axis] = true;
    position_homed[axis] = true;
    position_homing[axis] = false;
    restore_interrupts(saved);
}

static void limit_callback(uint gpio, uint32_t events)
{
    (void)events;
    if (gpio == LIMIT_PIN_X && switch_pressed(LIMIT_PIN_X)) {
        if (motor_stop_if_direction(POSITION_AXIS_X, X_DIR_TOWARD_ZERO)) {
            positioning_set_zero(POSITION_AXIS_X);
        }
    }
}

static bool refresh_y_limit(void)
{
    uint8_t state;
    last_limit_y_poll_us = time_us_64();
    if (!bridge_gpio_read(&state)) {
        limit_y_valid = false;
        if (motor_any_active() || motor_is_homing_xy()) motor_stop_all();
        return false;
    }
    limit_y_active = LIMIT_SWITCH_ACTIVE_LOW ?
        (state & BRIDGE_GPIO_LIMIT_Y) == 0u :
        (state & BRIDGE_GPIO_LIMIT_Y) != 0u;
    limit_y_valid = true;
    if (limit_y_active && motor_stop_if_direction(POSITION_AXIS_Y, Y_DIR_TOWARD_ZERO)) {
        positioning_set_zero(POSITION_AXIS_Y);
    }
    return true;
}

bool positioning_limit_y_ready(void)
{
    return refresh_y_limit();
}

void positioning_service(void)
{
    const uint64_t now = time_us_64();
    const uint32_t interval_us = motor_any_active() ? 1000u : 20000u;
    if (!bridge_ready()) {
        limit_y_valid = false;
        if (motor_any_active() || motor_is_homing_xy()) motor_stop_all();
        return;
    }
    if (limit_y_valid && now - last_limit_y_poll_us < interval_us &&
        (!bridge_irq_asserted() || now - last_limit_y_poll_us < 250u)) return;
    (void)refresh_y_limit();
}

void positioning_init(void)
{
    limit_y_valid = false;
    gpio_init(LIMIT_PIN_X);
    gpio_set_dir(LIMIT_PIN_X, GPIO_IN);
    gpio_pull_up(LIMIT_PIN_X);
    gpio_set_irq_enabled_with_callback(
        LIMIT_PIN_X, GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE,
        true, limit_callback);
    positioning_service();
}
