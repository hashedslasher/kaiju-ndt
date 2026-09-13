cmake_minimum_required(VERSION 3.16)
project(kaiju-viewer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)

find_package(Qt5 COMPONENTS Core Gui Widgets PrintSupport REQUIRED)

add_executable(kaiju-viewer
    src/main.cpp
    src/mainwindow.cpp
    external/qcustomplot.cpp
    src/mainwindow.h
    external/qcustomplot.h
)

target_link_libraries(kaiju-viewer PRIVATE
    Qt5::Core
    Qt5::Gui
    Qt5::Widgets
    Qt5::PrintSupport
)
