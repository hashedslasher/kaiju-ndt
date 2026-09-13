{ lib, stdenv, cmake, gcc-arm-embedded, local-pico-sdk, picotool, python3}:

stdenv.mkDerivation {
  pname = "pico-firmware";
  version = "1.0.0";
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

  # Prevent Nix from running a default single-target CMake configure pass
  dontUseCmakeConfigure = true;

  buildPhase = ''
    # rp2040
    cmake -B build2040 -DPICO_BOARD=pico \
      -DCMAKE_SYSTEM_NAME=Generic \
      -DCMAKE_C_COMPILER=$CMAKE_C_COMPILER \
      -DCMAKE_CXX_COMPILER=$CMAKE_CXX_COMPILER
    cmake --build build2040 -j$NIX_BUILD_CORES

    # rp2350
    cmake -B build2350 -DPICO_BOARD=pico2 \
      -DCMAKE_SYSTEM_NAME=Generic \
      -DCMAKE_C_COMPILER=$CMAKE_C_COMPILER \
      -DCMAKE_CXX_COMPILER=$CMAKE_CXX_COMPILER
    cmake --build build2350 -j$NIX_BUILD_CORES
  '';

  installPhase = ''
    mkdir -p $out/bin
    cp build2040/adc-pulse.uf2 $out/bin/rp2040.uf2
    cp build2350/adc-pulse.uf2 $out/bin/rp2350.uf2
  '';
}
