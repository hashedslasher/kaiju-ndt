#ifndef KAIJU_TEMPERATURE_H
#define KAIJU_TEMPERATURE_H

typedef enum {
    TEMPERATURE_READY,
    TEMPERATURE_PENDING,
    TEMPERATURE_UNAVAILABLE
} temperature_result_t;

/* DS18B20 on Pico GPIO20, using open-drain 1-Wire timing.
 * DQ must be electrically bidirectional and externally pulled up on the
 * sensor side. The current Si8663BB A3->B3 channel is NOT bidirectional.
 * The sensor must have VDD connected; parasite power is not supported.
 */
temperature_result_t temperature_poll(float *degrees_c);
const char *temperature_error(void);

#endif
