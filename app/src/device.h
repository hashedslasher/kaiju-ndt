#ifndef DEVICE_H

#define DEVICE_H

#include <string>

std::string findPort();
int write();
float sRead();
float read();
void dac(int x);
void pulse_adc_trig(int pon, int poff, int damp);

#endif
