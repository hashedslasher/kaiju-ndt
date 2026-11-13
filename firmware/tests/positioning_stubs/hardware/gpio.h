#ifndef KAIJU_POS_GPIO_H
#define KAIJU_POS_GPIO_H
#include <stdbool.h>
#include <stdint.h>
typedef unsigned uint;
#define GPIO_IN false
#define GPIO_IRQ_EDGE_FALL 4u
#define GPIO_IRQ_EDGE_RISE 8u
void gpio_init(uint pin);
void gpio_set_dir(uint pin, bool output);
void gpio_pull_up(uint pin);
int gpio_get(uint pin);
void gpio_set_irq_enabled_with_callback(uint pin, uint32_t events,
                                        bool enabled,
                                        void (*callback)(uint, uint32_t));
#endif
