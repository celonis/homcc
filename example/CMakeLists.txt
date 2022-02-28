cmake_minimum_required(VERSION 3.5)

project (example)

set (SOURCES
    src/main.cpp
    src/foo.cpp)

add_executable(example ${SOURCES})

target_include_directories(example
    PRIVATE 
        ${PROJECT_SOURCE_DIR}/include
)