#!/usr/bin/env bash
# Local Linux/WSL launcher. No downloads, networking, or headset changes.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
deps="$root/build/deps"
cmake_tool=${CMAKE_COMMAND:-cmake}
if ! command -v "$cmake_tool" >/dev/null 2>&1 && [ "$(uname -m)" = x86_64 ]; then
    cmake_tool="$deps/python/cmake/data/bin/cmake"
fi
if ! [ -x "$cmake_tool" ] && ! command -v "$cmake_tool" >/dev/null 2>&1; then
    echo "CMake is missing. Install CMake, AprilTag 3 and SDL2 development files." >&2
    echo "A headless preview-only build is available with: make -C frame all" >&2
    exit 1
fi
# Only use this checkout's extracted x86_64 SDK on an x86_64 machine.
args=()
if [ "$(uname -m)" = x86_64 ]; then
    libs="$deps/sdl2/usr/lib/x86_64-linux-gnu"
    if [ -d "$libs" ]; then
        export LD_LIBRARY_PATH="$libs:$libs/pulseaudio${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        args+=("-DSDL2_ROOT=$deps/sdl2/usr")
    fi
    if [ -d "$deps/apriltag/lib" ]; then
        args+=("-DAPRILTAG_ROOT=$deps/apriltag")
    fi
    if [ -d "$deps/opencv/usr/lib/x86_64-linux-gnu" ]; then
        export LD_LIBRARY_PATH="$deps/opencv/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        args+=("-DPOSE_SDK_ROOT=$deps/opencv/usr")
    fi
fi
"$cmake_tool" -S "$root" -B "$root/build/diagnostic" -DCMAKE_BUILD_TYPE=Release "${args[@]}"
"$cmake_tool" --build "$root/build/diagnostic" --parallel 4
exec "$root/build/diagnostic/framephone-diagnostic" "$@"
