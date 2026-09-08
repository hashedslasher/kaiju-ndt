#include <iostream>
#include <string>
#include "device.h"
#include "../include/asio.hpp"
//openPort: get OS, attempt to open port, error on fail
//writeDac: 

writeDac (std::string s, std::string port int baud_rate) {

    serial.set_option(asio::serial_port_base::baud_rate(115200));
    serial.set_option(asio::serial_port_base::character_size(8));
    serial.set_option(asio::serial_port_base::stop_bits(asio::serial_port_base::stop_bits::one));
    serial.set_option(asio::serial_port_base::parity(asio::serial_port_base::parity::none));

    asio::write(serial, boost::asio::buffer(s.c_str(), s.size()));

    serial.close();
};

std::string openPort() {
  std::string port;
  
  asio::io_service io;
  asio::serial_port serial(io);

  #if defined(__linux__) // Or #if __linux__
    port = "/dev/ttyACM*";
  #elif __APPLE__
    std::cout << "Hello, macOS!" << '\n';
  #elif _WIN32
    std::cout << "Hello, Windows!" << '\n';
  #else
    std::cout << "Hello, Other!" << '\n';
  #endif

  if (! serial.open(port) {
      std::cerr << "Failed to open: " << port;
      return -1
  }
  else {
    return port
  }
};
