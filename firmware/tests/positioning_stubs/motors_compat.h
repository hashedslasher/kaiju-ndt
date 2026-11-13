#ifndef MOTORS_H
#define MOTORS_H
#include <stdbool.h>
#include <stdint.h>
#include "positioning.h"
#define LIMIT_PIN_X 26u
bool motor_stop_if_direction(position_axis_t id, bool positive);
bool motor_any_active(void);
void stop_y(const char *args);
int32_t motor_inflight_step_delta(position_axis_t axis, bool *exact);
#endif
