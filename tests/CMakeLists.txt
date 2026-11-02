cmake_minimum_required(VERSION 3.24)

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(GenFormDomainTests LANGUAGES CXX)
    enable_testing()
    find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui)
endif()

add_executable(genform_domain_tests
    domain_tests.cpp
    ../genform/domain/geometry.cpp
    ../genform/domain/properties.cpp
    ../genform/domain/manufacturing.cpp
    ../genform/domain/checks.cpp
    ../genform/domain/sketch_editing.cpp
    ../genform/domain/standard_parts.cpp
)
target_compile_features(genform_domain_tests PRIVATE cxx_std_20)
target_include_directories(genform_domain_tests PRIVATE ..)
target_link_libraries(genform_domain_tests PRIVATE Qt6::Core Qt6::Gui)
if(MSVC)
    target_compile_options(genform_domain_tests PRIVATE /utf-8 /W4 /permissive-)
else()
    target_compile_options(genform_domain_tests PRIVATE -Wall -Wextra -Wpedantic)
endif()
add_test(NAME domain_tests COMMAND genform_domain_tests)
