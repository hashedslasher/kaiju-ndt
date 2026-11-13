# DS18B20 (native Pico GPIO20) and Celsius-to-Fahrenheit GUI display

The supplied `Kaiju.kicad_sch` routes `Pico_GPIO20` to DS18B20 `DQ`
through the **Si8663BB-AS1 A3 -> B3 channel (pins 4 -> 13)**. This
is a **one-way push-pull digital isolator channel**. The DS18B20 uses
bidirectional, open-drain 1-Wire signaling, so **the currently drawn
hardware cannot read the sensor**. The MCU can transmit on GPIO20, but
sensor data will not return to that GPIO. Software cannot correct this.

Before expecting valid readings, replace this connection with a suitable
bidirectional, open-drain 1-Wire-capable isolation circuit (or put the sensor
on the Pico side with an appropriate, direct DQ connection). Ensure there is
an appropriate pull-up on the sensor-side DQ line and that VDD and GND are
connected; the firmware does not support parasite-powered DS18B20 devices.
Do not simply tie opposite-direction push-pull digital isolator outputs
together on DQ. GPIO20 is not reused by the limit switch firmware.

## Implementation

- `firmware/src/gantry/temperature.c` is a native GPIO20 1-Wire master.
  It sends the reset, Skip ROM, Convert T, and Read Scratchpad sequences
  using open-drain direction changes, microsecond timing and CRC8.
- The existing USB serial `temp` command returns `OK temp=pending` during
  conversion, then `OK temp_c=23.25` with a signed Celsius value. A missing
  sensor or invalid scratchpad results in `ERR TEMP ...`.
- `python-tools/acq.py` converts Celsius to Fahrenheit and displays
  **`{number} F`** (e.g. `72.50 F`) in a read-only box on the toolbar,
  without an additional label. The box stays blank until a valid reading.
  GUI temperature polling is skipped during C-scans. Firmware also defers 1-Wire transactions while motors are active, to avoid delaying expander-based limit checks.

## Y limit changes

- `LIMIT_Y` now uses SC16IS752 GPIO0, active low, with GPIO-change interrupts
  enabled and a latched input. The Pico observes the SC interrupt on GPIO27.
- The limit is additionally polled every 1 ms during motion and every
  20 ms at rest; communication failures stop Y motion.
- `LIMIT_X` remains a native Pico interrupt on GPIO26.
- The SC16IS752 input needs an appropriate pull-up in hardware. Verify
  the Y limit reports correctly with `position` before enabling motion.

## Bench check

1. Before testing DQ, fix the one-way Si8663BB channel; verify DQ is
   bidirectional and has the required pull-up.
2. Issue `tmc status`, then press/release the Y limit and check `position`
   (`limit_y0=0` released, `limit_y0=1` pressed).
3. Send `temp`; the first response should be `OK temp=pending`. Send again
   after 750 ms, expecting `OK temp_c=...`.
4. Check the numeric Fahrenheit box, temperature agreement with a known
   thermometer, and Y stop behavior at low motor speeds.

The code has not been validated on an actual Pico 2, isolator, or sensor.
