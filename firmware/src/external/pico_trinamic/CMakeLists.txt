# The supplied pico_trinamic project references Trinamic-library as a git
# submodule. Resolve it from that directory, or fetch it when using a ZIP.
set(TRINAMIC_VENDOR "${CMAKE_CURRENT_LIST_DIR}/Trinamic-library")
if(EXISTS "${TRINAMIC_VENDOR}/tmc2209.c" AND EXISTS "${TRINAMIC_VENDOR}/common.c")
    set(TRINAMIC_SRC "${TRINAMIC_VENDOR}")
else()
    include(FetchContent)
    FetchContent_Declare(kaiju_trinamic
        GIT_REPOSITORY https://github.com/terjeio/Trinamic-library.git
        GIT_TAG master
        GIT_SHALLOW TRUE
    )
    FetchContent_GetProperties(kaiju_trinamic)
    if(NOT kaiju_trinamic_POPULATED)
        FetchContent_Populate(kaiju_trinamic)
    endif()
    set(TRINAMIC_SRC "${kaiju_trinamic_SOURCE_DIR}")
endif()

add_library(pico_trinamic STATIC
    ${TRINAMIC_SRC}/common.c
    ${TRINAMIC_SRC}/tmc2209.c
    ${CMAKE_CURRENT_LIST_DIR}/tmc_uart.c
)
target_include_directories(pico_trinamic PUBLIC
    ${CMAKE_CURRENT_LIST_DIR}
    ${TRINAMIC_SRC}
    ${CMAKE_CURRENT_LIST_DIR}/../SC16IS752
)
target_link_libraries(pico_trinamic PUBLIC pico_stdlib hardware_i2c sc16is752 m)
