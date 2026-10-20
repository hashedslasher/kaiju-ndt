#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/sync.h"
#include <string.h>
#include <stdio.h>
#include <inttypes.h>
#include "motors.pio.h"
#include "motors.h"

uint32_t step_profile_x[MAX_STEPS];
uint32_t step_profile_y[MAX_STEPS];
uint32_t step_profile_z[MAX_STEPS];

int dma_chan_x = -1;
int dma_chan_y = -1;
int dma_chan_z = -1;

PIO motor_pio = pio2;
uint motor_pio_offset;

typedef struct {
    PIO pio;
    uint sm;
    int dma_chan;
    uint32_t *profile;
    uint step_pin;
    uint dir_pin;
    bool active;
    bool continuous;
    bool needs_ramp;
    uint32_t planned_steps;
    position_axis_t id;
    bool dir_bit;
    uint32_t target_freq_hz;
} motor_axis_t;

static motor_axis_t axis_x;
static motor_axis_t axis_y;
static motor_axis_t axis_z;

typedef enum {
    HOME_IDLE = 0, HOME_X, HOME_Y, HOME_COMPLETE, HOME_FAILED
} home_state_t;
static home_state_t home_state = HOME_IDLE;
static uint32_t home_stage_start_ms;

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

static bool axis_block_drained(const motor_axis_t *axis)
{
    return !dma_channel_is_busy(axis->dma_chan) &&
           pio_sm_is_tx_fifo_empty(axis->pio, axis->sm) &&
           pio_sm_get_pc(axis->pio, axis->sm) == motor_pio_offset;
}

static uint32_t axis_executed_steps(const motor_axis_t *axis, bool *exact)
{
    if (!axis->active || !axis->planned_steps) {
        *exact = true;
        return 0u;
    }
    if (axis_block_drained(axis)) {
        *exact = true;
        return axis->planned_steps;
    }
    *exact = false;
    uint32_t remaining = dma_hw->ch[axis->dma_chan].transfer_count;
    if (remaining > axis->planned_steps) {
        remaining = axis->planned_steps;
    }
    uint32_t executed = axis->planned_steps - remaining;
    const uint32_t queued = pio_sm_get_tx_fifo_level(axis->pio, axis->sm);
    executed = executed > queued ? executed - queued : 0u;
    if (executed) {
        --executed;
    }
    return executed;
}

static void stop_axis_now(motor_axis_t *axis)
{
    const uint32_t saved = save_and_disable_interrupts();
    bool exact;
    pio_sm_set_enabled(axis->pio, axis->sm, false);
    const uint32_t executed = axis_executed_steps(axis, &exact);
    if (dma_channel_is_busy(axis->dma_chan)) {
        dma_channel_abort(axis->dma_chan);
    }
    if (axis->active && axis->planned_steps) {
        positioning_add_steps(axis->id, axis->dir_bit, executed, exact);
    }

    axis->active = false;
    axis->continuous = false;
    axis->needs_ramp = false;
    axis->planned_steps = 0u;
    pio_sm_clear_fifos(axis->pio, axis->sm);
    pio_sm_restart(axis->pio, axis->sm);
    pio_sm_exec(axis->pio, axis->sm, pio_encode_set(pio_pins, 0));
    pio_sm_exec(axis->pio, axis->sm, pio_encode_jmp(motor_pio_offset));
    pio_sm_set_enabled(axis->pio, axis->sm, true);
    restore_interrupts(saved);
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

static bool start_axis_block(motor_axis_t *axis)
{
    uint32_t room = positioning_steps_available(axis->id, axis->dir_bit);
    if (!axis->active || room == 0u) {
        stop_axis_now(axis);
        return false;
    }
    const uint32_t steps = room < MAX_STEPS ? room : MAX_STEPS;
    if (axis->needs_ramp) {
        build_ramp_profile(axis->profile, axis->dir_bit, axis->target_freq_hz);
        axis->needs_ramp = false;
    } else {
        build_cruise_profile(axis->profile, axis->dir_bit, axis->target_freq_hz);
    }

    const uint32_t saved = save_and_disable_interrupts();
    room = positioning_steps_available(axis->id, axis->dir_bit);
    if (!axis->active || room < steps) {
        restore_interrupts(saved);
        stop_axis_now(axis);
        return false;
    }
    axis->planned_steps = steps;
#ifdef EN_PIN
    gpio_put(EN_PIN, 0);
#endif
    start_dma(axis->pio, axis->sm, axis->dma_chan, axis->profile, steps);
    restore_interrupts(saved);
    return true;
}

static bool jog_axis(motor_axis_t *axis, bool dir_bit, uint32_t freq_hz)
{
    if (freq_hz == 0 || freq_hz > MAX_MOTOR_FREQ_HZ) {
        return false;
    }
    if (axis->active && axis->continuous &&
        axis->dir_bit == dir_bit && axis->target_freq_hz == freq_hz) {
        return true;
    }
    stop_axis_now(axis);
    if (positioning_steps_available(axis->id, dir_bit) == 0u) {
        return false;
    }
    axis->dir_bit = dir_bit;
    axis->target_freq_hz = freq_hz;
    axis->active = true;
    axis->continuous = true;
    axis->needs_ramp = true;
    return start_axis_block(axis);
}

static void service_axis(motor_axis_t *axis)
{
    if (!axis->active || !axis_block_drained(axis)) {
        return;
    }
    const uint32_t saved = save_and_disable_interrupts();
    if (!axis->active || !axis_block_drained(axis)) {
        restore_interrupts(saved);
        return;
    }
    positioning_add_steps(axis->id, axis->dir_bit, axis->planned_steps, true);
    axis->planned_steps = 0u;
    const bool continue_jog = axis->continuous;
    restore_interrupts(saved);

    if (continue_jog) {
        start_axis_block(axis);
    } else {
        stop_axis_now(axis);
    }
}

static void home_fail(void)
{
    stop_axis_now(&axis_x);
    stop_axis_now(&axis_y);
    positioning_cancel_homing(POSITION_AXIS_X);
    positioning_cancel_homing(POSITION_AXIS_Y);
    home_state = HOME_FAILED;
}

static void home_start_y(void)
{
    if (positioning_switch_active(POSITION_AXIS_Y)) {
        positioning_set_zero(POSITION_AXIS_Y);
        home_state = HOME_COMPLETE;
        return;
    }
    positioning_begin_homing(POSITION_AXIS_Y);
    home_state = HOME_Y;
    home_stage_start_ms = to_ms_since_boot(get_absolute_time());
    if (!jog_axis(&axis_y, Y_DIR_TOWARD_ZERO, HOME_SPEED_HZ)) {
        home_fail();
    }
}

bool motor_home_xy(void)
{
    if (axis_x.active || axis_y.active || axis_z.active) return false;
    positioning_cancel_homing(POSITION_AXIS_X);
    positioning_cancel_homing(POSITION_AXIS_Y);
    if (positioning_switch_active(POSITION_AXIS_X)) {
        positioning_set_zero(POSITION_AXIS_X);
        home_start_y();
    } else {
        positioning_begin_homing(POSITION_AXIS_X);
        home_state = HOME_X;
        home_stage_start_ms = to_ms_since_boot(get_absolute_time());
        if (!jog_axis(&axis_x, X_DIR_TOWARD_ZERO, HOME_SPEED_HZ)) {
            home_fail();
        }
    }
    return home_state != HOME_FAILED;
}

bool motor_is_homing_xy(void)
{
    return home_state == HOME_X || home_state == HOME_Y;
}

const char *motor_home_status(void)
{
    switch (home_state) {
        case HOME_X: return "homing-x";
        case HOME_Y: return "homing-y";
        case HOME_COMPLETE: return "complete";
        case HOME_FAILED: return "failed";
        default: return "idle";
    }
}

void motor_service(void)
{
    service_axis(&axis_x);
    service_axis(&axis_y);
    service_axis(&axis_z);
    if (home_state == HOME_X) {
        if (positioning_is_homed(POSITION_AXIS_X)) {
            home_start_y();
        } else if (!axis_x.active ||
                   (uint32_t)(to_ms_since_boot(get_absolute_time()) -
                              home_stage_start_ms) > HOME_AXIS_TIMEOUT_MS) {
            home_fail();
        }
    } else if (home_state == HOME_Y) {
        if (positioning_is_homed(POSITION_AXIS_Y)) {
            home_state = HOME_COMPLETE;
        } else if (!axis_y.active ||
                   (uint32_t)(to_ms_since_boot(get_absolute_time()) -
                              home_stage_start_ms) > HOME_AXIS_TIMEOUT_MS) {
            home_fail();
        }
    }
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

bool motor_stop_if_direction(position_axis_t id, bool positive)
{
    motor_axis_t *axis = id == POSITION_AXIS_X ? &axis_x :
                         id == POSITION_AXIS_Y ? &axis_y : &axis_z;
    if (axis->active && axis->dir_bit == positive) {
        stop_axis_now(axis);
        return true;
    }
    return false;
}

int32_t motor_inflight_step_delta(position_axis_t id, bool *exact)
{
    if (id > POSITION_AXIS_Z) {
        *exact = false;
        return 0;
    }
    const motor_axis_t *axis = id == POSITION_AXIS_X ? &axis_x :
                               id == POSITION_AXIS_Y ? &axis_y : &axis_z;
    const uint32_t saved = save_and_disable_interrupts();
    const uint32_t amount = axis_executed_steps(axis, exact);
    const int32_t delta = positioning_dir_increases_coord(id, axis->dir_bit) ?
                          (int32_t)amount : -(int32_t)amount;
    restore_interrupts(saved);
    return delta;
}

bool motor_any_active(void)
{
    return axis_x.active || axis_y.active || axis_z.active;
}

void motor_stop_all(void)
{
    if (motor_is_homing_xy()) {
        positioning_cancel_homing(POSITION_AXIS_X);
        positioning_cancel_homing(POSITION_AXIS_Y);
        home_state = HOME_FAILED;
    }
    stop_axis_now(&axis_x);
    stop_axis_now(&axis_y);
    stop_axis_now(&axis_z);
#ifdef EN_PIN
    gpio_put(EN_PIN, 1);
#endif
}

static bool parse_motion(const char *args, bool finite,
                         bool allow_up_down, bool *dir,
                         uint32_t *freq_hz, uint32_t *steps)
{
    char direction[16];
    char extra;
    int fields;
    if (args == NULL) {
        return false;
    }
    if (finite) {
        fields = sscanf(args, "%15s %" SCNu32 " %" SCNu32 " %c", direction,
                        freq_hz, steps, &extra);
        if (fields != 3 || *steps == 0 || *steps > MAX_STEPS) {
            return false;
        }
    } else {
        fields = sscanf(args, "%15s %" SCNu32 " %c", direction,
                        freq_hz, &extra);
        if (fields != 2) {
            return false;
        }
    }
    if (*freq_hz == 0 || *freq_hz > MAX_MOTOR_FREQ_HZ) {
        return false;
    }
    if (strcmp(direction, "plus") == 0 ||
        (allow_up_down && strcmp(direction, "up") == 0)) {
        *dir = true;
    } else if (strcmp(direction, "minus") == 0 ||
               (allow_up_down && strcmp(direction, "down") == 0)) {
        *dir = false;
    } else {
        return false;
    }
    return true;
}

static bool jog_command(motor_axis_t *axis, const char *args, bool z_axis)
{
    bool direction;
    uint32_t frequency = 0, ignored_steps = 0;
    if (!parse_motion(args, false, z_axis, &direction,
                      &frequency, &ignored_steps)) {
        return false;
    }
    return jog_axis(axis,
        positioning_dir_for_coordinate(axis->id, direction), frequency);
}

bool jog_x(const char *args) { return jog_command(&axis_x, args, false); }
bool jog_y(const char *args) { return jog_command(&axis_y, args, false); }
bool jog_z(const char *args) { return jog_command(&axis_z, args, true); }

static bool finite_move(motor_axis_t *axis, const char *args, bool z_axis)
{
    bool direction;
    uint32_t frequency = 0, steps = 0;
    if (!parse_motion(args, true, z_axis, &direction, &frequency, &steps)) {
        return false;
    }
    const bool motor_dir = positioning_dir_for_coordinate(axis->id, direction);
    stop_axis_now(axis);
    if (steps > positioning_steps_available(axis->id, motor_dir)) {
        return false;
    }
    ramp_profile(axis->profile, motor_dir, frequency, steps);
    const uint32_t saved = save_and_disable_interrupts();
    if (steps > positioning_steps_available(axis->id, motor_dir)) {
        restore_interrupts(saved);
        return false;
    }
    axis->active = true;
    axis->continuous = false;
    axis->dir_bit = motor_dir;
    axis->planned_steps = steps;
    axis->needs_ramp = false;
#ifdef EN_PIN
    gpio_put(EN_PIN, 0);
#endif
    start_dma(axis->pio, axis->sm, axis->dma_chan, axis->profile, steps);
    restore_interrupts(saved);
    return true;
}

bool move_x(const char *args) { return finite_move(&axis_x, args, false); }
bool move_y(const char *args) { return finite_move(&axis_y, args, false); }
bool move_z(const char *args) { return finite_move(&axis_z, args, true); }

void motor_setup(void)
{
#ifdef EN_PIN
    gpio_init(EN_PIN);
    gpio_put(EN_PIN, 1);
    gpio_set_dir(EN_PIN, GPIO_OUT);
#endif

    motor_pio_offset = pio_add_program(motor_pio, &stepper_ctrl_program);

    const uint sm_x = pio_claim_unused_sm(motor_pio, true);
    const uint sm_y = pio_claim_unused_sm(motor_pio, true);
    const uint sm_z = pio_claim_unused_sm(motor_pio, true);
    init_motor_sm(motor_pio, sm_x, motor_pio_offset, STEP_PIN_X, DIR_PIN_X);
    init_motor_sm(motor_pio, sm_y, motor_pio_offset, STEP_PIN_Y, DIR_PIN_Y);
    init_motor_sm(motor_pio, sm_z, motor_pio_offset, STEP_PIN_Z, DIR_PIN_Z);

    dma_chan_x = dma_claim_unused_channel(true);
    dma_chan_y = dma_claim_unused_channel(true);
    dma_chan_z = dma_claim_unused_channel(true);

    axis_x = (motor_axis_t){.pio=motor_pio, .sm=sm_x, .dma_chan=dma_chan_x,
        .profile=step_profile_x, .step_pin=STEP_PIN_X, .dir_pin=DIR_PIN_X,
        .id=POSITION_AXIS_X};
    axis_y = (motor_axis_t){.pio=motor_pio, .sm=sm_y, .dma_chan=dma_chan_y,
        .profile=step_profile_y, .step_pin=STEP_PIN_Y, .dir_pin=DIR_PIN_Y,
        .id=POSITION_AXIS_Y};
    axis_z = (motor_axis_t){.pio=motor_pio, .sm=sm_z, .dma_chan=dma_chan_z,
        .profile=step_profile_z, .step_pin=STEP_PIN_Z, .dir_pin=DIR_PIN_Z,
        .id=POSITION_AXIS_Z};
    positioning_init();
#if AUTO_HOME_XY_ON_STARTUP
    (void)motor_home_xy();
#endif
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
