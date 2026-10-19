{ lib, stdenv, cmake, gcc-arm-embedded, local-pico-sdk, picotool, python3}:

stdenv.mkDerivation {
  pname = "pico-firmware";
  version = "0.1.11-fork";
  src = ./.;

  nativeBuildInputs = [ 
    cmake 
    gcc-arm-embedded 
    python3
    picotool
  ];

  PICO_SDK_PATH = "${local-pico-sdk}/lib/pico-sdk";
  CMAKE_C_COMPILER = "${gcc-arm-embedded}/bin/arm-none-eabi-gcc";
  CMAKE_CXX_COMPILER = "${gcc-arm-embedded}/bin/arm-none-eabi-g++";

  dontUseCmakeConfigure = true;

  buildPhase = ''
    # The only supported board is Pico 2 / RP2350 with onboard DSP.
    cmake -B build-pico2-dsp -DPICO_BOARD=pico2 \
      -DFETCHCONTENT_BASE_DIR="$PWD/.deps" \
      -DCMAKE_SYSTEM_NAME=Generic \
      -DCMAKE_C_COMPILER=$CMAKE_C_COMPILER \
      -DCMAKE_CXX_COMPILER=$CMAKE_CXX_COMPILER
    cmake --build build-pico2-dsp -j$NIX_BUILD_CORES
  '';

  installPhase = ''
    mkdir -p $out/bin
    cp build-pico2-dsp/adc-pulse.uf2 $out/bin/pic0rick-pico2-dsp.uf2
  '';
}
