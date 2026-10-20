#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

cmake -S . -B build-pico2-dsp -DFETCHCONTENT_BASE_DIR="${PWD}/.deps"
cmake --build build-pico2-dsp --parallel 4

mkdir -p dist
cp build-pico2-dsp/adc-pulse.uf2 dist/pic0rick-pico2-dsp.uf2
printf 'Built %s\n' "${PWD}/dist/pic0rick-pico2-dsp.uf2"
