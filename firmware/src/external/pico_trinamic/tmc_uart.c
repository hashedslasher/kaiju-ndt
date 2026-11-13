/*
  tmc_uart.c - driver code for RP2040 ARM processors

  Copyright (c) 2025 Hannah Eikens
  Original code retrieved from https://github.com/grblHAL/RP2040/blob/master/tmc_uart.c

  grblHAL is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  grblHAL is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with grblHAL. If not, see <http://www.gnu.org/licenses/>.
*/

#include "common.h"
#include "tmc_uart.h"

static uart_inst_t * tmc_uart;

TMC_uart_write_datagram_t *tmc_uart_read (trinamic_motor_t driver, TMC_uart_read_datagram_t *dgr)
{
    static TMC_uart_write_datagram_t wdgr = {0};
    volatile uint32_t dly = 50, ms = to_ms_since_boot(get_absolute_time());

//    tmc_uart.reset_write_buffer();
    uart_write_blocking(tmc_uart, dgr->data, sizeof(TMC_uart_write_datagram_t));
    uart_tx_wait_blocking(tmc_uart);

    while(--dly)
        tight_loop_contents();

    // Wait for response with 2ms timeout
    while(!uart_is_readable(tmc_uart)) {
        if(to_ms_since_boot(get_absolute_time()) - ms >= 3)
            break;
    }

    uint8_t buffer[8];

    if(uart_is_readable(tmc_uart)) {
        uart_read_blocking(tmc_uart, buffer, 8);
    }

    if(buffer != NULL) {
        wdgr.data[0] = buffer[0];
        wdgr.data[1] = buffer[1];
        wdgr.data[2] = buffer[2];
        wdgr.data[3] = buffer[3];
        wdgr.data[4] = buffer[4];
        wdgr.data[5] = buffer[5];
        wdgr.data[6] = buffer[6];
        wdgr.data[7] = buffer[7];
    } else
        wdgr.msg.addr.value = 0xFF;

    dly = 8000;
    while(--dly)
        tight_loop_contents();

    return &wdgr;
}

void tmc_uart_write (trinamic_motor_t driver, TMC_uart_write_datagram_t *dgr)
{
    uart_write_blocking(tmc_uart, dgr->data, sizeof(TMC_uart_write_datagram_t));
    uart_tx_wait_blocking(tmc_uart);
}

void tmc_uart_init (uart_inst_t * uart, uint baudrate)
{   
    uart_init(uart, baudrate);
    tmc_uart = uart;
}
