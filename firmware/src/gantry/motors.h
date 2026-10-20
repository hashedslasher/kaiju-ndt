#ifndef MOTORS_H
#define MOTORS_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>
#include <stdbool.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "positioning.h"

#define STEP_PIN_X    18
#define DIR_PIN_X     19
#define STEP_PIN_Y    20
#define DIR_PIN_Y     21
#define STEP_PIN_Z    22
#define DIR_PIN_Z     26
#define LIMIT_PIN_X   27
#define LIMIT_PIN_Y   28

#define MAX_STEPS       5000
#define START_FREQ_HZ   100
#define MAX_RAMP_STEPS  100
#define MAX_MOTOR_FREQ_HZ 50000u

extern uint32_t step_profile_x[MAX_STEPS];
extern uint32_t step_profile_y[MAX_STEPS];
extern uint32_t step_profile_z[MAX_STEPS];

extern int dma_chan_x;
extern int dma_chan_y;
extern int dma_chan_z;

extern PIO motor_pio;
extern uint motor_pio_offset;

void motor_setup(void);
void motor_service(void);
bool motor_home_xy(void);
bool motor_is_homing_xy(void);
const char *motor_home_status(void);

bool move_x(const char *args);
bool move_y(const char *args);
bool move_z(const char *args);

bool jog_x(const char *args);
bool jog_y(const char *args);
bool jog_z(const char *args);

void stop_x(const char *args);
void stop_y(const char *args);
void stop_z(const char *args);
void motor_stop_all(void);
bool motor_stop_if_direction(position_axis_t axis, bool positive);
bool motor_any_active(void);
int32_t motor_inflight_step_delta(position_axis_t axis, bool *exact);

void init_motor_sm(PIO pio, uint sm, uint offset, uint step_pin, uint dir_pin);
void start_dma(PIO pio, uint sm, int dma_chan, uint32_t* profile, uint32_t steps);
void ramp_profile(uint32_t* profile_array, bool dir_bit, uint32_t target_freq_hz, uint32_t steps);

#ifdef __cplusplus
}
#endif

#endif // MOTORS_H
