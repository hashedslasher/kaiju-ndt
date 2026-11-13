Host-only simulation tests (from firmware/):

cc -std=c11 -Wall -Wextra -Werror -Itests/bridge_stubs -Isrc/gantry src/gantry/bridge.c tests/test_bridge_host.c -o /tmp/kaiju_bridge && /tmp/kaiju_bridge
cc -std=c11 -Wall -Wextra -Werror -Itests/temperature_stubs -Isrc/gantry src/gantry/temperature.c tests/test_temperature_gpio20.c -o /tmp/kaiju_temp && /tmp/kaiju_temp
cc -std=c11 -Wall -Wextra -Werror -Itests/positioning_stubs -Isrc/gantry -include tests/positioning_stubs/motors_compat.h src/gantry/positioning.c tests/test_positioning_expander.c -o /tmp/kaiju_limits && /tmp/kaiju_limits

The tests do not replace building firmware for RP2350 or testing the actual daughterboard.
