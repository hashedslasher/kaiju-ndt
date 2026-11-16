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

/* The RP2350 board connects TMC UARTs through the SC16IS752 I2C bridge. */
#include <string.h>
#include "common.h"
#include "tmc_uart.h"
#include "pico/stdlib.h"

#define TMC_UART_TIMEOUT_US 70000u

static SC16IS750_t *serial_bridge;
static bool transport_ok;
static const char *transport_error = "not initialized";

void tmc_uart_init(SC16IS750_t *bridge)
{
    serial_bridge = bridge;
    transport_ok = bridge != NULL;
    transport_error = transport_ok ? "ok" : "UART bridge missing";
}

bool tmc_uart_last_ok(void)
{
    return transport_ok;
}

const char *tmc_uart_last_error(void)
{
    return transport_error;
}

static bool error(const char *reason)
{
    transport_ok = false;
    transport_error = reason;
    return false;
}

static bool channel_from_motor(trinamic_motor_t motor, uint8_t *channel)
{
    if (!serial_bridge || motor.id >= 5u) return error("invalid motor / bridge");
    *channel = motor.id < 3u ? SC16IS750_CHANNEL_A : SC16IS750_CHANNEL_B;
    return true;
}

static bool clear_rx(uint8_t channel)
{
    uint8_t count;
    if (!SC16IS750_ReadRegisterChecked(serial_bridge, channel, SC16IS750_REG_RXLVL, &count))
        return error("SC RXLVL I2C read failed");
    while (count) {
        uint8_t unused[64];
        const uint8_t amount = count > sizeof(unused) ? sizeof(unused) : count;
        if (!SC16IS750_ReadFIFO(serial_bridge, channel, unused, amount))
            return error("SC RX drain failed");
        count = (uint8_t)(count - amount);
    }
    return true;
}

static bool transmit(uint8_t channel, const uint8_t *bytes, size_t count)
{
    uint8_t capacity;
    if (!clear_rx(channel)) return false;
    if (!SC16IS750_ReadRegisterChecked(serial_bridge, channel, SC16IS750_REG_TXLVL, &capacity))
        return error("SC TXLVL read failed");
    if (capacity < count) return error("SC TX FIFO full");
    if (!SC16IS750_WriteFIFO(serial_bridge, channel, bytes, count))
        return error("SC TX FIFO I2C write failed");

    const uint64_t deadline = time_us_64() + TMC_UART_TIMEOUT_US;
    do {
        uint8_t lsr;
        if (!SC16IS750_ReadRegisterChecked(serial_bridge, channel, SC16IS750_REG_LSR, &lsr))
            return error("SC LSR read failed");
        if (lsr & 0x40u) {
            transport_ok = true;
            transport_error = "ok";
            return true;
        }
    } while (time_us_64() < deadline);
    return error("SC transmit completion timeout");
}

void tmc_uart_write(trinamic_motor_t motor, TMC_uart_write_datagram_t *dgr)
{
    uint8_t channel;
    if (!channel_from_motor(motor, &channel)) return;
    if (!transmit(channel, dgr->data, sizeof(dgr->data))) return;
    sleep_us(150u);
}

TMC_uart_write_datagram_t *tmc_uart_read(trinamic_motor_t motor, TMC_uart_read_datagram_t *dgr)
{
    static TMC_uart_write_datagram_t reply;
    memset(&reply, 0, sizeof(reply));
    reply.msg.addr.value = 0xFFu;
    uint8_t channel;
    if (!channel_from_motor(motor, &channel)) return &reply;
    if (!transmit(channel, dgr->data, sizeof(dgr->data))) return &reply;

    uint8_t window[8] = {0};
    size_t used = 0;
    const uint64_t deadline = time_us_64() + TMC_UART_TIMEOUT_US;
    while (time_us_64() < deadline) {
        uint8_t available;
        if (!SC16IS750_ReadRegisterChecked(serial_bridge, channel, SC16IS750_REG_RXLVL, &available)) {
            error("SC reply RXLVL I2C read failed");
            return &reply;
        }
        if (available == 0) {
            sleep_us(50u);
            continue;
        }
        while (available) {
            uint8_t fifo[64];
            const uint8_t amount = available > sizeof(fifo) ? sizeof(fifo) : available;
            if (!SC16IS750_ReadFIFO(serial_bridge, channel, fifo, amount)) {
                error("SC reply FIFO I2C read failed");
                return &reply;
            }
            available = (uint8_t)(available - amount);
            for (unsigned i = 0; i < amount; ++i) {
                if (used < sizeof(window)) window[used++] = fifo[i];
                else {
                    memmove(window, window + 1, sizeof(window) - 1);
                    window[sizeof(window) - 1] = fifo[i];
                }
                if (used == sizeof(window) && window[0] == 0x05u &&
                    window[1] == 0xFFu && window[2] == dgr->msg.addr.value) {
                    memcpy(reply.data, window, sizeof(reply.data));
                    transport_ok = true;
                    transport_error = "ok";
                    return &reply;
                }
            }
        }
    }
    error("TMC UART reply timeout");
    return &reply;
}
