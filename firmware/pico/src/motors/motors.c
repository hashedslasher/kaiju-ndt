#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "string.h"
#include "stdio.h"
#include "motors.pio.h"
#include "motors.h"

#define STEP_PIN_X  18
#define DIR_PIN_X   19
#define STEP_PIN_Y  20
#define DIR_PIN_Y   21
#define STEP_PIN_Z  22
#define DIR_PIN_Z   26
#define EN_PIN      28

#define MAX_STEPS       5000
#define START_FREQ_HZ   100
#define MAX_RAMP_STEPS  100

uint32_t step_profile_x[MAX_STEPS];
uint32_t step_profile_y[MAX_STEPS];
uint32_t step_profile_z[MAX_STEPS];

int dma_chan_x = -1;
int dma_chan_y = -1;
int dma_chan_z = -1;

PIO motor_pio = pio1;
uint motor_pio_offset;

typedef struct {
    PIO pio;
    uint sm;
    int dma_chan;
    uint32_t *profile;
    uint step_pin;
    uint dir_pin;
    bool active;
    bool needs_ramp;
    bool dir_bit;
    uint32_t target_freq_hz;
} motor_axis_t;

static motor_axis_t axis_x;
static motor_axis_t axis_y;
static motor_axis_t axis_z;

static inline uint32_t pack_step_word(bool dir_bit, uint32_t delay)
{
    if (delay > 0x7FFFFFFFu) {
        delay = 0x7FFFFFFFu;
    }
    return (delay << 1) | (dir_bit ? 1u : 0u);
}

static inline uint32_t freq_to_delay(uint32_t freq_hz)
{
    uint32_t sys_clk = clock_get_hz(clk_sys);
    if (freq_hz == 0) {
        return 0x7FFFFFFFu;
    }

    uint32_t delay = (sys_clk / freq_hz);
    if (delay > 32) {
        delay -= 32;
    } else {
        delay = 0;
    }
    return delay;
}

void init_motor_sm(PIO pio, uint sm, uint offset, uint step_pin, uint dir_pin)
{
    pio_gpio_init(pio, step_pin);
    pio_gpio_init(pio, dir_pin);

    pio_sm_set_consecutive_pindirs(pio, sm, step_pin, 1, true);
    pio_sm_set_consecutive_pindirs(pio, sm, dir_pin, 1, true);

    pio_sm_config c = stepper_ctrl_program_get_default_config(offset);
    sm_config_set_set_pins(&c, step_pin, 1);
    sm_config_set_out_pins(&c, dir_pin, 1);
    sm_config_set_out_shift(&c, true, false, 32);

    pio_sm_init(pio, sm, offset, &c);
    pio_sm_set_enabled(pio, sm, true);
}

static void stop_axis_now(motor_axis_t *axis)
{
    axis->active = false;
    axis->needs_ramp = false;

    pio_sm_set_enabled(axis->pio, axis->sm, false);
    if (dma_channel_is_busy(axis->dma_chan)) {
        dma_channel_abort(axis->dma_chan);
    }

    pio_sm_clear_fifos(axis->pio, axis->sm);
    pio_sm_restart(axis->pio, axis->sm);

    pio_sm_exec(axis->pio, axis->sm, pio_encode_set(pio_pins, 0));
    pio_sm_exec(axis->pio, axis->sm, pio_encode_jmp(motor_pio_offset));
    pio_sm_set_enabled(axis->pio, axis->sm, true);
}

void start_dma(PIO pio, uint sm, int dma_chan, uint32_t* profile, uint32_t steps)
{
    dma_channel_config c = dma_channel_get_default_config(dma_chan);
    channel_config_set_transfer_data_size(&c, DMA_SIZE_32);
    channel_config_set_read_increment(&c, true);
    channel_config_set_write_increment(&c, false);
    channel_config_set_dreq(&c, pio_get_dreq(pio, sm, true));

    dma_channel_configure(
        dma_chan,
        &c,
        &pio->txf[sm],
        profile,
        steps,
        true
    );
}

static void build_cruise_profile(uint32_t *profile, bool dir_bit, uint32_t freq_hz)
{
    const uint32_t delay = freq_to_delay(freq_hz);
    for (uint32_t i = 0; i < MAX_STEPS; ++i) {
        profile[i] = pack_step_word(dir_bit, delay);
    }
}

static void build_ramp_profile(uint32_t *profile,
                               bool dir_bit,
                               uint32_t target_freq_hz)
{
    uint32_t ramp_steps = MAX_RAMP_STEPS;
    uint32_t start_freq = START_FREQ_HZ;

    if (target_freq_hz <= start_freq) {
        start_freq = target_freq_hz;
        ramp_steps = 0;
    }

    const uint32_t target_delay = freq_to_delay(target_freq_hz);

    for (uint32_t i = 0; i < MAX_STEPS; ++i) {
        uint32_t current_freq = target_freq_hz;

        if (i < ramp_steps) {
            current_freq = start_freq +
                           (uint32_t)(((uint64_t)(target_freq_hz - start_freq) * i) /
                                      ramp_steps);
        }

        uint32_t delay = (i < ramp_steps) ? freq_to_delay(current_freq) : target_delay;
        profile[i] = pack_step_word(dir_bit, delay);
    }
}

static void start_axis_block(motor_axis_t *axis)
{
    if (axis->needs_ramp) {
        build_ramp_profile(axis->profile, axis->dir_bit, axis->target_freq_hz);
        axis->needs_ramp = false;
    } else {
        build_cruise_profile(axis->profile, axis->dir_bit, axis->target_freq_hz);
    }

    start_dma(axis->pio, axis->sm, axis->dma_chan, axis->profile, MAX_STEPS);
}

static void jog_axis(motor_axis_t *axis, bool dir_bit, uint32_t freq_hz)
{
    if (freq_hz == 0) {
        return;
    }

    if (axis->active &&
        axis->dir_bit == dir_bit &&
        axis->target_freq_hz == freq_hz) {
        return;
    }

    stop_axis_now(axis);

    axis->dir_bit = dir_bit;
    axis->target_freq_hz = freq_hz;
    axis->active = true;
    axis->needs_ramp = true;

    start_axis_block(axis);
}

static void service_axis(motor_axis_t *axis)
{
    if (!axis->active) {
        return;
    }

    if (!dma_channel_is_busy(axis->dma_chan)) {
        start_axis_block(axis);
    }
}

void motor_service(void)
{
    service_axis(&axis_x);
    service_axis(&axis_y);
    service_axis(&axis_z);
}

void stop_x(const char *args)
{
    (void)args;
    stop_axis_now(&axis_x);
}

void stop_y(const char *args)
{
    (void)args;
    stop_axis_now(&axis_y);
}

void stop_z(const char *args)
{
    (void)args;
    stop_axis_now(&axis_z);
}

void jog_x(const char *args)
{
    char dir_str[16];
    uint32_t freq_hz = 0;

    if (sscanf(args, "%15s %lu", dir_str, &freq_hz) != 2) {
        return;
    }

    if (strcmp(dir_str, "plus") == 0) {
        jog_axis(&axis_x, true, freq_hz);
    } else if (strcmp(dir_str, "minus") == 0) {
        jog_axis(&axis_x, false, freq_hz);
    }
}

void jog_y(const char *args)
{
    char dir_str[16];
    uint32_t freq_hz = 0;

    if (sscanf(args, "%15s %lu", dir_str, &freq_hz) != 2) {
        return;
    }

    if (strcmp(dir_str, "plus") == 0) {
        jog_axis(&axis_y, true, freq_hz);
    } else if (strcmp(dir_str, "minus") == 0) {
        jog_axis(&axis_y, false, freq_hz);
    }
}

void jog_z(const char *args)
{
    char dir_str[16];
    uint32_t freq_hz = 0;

    if (sscanf(args, "%15s %lu", dir_str, &freq_hz) != 2) {
        return;
    }

    if (strcmp(dir_str, "up") == 0) {
        jog_axis(&axis_z, true, freq_hz);
    } else if (strcmp(dir_str, "down") == 0) {
        jog_axis(&axis_z, false, freq_hz);
    }
}

static void finite_move(motor_axis_t *axis,
                        uint32_t *profile,
                        const char *args,
                        bool allow_up_down)
{
    char dir_str[16];
    uint32_t freq_hz = 0;
    uint32_t steps = 0;

    if (sscanf(args, "%15s %lu %lu", dir_str, &freq_hz, &steps) != 3) {
        return;
    }

    if (steps == 0 || freq_hz == 0) {
        return;
    }
    if (steps > MAX_STEPS) {
        steps = MAX_STEPS;
    }

    bool dir_bit;
    if (strcmp(dir_str, "plus") == 0) {
        dir_bit = true;
    } else if (strcmp(dir_str, "minus") == 0) {
        dir_bit = false;
    } else if (allow_up_down && strcmp(dir_str, "up") == 0) {
        dir_bit = true;
    } else if (allow_up_down && strcmp(dir_str, "down") == 0) {
        dir_bit = false;
    } else {
        return;
    }

    stop_axis_now(axis);
    ramp_profile(profile, dir_bit, freq_hz, steps);
    start_dma(axis->pio, axis->sm, axis->dma_chan, profile, steps);
}

void move_x(const char *args)
{
    finite_move(&axis_x, step_profile_x, args, false);
}

void move_y(const char *args)
{
    finite_move(&axis_y, step_profile_y, args, false);
}

void move_z(const char *args)
{
    finite_move(&axis_z, step_profile_z, args, true);
}

void motor_setup(void)
{
    gpio_init(EN_PIN);
    gpio_set_dir(EN_PIN, GPIO_OUT);
    gpio_put(EN_PIN, 0);

    motor_pio_offset = pio_add_program(motor_pio, &stepper_ctrl_program);

    init_motor_sm(motor_pio, 0, motor_pio_offset, STEP_PIN_X, DIR_PIN_X);
    init_motor_sm(motor_pio, 1, motor_pio_offset, STEP_PIN_Y, DIR_PIN_Y);
    init_motor_sm(motor_pio, 2, motor_pio_offset, STEP_PIN_Z, DIR_PIN_Z);

    dma_chan_x = dma_claim_unused_channel(true);
    dma_chan_y = dma_claim_unused_channel(true);
    dma_chan_z = dma_claim_unused_channel(true);

    axis_x = (motor_axis_t){motor_pio, 0, dma_chan_x, step_profile_x,
                            STEP_PIN_X, DIR_PIN_X, false, false, false, 0};
    axis_y = (motor_axis_t){motor_pio, 1, dma_chan_y, step_profile_y,
                            STEP_PIN_Y, DIR_PIN_Y, false, false, false, 0};
    axis_z = (motor_axis_t){motor_pio, 2, dma_chan_z, step_profile_z,
                            STEP_PIN_Z, DIR_PIN_Z, false, false, false, 0};
}

void ramp_profile(uint32_t* profile_array,
                  bool dir_bit,
                  uint32_t target_freq_hz,
                  uint32_t steps)
{
    uint32_t ramp_steps = MAX_RAMP_STEPS;
    uint32_t start_freq = START_FREQ_HZ;

    if (steps < (MAX_RAMP_STEPS * 2)) {
        ramp_steps = steps / 2;
    }

    if (target_freq_hz <= start_freq) {
        start_freq = target_freq_hz;
        ramp_steps = 0;
    }

    for (uint32_t i = 0; i < steps; ++i) {
        uint32_t current_freq = target_freq_hz;

        if (i < ramp_steps) {
            current_freq = start_freq +
                           (uint32_t)(((uint64_t)(target_freq_hz - start_freq) * i) /
                                      ramp_steps);
        } else if (i >= steps - ramp_steps) {
            uint32_t decel_step = steps - i;
            current_freq = start_freq +
                           (uint32_t)(((uint64_t)(target_freq_hz - start_freq) * decel_step) /
                                      ramp_steps);
        }

        profile_array[i] = pack_step_word(dir_bit, freq_to_delay(current_freq));
    }
}
