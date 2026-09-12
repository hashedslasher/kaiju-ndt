set -e

# rp2040
cmake -B build/build2040 -DPICO_BOARD=pico
cmake --build build/build2040 -j4
cp build/build2040/adc-pulse.uf2 rp2040.uf2

# rp2350
cmake -B build/build2350 -DPICO_BOARD=pico2
cmake --build build/build2350 -j4
cp build/build2350/adc-pulse.uf2 rp2350.uf2
