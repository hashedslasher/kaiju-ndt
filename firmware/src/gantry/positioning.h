#ifndef GANTRY_POSITIONING_H
#define GANTRY_POSITIONING_H

#include <stdbool.h>
#include <stdint.h>

#define X_MIN_POSITION_STEPS   0
#define X_MAX_POSITION_STEPS   21000
#define Y_MIN_POSITION_STEPS   0
#define Y_MAX_POSITION_STEPS   11000
#define Z_MIN_POSITION_STEPS   0
#define Z_MAX_POSITION_STEPS   5000

#define X_DIR_TOWARD_ZERO  false
#define Y_DIR_TOWARD_ZERO  true
#define LIMIT_SWITCH_ACTIVE_LOW 1

#define AUTO_HOME_XY_ON_STARTUP 1
#define HOME_SPEED_HZ 2000u
#define HOME_SEARCH_MAX_STEPS 26000u
#define HOME_AXIS_TIMEOUT_MS 90000u

#define POSITION_UNCERTAINTY_STEPS 8

typedef enum {
    POSITION_AXIS_X = 0,
    POSITION_AXIS_Y = 1,
    POSITION_AXIS_Z = 2
} position_axis_t;

void positioning_init(void);
bool positioning_toward_zero_dir(position_axis_t axis);
bool positioning_dir_increases_coord(position_axis_t axis, bool dir_bit);
bool positioning_dir_for_coordinate(position_axis_t axis, bool positive);
bool positioning_switch_active(position_axis_t axis);
void positioning_begin_homing(position_axis_t axis);
void positioning_cancel_homing(position_axis_t axis);
bool positioning_limit_blocked(position_axis_t axis, bool dir_bit);
uint32_t positioning_steps_available(position_axis_t axis, bool dir_bit);
void positioning_add_steps(position_axis_t axis, bool dir_bit,
                           uint32_t steps, bool exact);
int32_t positioning_get_steps(position_axis_t axis);
bool positioning_is_exact(position_axis_t axis);
bool positioning_is_homed(position_axis_t axis);
void positioning_set_zero(position_axis_t axis);

#endif
