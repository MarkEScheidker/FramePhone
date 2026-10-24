#!/usr/bin/env bash
# Shared CMake recipe, called by the container build and dependency-equipped CI.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
build=${FRAMEPHONE_BUILD_DIR:-"$root/build/linux-native"}
prefix=${FRAMEPHONE_INSTALL_DIR:-"$build/install"}
cmake_tool=${CMAKE_COMMAND:-cmake}
ctest_tool=${CTEST_COMMAND:-ctest}
"$cmake_tool" -S "$root" -B "$build" -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_TESTING=ON \
    -DCMAKE_INSTALL_PREFIX="$prefix" "$@"
"$cmake_tool" --build "$build" --parallel "${FRAMEPHONE_BUILD_JOBS:-2}"
"$ctest_tool" --test-dir "$build" --output-on-failure
"$cmake_tool" --install "$build"
"$prefix/bin/framephone-camera" --help
"$prefix/bin/framephone-overlay" --self-test
"$prefix/bin/framephone-fiducial" --help
"$prefix/bin/framephone-fiducial" --self-test
