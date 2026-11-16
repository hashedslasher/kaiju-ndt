#ifndef TMC_UART_H
#define TMC_UART_H

#include <stdbool.h>
#include "sc16is750.h"

void tmc_uart_init(SC16IS750_t *bridge);
bool tmc_uart_last_ok(void);
const char *tmc_uart_last_error(void);

#endif
