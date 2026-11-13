#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include "positioning.h"
#include "bridge.h"
static uint64_t now;
static bool bridge_ok=true;
static bool irq;
static bool y_moving;
static int y_stops;
static uint8_t gpio_state=1u;
uint64_t time_us_64(void) {return now;}
uint32_t save_and_disable_interrupts(void) {return 0;}
void restore_interrupts(uint32_t v) {(void)v;}
void gpio_init(unsigned pin) {assert(pin==26u);}
void gpio_set_dir(unsigned pin, bool output) {assert(pin==26u&&!output);}
void gpio_pull_up(unsigned pin) {assert(pin==26u);}
int gpio_get(unsigned pin) {assert(pin==26u);return 1;}
void gpio_set_irq_enabled_with_callback(unsigned pin, uint32_t events, bool enabled, void (*cb)(unsigned, uint32_t)) {
 assert(pin==26u && events==(4u|8u) && enabled && cb);
}
bool bridge_gpio_read(uint8_t *state) {if(!bridge_ok)return false;*state=gpio_state;irq=false;return true;}
bool bridge_irq_asserted(void) {return irq;}
bool motor_any_active(void) {return y_moving;}
bool motor_stop_if_direction(position_axis_t axis, bool toward) {
 assert(toward==false);
 if (axis!=POSITION_AXIS_Y || !y_moving)return false;
 y_moving=false;y_stops++;return true;
}
void stop_y(const char *args) {(void)args;if(y_moving){y_moving=false;y_stops++;}}
int32_t motor_inflight_step_delta(position_axis_t axis,bool *exact) {(void)axis;*exact=true;return 0;}
int main(void) {
 positioning_init();
 assert(positioning_limit_y_ready()&&!positioning_switch_active(POSITION_AXIS_Y));
 assert(!positioning_limit_blocked(POSITION_AXIS_Y,false));
 positioning_begin_homing(POSITION_AXIS_Y);
 y_moving=true; gpio_state=0;irq=true;
 positioning_service();
 assert(y_stops==1&&!y_moving&&positioning_switch_active(POSITION_AXIS_Y));
 assert(positioning_is_homed(POSITION_AXIS_Y));
 assert(positioning_limit_blocked(POSITION_AXIS_Y,false));
 gpio_state=1;irq=true;positioning_service();
 assert(!positioning_switch_active(POSITION_AXIS_Y));
 bridge_ok=false; y_moving=true;now+=1001;positioning_service();
 assert(y_stops==2&&!y_moving&&!positioning_limit_y_ready());
 assert(positioning_steps_available(POSITION_AXIS_Y,true)==0u);
 bridge_ok=true; now+=20000;positioning_service();
 assert(positioning_limit_y_ready());
 puts("PASS: expander GPIO0 Y limit, interrupt service, fail-safe and recovery");
}
