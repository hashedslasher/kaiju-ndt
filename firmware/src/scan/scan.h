#ifndef SCAN_H
#define SCAN_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint32_t nx;
    uint32_t ny;
    uint32_t dx_steps;
    uint32_t dy_steps;
    uint32_t speed_hz;
    uint32_t gate_start;
    uint32_t gate_end;
    uint32_t settle_ms;
} scan_config_t;

bool scan_start(const scan_config_t *config, const char **error);
void scan_poll(void);
void scan_abort(void);
bool scan_active(void);

#endif
