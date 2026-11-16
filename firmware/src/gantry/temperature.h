#ifndef KAIJU_TEMPERATURE_H
#define KAIJU_TEMPERATURE_H
#include <stdbool.h>
#include <stdint.h>
typedef enum {
    TEMPERATURE_READY,
    TEMPERATURE_PENDING,
    TEMPERATURE_UNAVAILABLE
} temperature_result_t;
typedef struct {
    uint32_t attempts, valid, resets, tests, no_presence, crc_fail, invalid_data, io_fail;
    uint32_t reset_low_us, presence_read_us, write1_low_us, read_sample_us;
    bool presence, idle_high, sample_high;
} temperature_stats_t;
temperature_result_t temperature_poll(float *degrees_c);
const char *temperature_error(void);
const temperature_stats_t *temperature_stats(void);
bool temperature_test(void);
#endif
