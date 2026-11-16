/*
SC16IS750/752 Driver for RaspberryPi
*/


//#define SC16IS750_DEBUG_PRINT

#include <stdio.h>	
#include <stdint.h>
#include <stdbool.h>	
#include <stdlib.h>  
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/i2c.h"
#include "hardware/gpio.h"
#include "sc16is750.h"

#define SC_TIMEOUT_US 25000u
#define SC_I2C_HZ 100000u
#define SC_SDA_PIN 28u
#define SC_SCL_PIN 21u

static bool bus_initialized;

static bool sc_error(SC16IS750_t *dev, const char *phase, uint8_t subreg, int result)
{
    dev->last_error = result;
    dev->last_selector = subreg;
    dev->last_phase = phase;
    return false;
}

bool SC16IS750_BusSetup(SC16IS750_t *dev)
{
    if (dev->protocol != SC16IS750_PROTOCOL_I2C)
        return sc_error(dev, "protocol", 0, -20);
    if (bus_initialized) i2c_deinit(i2c0);
    gpio_init(SC_SDA_PIN);
    gpio_init(SC_SCL_PIN);
    gpio_disable_pulls(SC_SDA_PIN);
    gpio_disable_pulls(SC_SCL_PIN);
    dev->actual_hz = i2c_init(i2c0, SC_I2C_HZ);
    gpio_set_function(SC_SDA_PIN, GPIO_FUNC_I2C);
    gpio_set_function(SC_SCL_PIN, GPIO_FUNC_I2C);
    bus_initialized = true;
    sleep_us(100);
    if (!gpio_get(SC_SDA_PIN) || !gpio_get(SC_SCL_PIN))
        return sc_error(dev, "bus-not-high", 0, -21);
    dev->last_error = 0;
    dev->last_phase = "ok";
    return true;
}

static bool sc_port_read(SC16IS750_t *dev, uint8_t subreg, uint8_t *out, size_t length)
{
    if (!dev || !out || !length || dev->protocol != SC16IS750_PROTOCOL_I2C) return false;
    const int select = i2c_write_timeout_us(i2c0, dev->device_address_i2c, &subreg, 1, true, SC_TIMEOUT_US);
    if (select != 1) return sc_error(dev, "select", subreg, select < 0 ? select : -10);
    const int count = i2c_read_timeout_us(i2c0, dev->device_address_i2c, out, length, false, SC_TIMEOUT_US);
    if (count != (int)length) return sc_error(dev, "read", subreg, count < 0 ? count : -11);
    dev->last_error = 0;
    dev->last_selector = subreg;
    dev->last_phase = "ok";
    return true;
}

static bool sc_port_write(SC16IS750_t *dev, uint8_t subreg, const uint8_t *data, size_t length)
{
    if (!dev || !data || !length || length > 64 || dev->protocol != SC16IS750_PROTOCOL_I2C) return false;
    uint8_t frame[65];
    frame[0] = subreg;
    memcpy(frame + 1, data, length);
    const int count = i2c_write_timeout_us(i2c0, dev->device_address_i2c, frame, length + 1, false, SC_TIMEOUT_US);
    if (count != (int)(length + 1)) return sc_error(dev, "write", subreg, count < 0 ? count : -12);
    dev->last_error = 0;
    dev->last_selector = subreg;
    dev->last_phase = "ok";
    return true;
}

bool SC16IS750_ReadRegisterChecked(SC16IS750_t *dev, uint8_t channel, uint8_t reg, uint8_t *value)
{
    return sc_port_read(dev, (uint8_t)(reg << 3 | channel << 1), value, 1);
}

bool SC16IS750_WriteRegisterChecked(SC16IS750_t *dev, uint8_t channel, uint8_t reg, uint8_t value)
{
    return sc_port_write(dev, (uint8_t)(reg << 3 | channel << 1), &value, 1);
}

bool SC16IS750_WriteFIFO(SC16IS750_t *dev, uint8_t channel, const uint8_t *data, size_t length)
{
    if (!length) return true;
    return sc_port_write(dev, (uint8_t)(SC16IS750_REG_THR << 3 | channel << 1), data, length);
}

bool SC16IS750_ReadFIFO(SC16IS750_t *dev, uint8_t channel, uint8_t *data, size_t length)
{
    if (!length) return true;
    return sc_port_read(dev, (uint8_t)(SC16IS750_REG_RHR << 3 | channel << 1), data, length);
}

void SC16IS750_init(SC16IS750_t *dev, uint8_t protocol, uint8_t address, int channels)
{
    memset(dev, 0, sizeof(*dev));
    dev->protocol = protocol;
    dev->device_address_i2c = address;
    dev->channels = channels;
    dev->timeout = 40u;
    dev->last_error = -1;
}

bool SC16IS750_Probe(SC16IS750_t *dev, uint8_t *iocontrol)
{
    if (!SC16IS750_BusSetup(dev)) return false;
    if (!SC16IS750_ReadRegisterChecked(dev, SC16IS750_CHANNEL_A,
                                      SC16IS750_REG_IOCONTROL, iocontrol)) return false;
    return SC16IS750_ping(dev) != 0;
}

static bool sc_setup_uart(SC16IS750_t *dev, uint8_t channel, uint32_t baud)
{
    if (!SC16IS750_WriteRegisterChecked(dev, channel, SC16IS750_REG_LCR, 0x03u) ||
        !SC16IS750_WriteRegisterChecked(dev, channel, SC16IS750_REG_IER, 0u) ||
        !SC16IS750_WriteRegisterChecked(dev, channel, SC16IS750_REG_MCR, 0u) ||
        !SC16IS750_WriteRegisterChecked(dev, channel, SC16IS750_REG_EFCR, 0u)) return false;
    SC16IS750_FIFOEnable(dev, channel, 1);
    if (dev->last_error) return false;
    SC16IS750_SetBaudrate(dev, channel, baud);
    if (dev->last_error) return false;
    SC16IS750_SetLine(dev, channel, 8, 0, 1);
    return dev->last_error == 0;
}

void SC16IS750_begin(SC16IS750_t *dev, uint32_t baud_A, uint32_t baud_B, long crystal_freq)
{
    dev->crystal_freq = crystal_freq;
    uint8_t iocontrol;
    if (!SC16IS750_Probe(dev, &iocontrol)) return;
    if (!sc_setup_uart(dev, SC16IS750_CHANNEL_A, baud_A)) return;
    if (dev->channels == SC16IS750_DUAL_CHANNEL)
        (void)sc_setup_uart(dev, SC16IS750_CHANNEL_B, baud_B);
}

int SC16IS750_available(SC16IS750_t * dev, uint8_t channel)
{
	return SC16IS750_FIFOAvailableData(dev, channel);
}

int SC16IS750_read(SC16IS750_t * dev, uint8_t channel)
{
	if ( dev->peek_flag == 0) {
		return SC16IS750_ReadByte(dev, channel);
	} else {
		dev->peek_flag = 0;
		return dev->peek_buf;
	}
}

void SC16IS750_write(SC16IS750_t * dev, uint8_t channel, uint8_t val)
{
	SC16IS750_WriteByte(dev, channel, val);
}

void SC16IS750_pinMode(SC16IS750_t * dev, uint8_t pin, uint8_t i_o)
{
	SC16IS750_GPIOSetPinMode(dev, pin, i_o);
}

void SC16IS750_digitalWrite(SC16IS750_t * dev, uint8_t pin, uint8_t value)
{
	SC16IS750_GPIOSetPinState(dev, pin, value);
}

uint8_t SC16IS750_digitalRead(SC16IS750_t * dev, uint8_t pin)
{
	return SC16IS750_GPIOGetPinState(dev, pin);
}


uint8_t SC16IS750_ReadRegister(SC16IS750_t *dev, uint8_t channel, uint8_t reg_addr)
{
    uint8_t value = 0xFF;
    (void)SC16IS750_ReadRegisterChecked(dev, channel, reg_addr, &value);
    return value;
}

void SC16IS750_WriteRegister(SC16IS750_t *dev, uint8_t channel, uint8_t reg_addr, uint8_t val)
{
    (void)SC16IS750_WriteRegisterChecked(dev, channel, reg_addr, val);
}

int16_t SC16IS750_SetBaudrate(SC16IS750_t *dev, uint8_t channel, uint32_t baudrate)
{
    if (!baudrate || dev->crystal_freq <= 0) {
        dev->last_error = -23;
        return -1;
    }
    uint8_t mcr, lcr;
    if (!SC16IS750_ReadRegisterChecked(dev, channel, SC16IS750_REG_MCR, &mcr) ||
        !SC16IS750_ReadRegisterChecked(dev, channel, SC16IS750_REG_LCR, &lcr)) return -1;
    const uint32_t divisor_freq = (uint32_t)dev->crystal_freq / ((mcr & 0x80u) ? 4u : 1u);
    const uint32_t target = baudrate * 16u;
    if (target > divisor_freq || !target) {
        dev->last_error = -24;
        return -1;
    }
    const uint32_t divisor = (divisor_freq + target / 2u) / target;
    if (!divisor || divisor > 65535u) {
        dev->last_error = -25;
        return -1;
    }
    if (!SC16IS750_WriteRegisterChecked(dev, channel, SC16IS750_REG_LCR, lcr | 0x80u)) return -1;
    if (!SC16IS750_WriteRegisterChecked(dev, channel, SC16IS750_REG_DLL, (uint8_t)divisor) ||
        !SC16IS750_WriteRegisterChecked(dev, channel, SC16IS750_REG_DLH, (uint8_t)(divisor >> 8))) {
        return -1;
    }
    if (!SC16IS750_WriteRegisterChecked(dev, channel, SC16IS750_REG_LCR, lcr & 0x7Fu)) return -1;
    const uint32_t actual_baud = divisor_freq / (16u * divisor);
    return (int16_t)((int32_t)(actual_baud * 1000u / baudrate) - 1000);
}

void SC16IS750_SetLine(SC16IS750_t *dev, uint8_t channel, uint8_t data_length,
                        uint8_t parity_select, uint8_t stop_length)
{
    uint8_t lcr;
    if (!SC16IS750_ReadRegisterChecked(dev, channel, SC16IS750_REG_LCR, &lcr)) return;
    lcr &= 0xC0u;
    lcr |= data_length >= 5 && data_length <= 8 ? (data_length - 5u) : 3u;
    if (stop_length == 2u) lcr |= 0x04u;
    if (parity_select == 1u) lcr |= 0x08u;
    else if (parity_select == 2u) lcr |= 0x18u;
    else if (parity_select == 3u) lcr |= 0x28u;
    else if (parity_select == 4u) lcr |= 0x38u;
    (void)SC16IS750_WriteRegisterChecked(dev, channel, SC16IS750_REG_LCR, lcr);
}

void SC16IS750_GPIOSetPinMode(SC16IS750_t * dev, uint8_t pin_number, uint8_t i_o)
{
	uint8_t temp_iodir;

	temp_iodir = SC16IS750_ReadRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IODIR);
	if ( i_o != 0 ) {
		temp_iodir |= (0x01 << pin_number);
	} else {
		temp_iodir &= (uint8_t)~(0x01 << pin_number);
	}

	SC16IS750_WriteRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IODIR, temp_iodir);
	return;
}

void SC16IS750_GPIOSetPinState(SC16IS750_t * dev, uint8_t pin_number, uint8_t pin_state)
{
	uint8_t temp_iostate;

	temp_iostate = SC16IS750_ReadRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IOSTATE);
	if ( pin_state == 1 ) {
		temp_iostate |= (0x01 << pin_number);
	} else {
		temp_iostate &= (uint8_t)~(0x01 << pin_number);
	}

	SC16IS750_WriteRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IOSTATE, temp_iostate);
	return;
}


uint8_t SC16IS750_GPIOGetPinState(SC16IS750_t * dev, uint8_t pin_number)
{
	uint8_t temp_iostate;

	temp_iostate = SC16IS750_ReadRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IOSTATE);
	if ( ( temp_iostate & (0x01 << pin_number) ) == 0 ) {
		return 0;
	}
	return 1;
}

uint8_t SC16IS750_GPIOGetPortState(SC16IS750_t * dev)
{

	return SC16IS750_ReadRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IOSTATE);

}

void SC16IS750_GPIOSetPortMode(SC16IS750_t * dev, uint8_t port_io)
{
	SC16IS750_WriteRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IODIR, port_io);
	return;
}

void SC16IS750_GPIOSetPortState(SC16IS750_t * dev, uint8_t port_state)
{
	SC16IS750_WriteRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IOSTATE, port_state);
	return;
}

void SC16IS750_SetPinInterrupt(SC16IS750_t * dev, uint8_t io_int_ena)
{
	SC16IS750_WriteRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IOINTENA, io_int_ena);
	return;
}

void SC16IS750_ResetDevice(SC16IS750_t *dev)
{
    uint8_t control;
    if (!SC16IS750_ReadRegisterChecked(dev, SC16IS750_CHANNEL_A,
                                      SC16IS750_REG_IOCONTROL, &control)) return;
    (void)SC16IS750_WriteRegisterChecked(dev, SC16IS750_CHANNEL_A,
                                         SC16IS750_REG_IOCONTROL, control | 0x08u);
}

void SC16IS750_ModemPin(SC16IS750_t * dev, uint8_t gpio) //gpio == 0, gpio[7:4] are modem pins, gpio == 1 gpio[7:4] are gpios
{
	uint8_t temp_iocontrol;

	temp_iocontrol = SC16IS750_ReadRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IOCONTROL);
	if ( gpio == 0 ) {
		temp_iocontrol |= 0x02;
	} else {
		temp_iocontrol &= 0xFD;
	}
	SC16IS750_WriteRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IOCONTROL, temp_iocontrol);

	return;
}

void SC16IS750_GPIOLatch(SC16IS750_t * dev, uint8_t latch)
{
	uint8_t temp_iocontrol;

	temp_iocontrol = SC16IS750_ReadRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IOCONTROL);
	if ( latch == 0 ) {
		temp_iocontrol &= 0xFE;
	} else {
		temp_iocontrol |= 0x01;
	}
	SC16IS750_WriteRegister(dev, SC16IS750_CHANNEL_BOTH, SC16IS750_REG_IOCONTROL, temp_iocontrol);

	return;
}

void SC16IS750_InterruptControl(SC16IS750_t * dev, uint8_t channel, uint8_t int_ena)
{
	SC16IS750_WriteRegister(dev, channel, SC16IS750_REG_IER, int_ena);
}

uint8_t SC16IS750_InterruptPendingTest(SC16IS750_t * dev, uint8_t channel)
{
	return (SC16IS750_ReadRegister(dev, channel, SC16IS750_REG_IIR) & 0x01);
}

int16_t SC16IS750_InterruptEventTest(SC16IS750_t * dev, uint8_t channel)
{
	uint8_t irq_src;

	irq_src = SC16IS750_ReadRegister(dev, channel, SC16IS750_REG_IIR);
	//irq_src = (irq_src >> 1);
	//irq_src &= 0x3F;
	irq_src &= 0x3E;

	switch (irq_src) {
		case 0x06:			//Receiver Line Status Error
			return SC16IS750_RECEIVE_LINE_STATUS_ERROR;
		case 0x0c:			//Receiver time-out interrupt
			return SC16IS750_RECEIVE_TIMEOUT_INTERRUPT;
		case 0x04:			//RHR interrupt
			return SC16IS750_RHR_INTERRUPT;
		case 0x02:			//THR interrupt
			return SC16IS750_THR_INTERRUPT;
		case 0x00:			//modem interrupt;
			return SC16IS750_MODEM_INTERRUPT;
		case 0x30:			//input pin change of state
			return SC16IS750_INPUT_PIN_CHANGE_STATE;
		case 0x10:			//XOFF
			return SC16IS750_RECEIVE_XOFF;
		case 0x20:			//CTS,RTS
			return SC16IS750_CTS_RTS_CHANGE;
		default:
			return -1;
	}
	return -1;
}

void SC16IS750_FIFOEnable(SC16IS750_t *dev, uint8_t channel, uint8_t enabled)
{
    SC16IS750_WriteRegister(dev, channel, SC16IS750_REG_FCR, enabled ? 0x07u : 0u);
}

void SC16IS750_FIFOReset(SC16IS750_t * dev, uint8_t channel, uint8_t rx_fifo)
{
	uint8_t temp_fcr;

	temp_fcr = SC16IS750_ReadRegister(dev, channel, SC16IS750_REG_FCR);

	if (rx_fifo == 0){
		temp_fcr |= 0x04;
	} else {
		temp_fcr |= 0x02;
	}
	SC16IS750_WriteRegister(dev, channel, SC16IS750_REG_FCR, temp_fcr);

	return;

}

void SC16IS750_FIFOSetTriggerLevel(SC16IS750_t * dev, uint8_t channel, uint8_t rx_fifo, uint8_t length)
{
	uint8_t temp_reg;

	temp_reg = SC16IS750_ReadRegister(dev, channel, SC16IS750_REG_MCR);
	temp_reg |= 0x04;
	SC16IS750_WriteRegister(dev, channel, SC16IS750_REG_MCR, temp_reg); //SET MCR[2] to '1' to use TLR register or trigger level control in FCR register

	temp_reg = SC16IS750_ReadRegister(dev, channel, SC16IS750_REG_EFR);
	SC16IS750_WriteRegister(dev, channel, SC16IS750_REG_EFR, temp_reg|0x10); //set ERF[4] to '1' to use the  enhanced features
	if (rx_fifo == 0) {
		SC16IS750_WriteRegister(dev, channel, SC16IS750_REG_TLR, length<<4); //Tx FIFO trigger level setting
	} else {
		SC16IS750_WriteRegister(dev, channel, SC16IS750_REG_TLR, length);	 //Rx FIFO Trigger level setting
	}
	SC16IS750_WriteRegister(dev, channel, SC16IS750_REG_EFR, temp_reg); //restore EFR register

	return;
}

uint8_t SC16IS750_FIFOAvailableData(SC16IS750_t * dev, uint8_t channel)
{
#ifdef	SC16IS750_DEBUG_PRINT
	printf("=====Available data:");
	printf("%x\n", SC16IS750_ReadRegister(dev, channel, SC16IS750_REG_RXLVL));
#endif
	return SC16IS750_ReadRegister(dev, channel, SC16IS750_REG_RXLVL);
	//return SC16IS750_ReadRegister(dev, SC16IS750_REG_LSR) & 0x01;
}

uint8_t SC16IS750_FIFOAvailableSpace(SC16IS750_t * dev, uint8_t channel)
{
	return SC16IS750_ReadRegister(dev, channel, SC16IS750_REG_TXLVL);
}

void SC16IS750_WriteByte(SC16IS750_t *dev, uint8_t channel, uint8_t val)
{
    const uint64_t deadline = time_us_64() + 12000u;
    do {
        uint8_t lsr;
        if (!SC16IS750_ReadRegisterChecked(dev, channel, SC16IS750_REG_LSR, &lsr)) return;
        if ((lsr & 0x20u) != 0) {
            SC16IS750_WriteRegister(dev, channel, SC16IS750_REG_THR, val);
            return;
        }
    } while (time_us_64() < deadline);
    dev->last_error = -21;
}

int SC16IS750_ReadByte(SC16IS750_t * dev, uint8_t channel)
{
	volatile uint8_t val;
	if (SC16IS750_FIFOAvailableData(dev, channel) == 0) {
#ifdef	SC16IS750_DEBUG_PRINT
		printf("No data available\n");
#endif
		return -1;

	} else {

#ifdef	SC16IS750_DEBUG_PRINT
		printf("***********Data available***********\n");
#endif
		val = SC16IS750_ReadRegister(dev, channel, SC16IS750_REG_RHR);
		return val;
	}


}

void SC16IS750_EnableTransmit(SC16IS750_t * dev, uint8_t channel, uint8_t tx_enable)
{
	uint8_t temp_efcr;
	temp_efcr = SC16IS750_ReadRegister(dev, channel, SC16IS750_REG_EFCR);
	if ( tx_enable == 0) {
		temp_efcr |= 0x04;
	} else {
		temp_efcr &= 0xFB;
	}
	SC16IS750_WriteRegister(dev, channel, SC16IS750_REG_EFCR, temp_efcr);

	return;
}

uint8_t SC16IS750_ping(SC16IS750_t *dev)
{
    uint8_t original, probe;
    const uint8_t selector = SC16IS750_REG_SPR << 3;
    if (!SC16IS750_ReadRegisterChecked(dev, SC16IS750_CHANNEL_A, SC16IS750_REG_SPR, &original))
        return 0;
    const uint8_t patterns[] = {0x55u, 0xAAu};
    bool ok = true;
    for (unsigned i = 0; i < sizeof(patterns); ++i) {
        if (!SC16IS750_WriteRegisterChecked(dev, SC16IS750_CHANNEL_A, SC16IS750_REG_SPR, patterns[i]) ||
            !SC16IS750_ReadRegisterChecked(dev, SC16IS750_CHANNEL_A, SC16IS750_REG_SPR, &probe)) {
            ok = false;
            break;
        }
        if (probe != patterns[i]) {
            sc_error(dev, "scratch-mismatch", selector, -30);
            ok = false;
            break;
        }
    }
    const int saved_error = dev->last_error;
    const uint8_t saved_selector = dev->last_selector;
    const char *saved_phase = dev->last_phase;
    const bool can_restore = ok || SC16IS750_BusSetup(dev);
    const bool restored = can_restore && SC16IS750_WriteRegisterChecked(dev, SC16IS750_CHANNEL_A, SC16IS750_REG_SPR, original) &&
        SC16IS750_ReadRegisterChecked(dev, SC16IS750_CHANNEL_A, SC16IS750_REG_SPR, &probe);
    if (!ok) {
        sc_error(dev, saved_phase, saved_selector, saved_error);
        return 0;
    }
    if (!restored) return 0;
    if (probe != original) return sc_error(dev, "scratch-restore", selector, -31);
    return 1;
}

void SC16IS750_setTimeout(SC16IS750_t * dev, uint32_t time_out)
{
	dev->timeout = time_out;
}

size_t SC16IS750_readBytes(SC16IS750_t * dev, uint8_t channel, char *buffer, size_t length)
{
	size_t count=0;
	int16_t tmp;
	uint8_t _channel;

	while (count < length) {
		tmp = SC16IS750_readwithtimeout(dev, &_channel);
		if (tmp < 0) {
			break;
		}
		if (_channel == channel) {
			*buffer++ = (char)tmp;
			count++;
		}
	}

	return count;
}

int16_t SC16IS750_readwithtimeout(SC16IS750_t * dev, uint8_t * channel)
{
	int16_t tmp;
	uint32_t time_stamp;
	time_stamp = to_ms_since_boot(get_absolute_time());
	do {
		*channel = SC16IS750_CHANNEL_A;
		tmp = SC16IS750_read(dev, SC16IS750_CHANNEL_A);
		if (tmp >= 0) return tmp;
		if (dev->channels == SC16IS750_DUAL_CHANNEL) {
			*channel = SC16IS750_CHANNEL_B;
			tmp = SC16IS750_read(dev, SC16IS750_CHANNEL_B);
			if (tmp >= 0) return tmp;
		}
	} while(to_ms_since_boot(get_absolute_time()) - time_stamp < dev->timeout);
	return -1;	 // -1 indicates timeout
}

void SC16IS750_flush(SC16IS750_t *dev, uint8_t channel)
{
    const uint64_t deadline = time_us_64() + 12000u;
    do {
        uint8_t lsr;
        if (!SC16IS750_ReadRegisterChecked(dev, channel, SC16IS750_REG_LSR, &lsr)) return;
        if (lsr & 0x40u) return;
    } while (time_us_64() < deadline);
    dev->last_error = -22;
}

int SC16IS750_peek(SC16IS750_t * dev, uint8_t channel)
{
	if ( dev->peek_flag == 0 ) {
		dev->peek_buf = SC16IS750_ReadByte(dev, channel);
		if ( dev->peek_buf >= 0 ) {
			dev->peek_flag = 1;
		}
	}

	return dev->peek_buf;

}

