#include "pico/stdlib.h"
#include "hardware/gpio.h"

#define STEP_PIN_X  18
#define DIR_PIN_X   19
#define STEP_PIN_Y  20
#define DIR_PIN_Y   21
#define STEP_PIN_Z  22
#define DIR_PIN_Z   26

#define EN_PIN    28

#define STEPS_PER_REV  3200
#define PULSE_US  1000

void motor_setup() {
    gpio_init(STEP_PIN_X);
    gpio_init(DIR_PIN_X);
    
    gpio_init(STEP_PIN_Y);
    gpio_init(DIR_PIN_Y);
    
    gpio_init(STEP_PIN_Z);
    gpio_init(DIR_PIN_Z);
    
    gpio_init(EN_PIN);

    gpio_set_dir(STEP_PIN_X, GPIO_OUT);
    gpio_set_dir(DIR_PIN_X,  GPIO_OUT);
    
    gpio_set_dir(STEP_PIN_Y, GPIO_OUT);
    gpio_set_dir(DIR_PIN_Y,  GPIO_OUT);
    
    gpio_set_dir(STEP_PIN_Z, GPIO_OUT);
    gpio_set_dir(DIR_PIN_Z,  GPIO_OUT);
    
    gpio_set_dir(EN_PIN,   GPIO_OUT);

    gpio_put(EN_PIN,   0);
    
    gpio_put(STEP_PIN_X, 0);
    gpio_put(DIR_PIN_X,  0);
    
    gpio_put(STEP_PIN_Y, 0);
    gpio_put(DIR_PIN_Y,  0);
    
    gpio_put(STEP_PIN_Z, 0);
    gpio_put(DIR_PIN_Z,  0);
}

void move_x_plus () {
    gpio_put(DIR_PIN_X, 1);
    for (int i = 0; i < 16; i++) {
        gpio_put(STEP_PIN_X, 1);
        sleep_us(PULSE_US);
        gpio_put(STEP_PIN_X, 0);
        sleep_us(PULSE_US);
    }
}

void move_x_minus () {
    gpio_put(DIR_PIN_X, 0);
    for (int i = 0; i < 16; i++) {
        gpio_put(STEP_PIN_X, 1);
        sleep_us(PULSE_US);
        gpio_put(STEP_PIN_X, 0);
        sleep_us(PULSE_US);
    }
}

void move_y_plus () {
    gpio_put(DIR_PIN_Y, 1);
    for (int i = 0; i < 16; i++) {
        gpio_put(STEP_PIN_Y, 1);
        sleep_us(PULSE_US);
        gpio_put(STEP_PIN_Y, 0);
        sleep_us(PULSE_US);
    }
}

void move_y_minus () {
    gpio_put(DIR_PIN_Y, 0);
    for (int i = 0; i < 16; i++) {
        gpio_put(STEP_PIN_Y, 1);
        sleep_us(PULSE_US);
        gpio_put(STEP_PIN_Y, 0);
        sleep_us(PULSE_US);
    }
}

void move_z_plus () {
    gpio_put(DIR_PIN_Z, 1);
    for (int i = 0; i < 16; i++) {
        gpio_put(STEP_PIN_Z, 1);
        sleep_us(PULSE_US);
        gpio_put(STEP_PIN_Z, 0);
        sleep_us(PULSE_US);
    }
}

void move_z_minus () {
    gpio_put(DIR_PIN_Z, 0);
    for (int i = 0; i < 16; i++) {
        gpio_put(STEP_PIN_Z, 1);
        sleep_us(PULSE_US);
        gpio_put(STEP_PIN_Z, 0);
        sleep_us(PULSE_US);
    }
}
