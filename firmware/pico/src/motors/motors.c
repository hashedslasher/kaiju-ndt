#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/clocks.h"
#include "string.h"
#include "stdio.h"
#include "motors.pio.h"

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

PIO motor_pio = pio0;
uint motor_pio_offset;

void init_motor_sm(PIO pio, uint sm, uint offset, uint step_pin, uint dir_pin) {
    pio_gpio_init(pio, step_pin);
    pio_gpio_init(pio, dir_pin);
    pio_sm_set_consecutive_pindirs(pio, sm, step_pin, 1, true);
    pio_sm_set_consecutive_pindirs(pio, sm, dir_pin, 1, true);

    pio_sm_config c = stepper_ctrl_program_get_default_config(offset);
    sm_config_set_set_pins(&c, step_pin, 1);
    sm_config_set_sideset_pins(&c, dir_pin); 
    
    pio_sm_init(pio, sm, offset, &c);
    pio_sm_set_enabled(pio, sm, true);
}

void start_dma(PIO pio, uint sm, int dma_chan, uint32_t* profile, uint32_t steps) {
    if (dma_channel_is_busy(dma_chan)) {
        dma_channel_abort(dma_chan);
        pio_sm_clear_fifos(pio, sm);
    }

    dma_channel_config c = dma_channel_get_default_config(dma_chan);
    channel_config_set_transfer_data_size(&c, DMA_SIZE_32);
    channel_config_set_read_increment(&c, true);
    channel_config_set_write_increment(&c, false);
    channel_config_set_dreq(&c, pio_get_dreq(pio, sm, true));

    dma_channel_configure(
        dma_chan, &c,
        &pio->txf[sm], 
        profile,       
        steps,
        true           
    );
}

void motor_setup() {
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
}

void ramp_profile(uint32_t* profile_array, bool dir_bit, uint32_t target_freq_hz, uint32_t steps) {
    uint32_t sys_clk = clock_get_hz(clk_sys);
    uint32_t start_freq = START_FREQ_HZ;
    uint32_t ramp_steps = MAX_RAMP_STEPS;
    
    if (steps < (MAX_RAMP_STEPS * 2)) {
        ramp_steps = steps / 2;
    }

    if (target_freq_hz <= start_freq) {
        start_freq = target_freq_hz;
        ramp_steps = 0;
    }

    float freq_inc = 0;
    if (ramp_steps > 0) {
        freq_inc = (float)(target_freq_hz - start_freq) / ramp_steps;
    }

    for (uint32_t i = 0; i < steps; i++) {
        uint32_t current_freq = target_freq_hz;

        if (i < ramp_steps) {
            current_freq = start_freq + (uint32_t)(i * freq_inc);
        } else if (i >= steps - ramp_steps) {
            uint32_t decel_step = steps - i; 
            current_freq = start_freq + (uint32_t)(decel_step * freq_inc);
        }

        uint32_t delay = (sys_clk / current_freq) - 32;
        profile_array[i] = (dir_bit ? 0x80000000 : 0) | (delay & 0x7FFFFFFF);
    }
}

void move_x(const char *args) {
    char dir_str[16];
    uint32_t freq_hz = 0;
    uint32_t steps = 0;

    if (sscanf(args, "%15s %lu %lu", dir_str, &freq_hz, &steps) != 3) {
        return;
    }

    if (steps > MAX_STEPS) steps = MAX_STEPS;
    if (steps == 0 || freq_hz == 0) return;

    bool dir_bit = false;
    if (strcmp(dir_str, "plus") == 0) dir_bit = true;
    else if (strcmp(dir_str, "minus") == 0) dir_bit = false;
    else return;

    ramp_profile(step_profile_x, dir_bit, freq_hz, steps);
    start_dma(motor_pio, 0, dma_chan_x, step_profile_x, steps);
}

void move_y(const char *args) {
    char dir_str[16];
    uint32_t freq_hz = 0;
    uint32_t steps = 0;

    if (sscanf(args, "%15s %lu %lu", dir_str, &freq_hz, &steps) != 3) return;
    if (steps > MAX_STEPS) steps = MAX_STEPS;
    if (steps == 0 || freq_hz == 0) return;

    bool dir_bit = false;
    if (strcmp(dir_str, "plus") == 0) dir_bit = true;
    else if (strcmp(dir_str, "minus") == 0) dir_bit = false;
    else return;

    ramp_profile(step_profile_y, dir_bit, freq_hz, steps);
    start_dma(motor_pio, 1, dma_chan_y, step_profile_y, steps);
}

void move_z(const char *args) {
    char dir_str[16];
    uint32_t freq_hz = 0;
    uint32_t steps = 0;

    if (sscanf(args, "%15s %lu %lu", dir_str, &freq_hz, &steps) != 3) return;
    if (steps > MAX_STEPS) steps = MAX_STEPS;
    if (steps == 0 || freq_hz == 0) return;

    bool dir_bit = false;
    if (strcmp(dir_str, "plus") == 0 || strcmp(dir_str, "up") == 0) dir_bit = true;
    else if (strcmp(dir_str, "minus") == 0 || strcmp(dir_str, "down") == 0) dir_bit = false;
    else return;

    ramp_profile(step_profile_z, dir_bit, freq_hz, steps);
    start_dma(motor_pio, 2, dma_chan_z, step_profile_z, steps);
}
