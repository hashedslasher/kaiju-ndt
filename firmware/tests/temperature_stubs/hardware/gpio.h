#ifndef KAIJU_TEMP_STUB_GPIO_H
#define KAIJU_TEMP_STUB_GPIO_H
#include <stdbool.h>
#include <stdint.h>
#define GPIO_IN false
#define GPIO_OUT true
void gpio_init(unsigned pin);
void gpio_put(unsigned pin, bool value);
void gpio_set_dir(unsigned pin, bool output);
void gpio_pull_up(unsigned pin);
bool gpio_get(unsigned pin);
#endif
