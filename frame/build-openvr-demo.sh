#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
build="$root/build"
sdk="$build/include"
openvr_tag=v2.15.6
openvr_header_sha256=1e6ed57199896cc1f7c5484e50fa18955e97be15be690beb28d998c877ead7fd

for tool in cmake curl sha256sum; do
    command -v "$tool" >/dev/null || {
        echo "Missing $tool. Build in an ARM64 Linux development environment with CMake installed." >&2
        exit 1
    }
done

mkdir -p "$sdk"
header="$sdk/openvr.h"
if ! echo "$openvr_header_sha256  $header" | sha256sum -c --status 2>/dev/null; then
    part="$header.part"
    curl -fsSL "https://raw.githubusercontent.com/ValveSoftware/openvr/$openvr_tag/headers/openvr.h" -o "$part"
    echo "$openvr_header_sha256  $part" | sha256sum -c --status || {
        rm -f "$part"
        echo "OpenVR header checksum mismatch for $openvr_tag" >&2
        exit 1
    }
    mv "$part" "$header"
fi

cmake -S "$root" -B "$build/cmake" -DCMAKE_BUILD_TYPE=Release \
    -DFRAMEPHONE_BUILD_OPENVR_OVERLAY=ON \
    -DOPENVR_INCLUDE_DIR="$sdk" \
    -DOPENVR_LIBRARY_DIR="${OPENVR_LIBRARY_DIR:-/opt/steamvr/bin/linuxarm64}"
cmake --build "$build/cmake" --parallel
echo "Built native sources under $build/cmake"
