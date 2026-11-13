#ifndef TMC_UART_H
#define TMC_UART_H

#include "pico/stdlib.h"
#include "hardware/uart.h"

void tmc_uart_init(uart_inst_t * uart, uint baudrate);

#endif