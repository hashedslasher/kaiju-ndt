cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# The only supported target is a Raspberry Pi Pico 2 (RP2350).
# Set before importing the Pico SDK so cached builds cannot select RP2040.
set(PICO_BOARD pico2 CACHE STRING "Raspberry Pi Pico 2" FORCE)

# Keep compatibility with Raspberry Pi's Pico VS Code extension.
if(WIN32)
    set(USERHOME $ENV{USERPROFILE})
else()
    set(USERHOME $ENV{HOME})
endif()
set(sdkVersion 2.3.0)
set(toolchainVersion 14_2_Rel1)
set(picotoolVersion 2.3.0)
set(picoVscode ${USERHOME}/.pico-sdk/cmake/pico-vscode.cmake)
if(EXISTS ${picoVscode})
    include(${picoVscode})
endif()

include(pico_sdk_import.cmake)
project(adc-pulse C CXX ASM)
pico_sdk_init()

set(PIC0RICK_FIRMWARE_VERSION "0.1.11-fork" CACHE STRING "Firmware version")

# CMSIS-DSP implements the RP2350 float32 Hilbert-envelope pipeline.
include(FetchContent)
FetchContent_Declare(
    CMSISDSP
    GIT_REPOSITORY https://github.com/ARM-software/CMSIS-DSP.git
    GIT_TAG v1.17.0
    GIT_SHALLOW TRUE
)
set(CMSISCORE
    ${PICO_SDK_PATH}/src/rp2_common/cmsis/stub/CMSIS/Core
    CACHE PATH "CMSIS Core headers" FORCE
)
set(DISABLEFLOAT16 ON CACHE BOOL "Disable CMSIS-DSP float16" FORCE)
FetchContent_MakeAvailable(CMSISDSP)

# Build only the DSP float32 transform sources required by the pipeline.
set_property(TARGET CMSISDSP PROPERTY EXCLUDE_FROM_ALL TRUE)
add_library(cmsisdsp_p0rk STATIC
    ${cmsisdsp_SOURCE_DIR}/Source/TransformFunctions/arm_bitreversal2.c
    ${cmsisdsp_SOURCE_DIR}/Source/TransformFunctions/arm_cfft_f32.c
    ${cmsisdsp_SOURCE_DIR}/Source/TransformFunctions/arm_cfft_init_f32.c
    ${cmsisdsp_SOURCE_DIR}/Source/TransformFunctions/arm_cfft_radix8_f32.c
    ${cmsisdsp_SOURCE_DIR}/Source/TransformFunctions/arm_rfft_fast_f32.c
    ${cmsisdsp_SOURCE_DIR}/Source/TransformFunctions/arm_rfft_fast_init_f32.c
    ${cmsisdsp_SOURCE_DIR}/Source/CommonTables/arm_common_tables.c
    ${cmsisdsp_SOURCE_DIR}/Source/CommonTables/arm_const_structs.c
)
target_include_directories(cmsisdsp_p0rk PUBLIC
    ${cmsisdsp_SOURCE_DIR}/Include
    ${CMSISCORE}/Include
)
target_include_directories(cmsisdsp_p0rk PRIVATE
    ${cmsisdsp_SOURCE_DIR}/PrivateInclude
)
target_compile_definitions(cmsisdsp_p0rk PUBLIC
    ARM_MATH_CM33
    DISABLEFLOAT16
)
target_compile_options(cmsisdsp_p0rk PRIVATE
    -O3
    -ffast-math
    -ffunction-sections
    -fdata-sections
)

add_library(p0rk_dsp STATIC
    src/dsp/dsp.c
    src/dsp/pipeline.c
    src/dsp/protocol.c
    src/hw/acquisition.c
    src/hw/dac.c
)
pico_generate_pio_header(p0rk_dsp ${CMAKE_CURRENT_LIST_DIR}/src/hw/acquisition.pio)
pico_generate_pio_header(p0rk_dsp ${CMAKE_CURRENT_LIST_DIR}/src/hw/pulser.pio)
target_include_directories(p0rk_dsp PUBLIC
    ${CMAKE_CURRENT_LIST_DIR}/src/dsp
    ${CMAKE_CURRENT_LIST_DIR}/src/hw
)
target_compile_definitions(p0rk_dsp PUBLIC
    ARM_MATH_CM33
    DISABLEFLOAT16
)
target_link_libraries(p0rk_dsp PUBLIC
    pico_stdlib
    pico_multicore
    pico_util
    hardware_pio
    hardware_dma
    hardware_clocks
    hardware_gpio
    hardware_spi
    cmsisdsp_p0rk
)

add_library(p0rk_gantry STATIC
    src/gantry/motors.c
    src/gantry/positioning.c
)
pico_generate_pio_header(p0rk_gantry ${CMAKE_CURRENT_LIST_DIR}/src/gantry/motors.pio)
target_include_directories(p0rk_gantry PUBLIC
    ${CMAKE_CURRENT_LIST_DIR}/src/gantry
)
target_link_libraries(p0rk_gantry PUBLIC
    pico_stdlib
    hardware_pio
    hardware_dma
    hardware_clocks
    hardware_gpio
)

# Raw TinyUSB (not SDK stdio_usb) carries text commands and binary frames.
add_executable(adc-pulse
    src/main_dsp.c
    src/dsp/usb_transport.c
    src/dsp/usb_descriptors.c
)
pico_set_program_name(adc-pulse "pic0rick-pico2-dsp")
pico_set_program_version(adc-pulse "${PIC0RICK_FIRMWARE_VERSION}")
pico_enable_stdio_uart(adc-pulse 0)
pico_enable_stdio_usb(adc-pulse 0)
target_include_directories(adc-pulse PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src/dsp
    ${CMAKE_CURRENT_LIST_DIR}/src/hw
)
target_compile_definitions(adc-pulse PRIVATE
    PIC0RICK_FIRMWARE_VERSION=\"${PIC0RICK_FIRMWARE_VERSION}\"
    U4RK_CMSIS_DSP_VERSION=\"1.17.0\"
)
target_link_libraries(adc-pulse PRIVATE
    pico_stdlib
    pico_bootrom
    pico_multicore
    pico_util
    hardware_pio
    hardware_dma
    hardware_clocks
    hardware_gpio
    hardware_spi
    tinyusb_device
    p0rk_dsp
    p0rk_gantry
)
pico_add_extra_outputs(adc-pulse)
