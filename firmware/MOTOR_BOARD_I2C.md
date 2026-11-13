# Isolated motor daughterboard: SC16IS752 and TMC2209

## Wiring from Kaiju.kicad_sch (2026-11-13)

| Signal | Pico GPIO | Daughterboard |
|---|---:|---|
| I2C0 SDA | 28 | ISO1642 SDA1 -> SC16IS752 SDA |
| I2C0 SCL | 21 | ISO1642 SCL1 -> SC16IS752 SCL |
| X step | 18 | SI8663 A1 -> B1 -> X1/X2 STEP |
| Y step | 22 | SI8663 A2 -> B2 -> Y1/Y2 STEP |
| Z step | 19 | SI8663 A3 -> B3 -> Z STEP |
| X primary limit | 26 | SI8663 B4 -> A4 |
| DS18B20 DQ (1-Wire) | 20 | SI8663 A3 -> B3 (**one-way, not suitable for 1-Wire**) |
| SC interrupt | 27 | SI8663 B6 -> A6 (active low, Y limit interrupt) |

The SC16IS752 is in I2C mode, A0=A1=0, so its 7-bit address is **0x4D**. The on-board crystal is 14.7456 MHz. Both UARTs are configured 115200 baud, 8N1 (divisor 8); I2C is 400 kHz.

| SC16IS752 GPIO | Function |
|---|---|
| GPIO0 | Y primary limit input (active-low; polled and interrupt-enabled) |
| GPIO1 | Z limit input (status only) |
| GPIO2 | Y2 limit input (status only) |
| GPIO3 | X2 limit input (status only) |
| GPIO4 | All motor enable pins, LOW enables |
| GPIO5 | Z direction |
| GPIO6 | Y direction |
| GPIO7 | X direction |

| Driver | Bridge UART | TMC2209 slave address (MS2:MS1) |
|---|---|---:|
| X1 (U7) | A | 0 |
| X2 (U8) | A | 1 |
| Y1 (U9) | A | 2 |
| Y2 (U10) | B | 0 |
| Z (U11) | B | 1 |

The factory BTT TMC2209 V1.3 UART routing uses its header pin 4 (labeled RX in this schematic). Its alternate header pin 5 is intentionally unconnected in the supplied schematic. Verify the module's onboard UART selection resistors are still in their factory positions.

## Boot behavior

1. I2C0 is initialized. The SC16IS752 scratch register is written/read to confirm the bridge responds.
2. Shared ENABLE is held high (drivers disabled). GPIO5-7 are configured for direction.
3. Both SC16IS752 UARTs are configured with the crystal-derived divisor.
4. All five TMC2209 drivers receive `SLAVECONF.SENDDELAY=2` to support multiple slaves sharing a UART. They are identified by the `IOIN` version field, then their `GCONF.pdn_disable`, `GCONF.mstep_reg_select`, and `CHOPCONF.MRES` fields are configured and read back.
5. The result is 1/8 native microstepping on **all five** drivers. The driver's analog current-scale selection and current configuration are preserved. If any driver fails, movement is blocked; retry via `tmc setup`.

The PIO programs generate only step pulses. Direction is applied via bridge GPIO before any motor step DMA starts. The primary X limit switch uses a direct Pico interrupt. The primary Y switch is connected to SC16IS752 GPIO0 and checked from the main motor-service loop on bridge IRQ and periodic polling (1 ms during motion, 20 ms idle). If the expander read fails, Y steps are stopped and further Y movement is inhibited until communication recovers. This input is **not** equivalent to an instantaneous native GPIO hardware limit; retain an independent emergency stop and verify braking distance before high-speed motion. Additional X2/Y2/Z switches can be inspected via the SC GPIO state but are **not yet enforced as travel limits** (their end-of-travel polarity/direction hasn't been verified).

## Serial commands (over the existing USB CDC connection)

```
tmc status
tmc setup
tmc read x1 0x06
tmc read x2 0x06
tmc read y1 0x06
tmc read y2 0x06
tmc read z 0x06
tmc read x1 0x00
tmc read x1 0x6C
```

`tmc status` returns `online_mask=0x1F` if all five were configured at boot. The five `IOIN` responses should each have version `0x21` in bits 31:24. The `tmc write` command directly changes driver registers and is intended for experienced users: changing motor current, chopper, or direction settings can cause unintended motion or overheating. It queues the UART write without receiving a TMC ACK; use a subsequent read to confirm the value. `tmc setup` reapplies the default microstep selection (and may overwrite user-changed microstep settings).

## Hardware bring-up order

- With the 24 V motor supply off, verify isolation, daughterboard 3.3 V rails, pin mapping, and polarity using a multimeter.
- Start with Pico USB plus isolated-side 3.3 V only if your specific daughterboard and TMC modules support this configuration. Verify the SC16IS752 responds and `tmc status` sees a bridge; the TMC drivers may require their motor power supply to respond correctly.
- With motors safely disconnected mechanically or gantry away from its stops, power the motor stage and run `tmc setup`, then read `IOIN` for **each** of the five drivers.
- Confirm `tmc status` shows mask `0x1F` before issuing movement commands. Confirm each direction using a very small, slow jog; then verify native X and expander Y end-stop behavior before homing. Observe `position` reporting `limit_y0=1` when the Y switch is pressed.
- Observe current and heating while operating. This firmware does not automatically select or change an IRUN/IHOLD current setpoint.

## Build

From `firmware/`, use `./build.sh` in the usual Pico SDK / CMSIS-DSP build environment. This archive excludes stale UF2 outputs and build caches: rebuild before flashing the Pico 2. The firmware is configured for `PICO_BOARD=pico2`.

The included SC16IS752 and pico_trinamic directories under `src/external/` were not copied directly into the firmware build because their provided implementations target Linux/wiringPi or direct Pico UART, rather than the Pico 2 -> I2C -> SC16IS752 -> TMC2209 architecture. The native firmware bridge is implemented in `src/gantry/bridge.c` and `bridge.h`.

Host-only I2C/UART simulation tests were run, but an RP2350 firmware build and physical-board validation were **not** possible in the current environment.
