#ifndef MOCK_STDLIB_H
#define MOCK_STDLIB_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
typedef unsigned int uint;
uint64_t time_us_64(void);
void tight_loop_contents(void);
void sleep_us(uint64_t delay);
#endif
