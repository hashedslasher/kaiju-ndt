# Development setup and building

## Setup
  
  Clone the repository if you already have git installed, or download as a zip from the front page
  
  ### Windows
  1. Open powershell and navigate to kaiju-ndt/setup
    
  2. Then run:
      ```bash
      .\setup-windows.ps1
      ```
  3. Install qt5 and arm-embedded
  
  ### Linux
  1. Open a terminal and navigate to kaiju-ndt/setup
    
  2. Then run:
      ```bash
      chmod +x setup-linux.sh;./setup-linux.sh
      ```

## Building pico firmware and the c++ acquisition app
  Navigate to app or firmware/pico, depending on what you want to build.

  ### Windows
  ```bash
  .\build.ps1
  ```
  ### Linux
  ```bash
  ./build.sh
  ```
  To run the acquisition app after building open your file explorer navigate to kaiju-ndt/app/build, click on kaiju-ndt

  See [Home](../README.md) to flash pico firmware
