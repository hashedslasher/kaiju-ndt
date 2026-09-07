cmake_minimum_required(VERSION 3.16)
project(name_of_the_app LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)

find_package(Qt5 COMPONENTS Core Gui Widgets PrintSupport REQUIRED)

add_executable(name_of_the_app
    src/main.cpp
    src/mainwindow.cpp
    src/qcustomplot.cpp
    src/mainwindow.h
    src/qcustomplot.h
)

target_link_libraries(name_of_the_app PRIVATE
    Qt5::Core
    Qt5::Gui
    Qt5::Widgets
    Qt5::PrintSupport
)
