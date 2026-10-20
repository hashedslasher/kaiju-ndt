#include "positioning.h"

#include "motors.h"
#include "hardware/gpio.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

static volatile int32_t position_steps[3] = {0, 0, 0};
static volatile bool position_exact[3] = {false, false, false};
static volatile bool position_homed[3] = {false, false, false};
static volatile bool position_homing[3] = {false, false, false};

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
    if (axis == POSITION_AXIS_Y) return switch_pressed(LIMIT_PIN_Y);
    return false;
}

bool positioning_limit_blocked(position_axis_t axis, bool dir_bit)
{
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
    if (axis > POSITION_AXIS_Z || positioning_limit_blocked(axis, dir_bit)) {
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
    } else if (gpio == LIMIT_PIN_Y && switch_pressed(LIMIT_PIN_Y)) {
        if (motor_stop_if_direction(POSITION_AXIS_Y, Y_DIR_TOWARD_ZERO)) {
            positioning_set_zero(POSITION_AXIS_Y);
        }
    }
}

void positioning_init(void)
{
    gpio_init(LIMIT_PIN_X);
    gpio_init(LIMIT_PIN_Y);
    gpio_set_dir(LIMIT_PIN_X, GPIO_IN);
    gpio_set_dir(LIMIT_PIN_Y, GPIO_IN);
    gpio_pull_up(LIMIT_PIN_X);
    gpio_pull_up(LIMIT_PIN_Y);
    gpio_set_irq_enabled_with_callback(
        LIMIT_PIN_X, GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE,
        true, limit_callback);
    gpio_set_irq_enabled(
        LIMIT_PIN_Y, GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE, true);

    if (switch_pressed(LIMIT_PIN_X)) positioning_set_zero(POSITION_AXIS_X);
    if (switch_pressed(LIMIT_PIN_Y)) positioning_set_zero(POSITION_AXIS_Y);
}
