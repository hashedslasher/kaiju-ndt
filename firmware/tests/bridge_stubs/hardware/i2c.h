#ifndef MOCK_I2C_H
#define MOCK_I2C_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
typedef unsigned int uint;
typedef struct {int unused;} i2c_inst_t;
extern i2c_inst_t *i2c0;
uint i2c_init(i2c_inst_t *, uint);
int i2c_write_timeout_us(i2c_inst_t *, uint8_t, const uint8_t *, size_t, bool, uint);
int i2c_read_timeout_us(i2c_inst_t *, uint8_t, uint8_t *, size_t, bool, uint);
#endif
