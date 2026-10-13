# Non-blocking USB command parser for motor jogging

## Change

`src/main.c` now calls `poll_serial_commands()` instead of the blocking
`fast_serial_read_until()` path. The parser holds partial commands across
main-loop iterations, ignores CR characters for CRLF compatibility, rejects
an oversized line without executing a truncated command, and processes at
most one full command or 64 characters each main-loop iteration.

This lets `motor_service()` run while waiting for the next serial command,
so the firmware can refill the motor's 5,000-step DMA blocks.

The command syntax remains unchanged (`jog_x plus 2000`, `stop_x`,
`move_y minus 2000 100`, `start acq ...`, etc.). Commands are newline-ended.

## Build/flash

The old `rp2040.uf2` and `rp2350.uf2` were omitted deliberately: they were
built before this fix and DO NOT include it. Rebuild using the project's
`firmware/pico/build.sh` in a Pico SDK / ARM toolchain environment, or:

    cmake -S firmware/pico -B firmware/pico/build/build2040 -DPICO_BOARD=pico
    cmake --build firmware/pico/build/build2040 -j4

For Pico 2, set `-DPICO_BOARD=pico2` with a separate build folder.
Flash the newly produced `adc-pulse.uf2` for your board.

## Limitations

Acquisition operations (`pulse_adc_trigger` / `fast_serial_write`) can still
block the main loop while sampling or writing binary data over USB. If brief
motion interruptions persist during acquisition or at especially high step
frequencies, DMA chaining/interrupt-driven motor-block refill or an
asynchronous acquisition/write path should be implemented next.

Build and physical-motion validation still need to be performed on hardware.
