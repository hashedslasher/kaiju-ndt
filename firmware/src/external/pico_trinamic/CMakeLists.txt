add_library(pico_trinamic INTERFACE)

target_sources(pico_trinamic INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/Trinamic-library/common.c
        ${CMAKE_CURRENT_LIST_DIR}/Trinamic-library/tmc_interface.c
        ${CMAKE_CURRENT_LIST_DIR}/Trinamic-library/tmc2130.c
        ${CMAKE_CURRENT_LIST_DIR}/Trinamic-library/tmc2130.c
        ${CMAKE_CURRENT_LIST_DIR}/Trinamic-library/tmc2209.c
        ${CMAKE_CURRENT_LIST_DIR}/Trinamic-library/tmc5160.c
        ${CMAKE_CURRENT_LIST_DIR}/tmc_uart.c
)

target_include_directories(pico_trinamic INTERFACE ${CMAKE_CURRENT_LIST_DIR} ${CMAKE_CURRENT_LIST_DIR}/Trinamic-library)

#add_subdirectory(Trinamic-library)

# Add the used pico libraries to the library
target_link_libraries(pico_trinamic INTERFACE
        pico_stdlib
        #trinamic
        hardware_uart
        )
