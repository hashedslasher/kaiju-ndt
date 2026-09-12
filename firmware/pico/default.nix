{ lib, stdenv, cmake, gcc-arm-embedded, local-pico-sdk, python3 }:

stdenv.mkDerivation {
  pname = "pico-firmware";
  version = "1.0.0";
  src = ./.;

  nativeBuildInputs = [ 
    cmake 
    gcc-arm-embedded 
    python3 
  ];

  PICO_SDK_PATH = "${local-pico-sdk}/lib/pico-sdk";
  CMAKE_C_COMPILER = "${gcc-arm-embedded}/bin/arm-none-eabi-gcc";
  CMAKE_CXX_COMPILER = "${gcc-arm-embedded}/bin/arm-none-eabi-g++";

  cmakeFlags = [
    "-DCMAKE_SYSTEM_NAME=Generic"
  ];
}
