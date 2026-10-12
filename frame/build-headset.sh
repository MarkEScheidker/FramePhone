#!/usr/bin/env bash
# Run INSIDE an ARM64 Linux development environment on the headset.
# No dependency downloads, root operations, SSH or service changes.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ "$#" -gt 0 ]; then
    echo "Usage: bash frame/build-headset.sh (inside ARM64 Linux; see docs/HEADSET_TEST.md)" >&2
    exit 2
fi
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != aarch64 ]; then
    echo "Run this on the Steam Frame in its ARM64 Linux development container." >&2
    echo "This x86_64 checkout's extracted SDK cannot produce a headset executable." >&2
    exit 1
fi
for tool in cmake c++ ctest file python3; do
    command -v "$tool" >/dev/null || { echo "Missing $tool; see docs/HEADSET_TEST.md" >&2; exit 1; }
done
build="$root/build/headset-aarch64"
cmake -S "$root" -B "$build" -DCMAKE_BUILD_TYPE=Release \
    -DFRAMEPHONE_REQUIRE_TRACKER=ON -DFRAMEPHONE_ENABLE_APRILTAG=ON \
    -DFRAMEPHONE_ENABLE_POSE=ON -DFRAMEPHONE_ENABLE_SDL2=OFF \
    -DFRAMEPHONE_BUILD_OPENVR_OVERLAY=OFF -DBUILD_TESTING=ON \
    -DCMAKE_INSTALL_PREFIX="$build/install"
cmake --build "$build" --parallel "${FRAMEPHONE_BUILD_JOBS:-4}"
file "$build/framephone-stereo" | tee "$build/binary-info.txt"
if ! file "$build/framephone-stereo" | grep -q 'ARM aarch64'; then
    echo "Compiler produced an unexpected architecture; refusing to install." >&2
    exit 1
fi
ctest --test-dir "$build" --output-on-failure
cmake --install "$build"
echo "Ready: $build/install/bin/framephone-stereo"
echo "Run in this SAME container (its OpenCV/AprilTag runtime libraries are required)."
echo "Live setup and test commands: $root/docs/HEADSET_TEST.md"
