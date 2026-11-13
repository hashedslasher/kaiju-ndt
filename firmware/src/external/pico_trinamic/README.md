# Pico SDK Trinamic Stepper Driver Library

This is a C library for Pico SDK to interface with Trinamic stepper drivers. (work in progress)
The library uses the excelent [Trinamic-library](https://github.com/terjeio/Trinamic-library) from [grblHAL](https://github.com/grblHAL).

# Supported Drivers (as of now)

TMC2209

# Usage

To use this library in your code, simply `git clone` it into your Pico SDK Project directory. Once cloned, run `git submodule update --init --recursive` in the library directory.
In your CMakeLists.txt, make sure to use `add_submodules()`, also add `pico_trinamic` to your `target_link_libraries`. To access library functions in your project code, simply use `#include "trinamic.h"`

# Example-code

To build example code, open the example folder in VS Code. This example code demonstrates the use and initialization of the TMC2209 driver.

# To Do

Although the funcionts and variable are relatively self explanatory, one of the goals is to create or generate proper documentation. The Trinamic-Library is not commented or documented.
Add support for TMC2130
Add Support for TMC5160

# Disclaimer

This project has no guarantee of safety, using it is at your own risk. This is an open-source project, so its free to use. 
Errors could have been made, but overlooked, so feel free to contribute :blush: