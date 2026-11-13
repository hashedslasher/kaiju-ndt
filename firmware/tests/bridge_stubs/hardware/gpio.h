#ifndef MOCK_GPIO_H
#define MOCK_GPIO_H
#include <stdint.h>
#include <stdbool.h>
#define GPIO_FUNC_I2C 3
#define GPIO_IN 0
void gpio_set_function(unsigned, unsigned);
void gpio_pull_up(unsigned);
void gpio_init(unsigned);
void gpio_set_dir(unsigned, bool);
int gpio_get(unsigned);
#endif
