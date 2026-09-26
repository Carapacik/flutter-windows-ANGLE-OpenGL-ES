cmake_minimum_required(VERSION 3.14)
project(angle_native_smoke_test LANGUAGES CXX)
if(NOT DEFINED ANGLE_ROOT)
  message(FATAL_ERROR "ANGLE_ROOT must point to staging")
endif()
add_executable(angle_smoke_test angle_smoke_test.cpp)
target_compile_features(angle_smoke_test PRIVATE cxx_std_17)
if(MSVC)
  target_compile_options(angle_smoke_test PRIVATE /EHsc)
endif()
target_include_directories(angle_smoke_test PRIVATE "${ANGLE_ROOT}/include")
target_link_libraries(angle_smoke_test PRIVATE d3d11 dxgi
  "${ANGLE_ROOT}/lib/libEGL.dll.lib"
  "${ANGLE_ROOT}/lib/libGLESv2.dll.lib")
