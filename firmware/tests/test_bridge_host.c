#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include "hardware/i2c.h"
#include "hardware/gpio.h"
#include "pico/stdlib.h"
#include "bridge.h"

static i2c_inst_t dev;
i2c_inst_t *i2c0 = &dev;
static int i2c_addr, clk, sda;
static uint8_t scratch=0x01, outputs=0xFF, directions, io_intena, io_control;
static uint8_t lcr[2],dll[2],dlh[2];
static uint8_t pos_channel,pos_reg;
static uint8_t rx[2][128];
static size_t rx_len[2];
static uint32_t regs[5][128];
static int packet_count, write_count;
static bool corrupt_reply;

uint i2c_init(i2c_inst_t *d,uint baud){assert(d==i2c0);assert(baud==400000u);return baud;}
void gpio_set_function(unsigned pin,unsigned function){assert(function==GPIO_FUNC_I2C);if(pin==28)sda++;if(pin==21)clk++;}
void gpio_pull_up(unsigned pin){(void)pin;}
void gpio_init(unsigned pin){assert(pin==27);}
void gpio_set_dir(unsigned pin,bool output){assert(pin==27);assert(!output);}
int gpio_get(unsigned pin){assert(pin==27);return 1;}
uint64_t time_us_64(void){static uint64_t t=0;t+=200;return t;}
void tight_loop_contents(void){}
void sleep_us(uint64_t delay){(void)delay;}
static uint8_t crc(const uint8_t *p,size_t n){uint8_t c=0;for(size_t i=0;i<n;i++){uint8_t v=p[i];for(int j=0;j<8;j++){bool x=((c>>7)^v)&1;c<<=1;if(x)c^=0x07;v>>=1;}}return c;}
static void append(unsigned channel,const uint8_t *p,size_t n){assert(rx_len[channel]+n<128);memcpy(rx[channel]+rx_len[channel],p,n);rx_len[channel]+=n;}
static void send_uart(unsigned channel,const uint8_t *data,size_t n){
 packet_count++;
 assert((n==4||n==8)&&data[0]==0x05&&data[n-1]==crc(data,n-1));
 append(channel,data,n);
 uint8_t addr=data[1];int m=-1;
 for(int i=0;i<TMC_COUNT;i++) if((i<3?0:1)==channel && ((i<3?i:i-3)==addr)) m=i;
 if(m<0)return;
 uint8_t r=data[2]&0x7F;
 if(n==8){
   regs[m][r]=((uint32_t)data[3]<<24)|((uint32_t)data[4]<<16)|((uint32_t)data[5]<<8)|data[6];
   write_count++;
 }else{
   uint32_t val=regs[m][r];
   uint8_t reply[8]={0x05,0xFF,r,val>>24,val>>16,val>>8,val,0};
   reply[7]=crc(reply,7);
   if(corrupt_reply)reply[7]^=1;
   append(channel,reply,8);
 }
}
int i2c_write_timeout_us(i2c_inst_t *d,uint8_t addr,const uint8_t *p,size_t n,bool nostop,uint timeout){
 assert(d==i2c0&&addr==0x4D&&n>=1&&timeout==3000u);
 i2c_addr=addr;
 if(nostop){assert(n==1);pos_reg=p[0]>>3;pos_channel=(p[0]>>1)&1;return n;}
 uint8_t reg=p[0]>>3,ch=(p[0]>>1)&1;
 if(reg==0&&n>1&&!(lcr[ch]&0x80)){send_uart(ch,p+1,n-1);return n;}
 assert(n==2);
 uint8_t value=p[1];
 if(reg==3)lcr[ch]=value;
 if(reg==0 && lcr[ch]&0x80)dll[ch]=value;
 if(reg==1 && lcr[ch]&0x80)dlh[ch]=value;
 if(reg==7)scratch=value;
 if(reg==0xA)directions=value;
 if(reg==0xC)io_intena=value;
 if(reg==0xE)io_control=value;
 if(reg==0xB)outputs=value;
 return n;
}
int i2c_read_timeout_us(i2c_inst_t *d,uint8_t addr,uint8_t *p,size_t n,bool nostop,uint timeout){
 assert(d==i2c0&&addr==0x4D&&n==1&&!nostop&&timeout==3000u);
 if(pos_reg==7)*p=scratch;
 else if(pos_reg==0x5)*p=0x60;
 else if(pos_reg==0x8)*p=64;
 else if(pos_reg==0x9)*p=rx_len[pos_channel];
 else if(pos_reg==0xB)*p=outputs;
 else if(pos_reg==0){assert(rx_len[pos_channel]>0);*p=rx[pos_channel][0];memmove(rx[pos_channel],rx[pos_channel]+1,--rx_len[pos_channel]);}
 else *p=0;
 return n;
}
int main(void){
 for(int i=0;i<TMC_COUNT;i++){
  regs[i][0x06]=0x21000000;
  regs[i][0x00]=0x01;
  regs[i][0x6C]=0x10400053;
 }
 assert(bridge_init());
 assert(sda==1&&clk==1&&i2c_addr==0x4D);
 assert(outputs==0x10&&directions==0xF0);
 assert(io_control==0x01&&io_intena==BRIDGE_GPIO_LIMIT_Y);
 assert(dll[0]==8 && dll[1]==8 && dlh[0]==0&&dlh[1]==0);
 assert(lcr[0]==0x03 && lcr[1]==0x03);
 for(int i=0;i<TMC_COUNT;i++){
  assert(tmc_configure_8_microsteps(i));
  assert(tmc_motor_online(i));
  assert((regs[i][0x00]&0xC0)==0xC0);
  assert(((regs[i][0x6C]>>24)&15)==5);
  assert(regs[i][0x03]==0x200);
 }
 assert(tmc_all_online());
 assert(bridge_set_direction(0,true));
 assert((outputs&0x80)!=0);
 assert(bridge_set_direction(2,true));
 assert((outputs&0x20)!=0);
 assert(bridge_set_enable(true)&&!(outputs&0x10));
 assert(bridge_set_enable(false)&&(outputs&0x10));
 assert(tmc_write(TMC_Y1,0x10,0x01020304));
 uint32_t val=0;
 assert(tmc_read(TMC_Y1,0x10,&val)&&val==0x01020304);
 corrupt_reply=true;
 assert(!tmc_read(TMC_Z,0x06,&val));
 assert(strcmp(bridge_error(),"TMC UART reply timeout or CRC mismatch")==0);
 printf("PASS: I2C 0x4D, 14.7456MHz UART A/B 115200, 5 addressed TMC2209s, CRC, GPIO direction/enable, timeout (%d UART packets, %d writes)\n",packet_count,write_count);
}
