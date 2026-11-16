#ifndef KAIJU_MOTOR_BRIDGE_H
#define KAIJU_MOTOR_BRIDGE_H

#include <stdbool.h>
#include <stdint.h>

#define BRIDGE_I2C_SDA_PIN 28u
#define BRIDGE_I2C_SCL_PIN 21u
#define BRIDGE_IRQ_PIN 27u
#define BRIDGE_I2C_ADDRESS 0x4Du
#define BRIDGE_CRYSTAL_HZ 14745600u
#define BRIDGE_UART_BAUD 115200u

#define BRIDGE_GPIO_LIMIT_Y2  (1u << 0)
#define BRIDGE_GPIO_LIMIT_X2  (1u << 1)
#define BRIDGE_GPIO_LIMIT_Z   (1u << 2)
#define BRIDGE_GPIO_LIMIT_Y   (1u << 3)
#define BRIDGE_GPIO_ENABLE    (1u << 4)
#define BRIDGE_GPIO_DIR_Z     (1u << 5)
#define BRIDGE_GPIO_DIR_Y     (1u << 6)
#define BRIDGE_GPIO_DIR_X     (1u << 7)

typedef enum {
    TMC_X1 = 0,
    TMC_X2,
    TMC_Y1,
    TMC_Y2,
    TMC_Z,
    TMC_COUNT
} tmc_motor_t;

bool bridge_init(void);
bool bridge_setup_motors(void);
bool bridge_i2c_test(uint8_t *iocontrol, uint32_t *hz);
bool bridge_ready(void);
bool bridge_set_enable(bool enabled);
bool bridge_set_direction(unsigned axis, bool level);
bool bridge_gpio_read(uint8_t *state);
bool bridge_irq_asserted(void);
const char *bridge_error(void);

bool tmc_read(tmc_motor_t motor, uint8_t reg, uint32_t *value);
bool tmc_write(tmc_motor_t motor, uint8_t reg, uint32_t value);
bool tmc_configure_8_microsteps(tmc_motor_t motor);
bool tmc_motor_online(tmc_motor_t motor);
bool tmc_all_online(void);
bool tmc_xy_online(void);
bool tmc_motion_ready(unsigned axis);
const char *tmc_motor_name(tmc_motor_t motor);
bool tmc_motor_from_name(const char *name, tmc_motor_t *motor);

#endif
