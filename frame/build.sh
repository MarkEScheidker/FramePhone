#!/usr/bin/env bash
# The same packaged Linux build on a desktop or the headset.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
arch=arm64
usage() {
    echo "Usage: bash frame/build.sh [--arch arm64|amd64|native]"
    echo "Default: ARM64 headset package. Requires Linux, Python 3 and Podman or Docker."
    echo "On x86_64, ARM64 builds also require QEMU/binfmt (see frame/docs/BUILD.md)."
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --arch) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; arch=$2; shift 2 ;;
        *) usage >&2; exit 2 ;;
    esac
done
[ "$(uname -s)" = Linux ] || { echo "Build from Linux (including WSL2)." >&2; exit 1; }
if [ "$arch" = native ]; then
    case "$(uname -m)" in
        aarch64|arm64) arch=arm64 ;;
        x86_64|amd64) arch=amd64 ;;
        *) echo "Unsupported native architecture." >&2; exit 2 ;;
    esac
fi
case "$arch" in arm64|amd64) ;; *) usage >&2; exit 2 ;; esac
for tool in python3 tar sha256sum; do
    command -v "$tool" >/dev/null || { echo "Missing $tool." >&2; exit 1; }
done
source "$root/frame/pack/engine.sh"
choose_engine
jobs=${FRAMEPHONE_BUILD_JOBS:-2}
[[ "$jobs" =~ ^[1-9][0-9]?$ ]] || { echo "FRAMEPHONE_BUILD_JOBS must be 1–99." >&2; exit 2; }
mkdir -p "$root/frame/build/dist"
work=$(mktemp -d "$root/frame/build/package.XXXXXX")
container=
cleanup() {
    if [ -n "$container" ]; then "$engine" rm "$container" >/dev/null 2>&1 || true; fi
    rm -rf "$work"
}
trap cleanup EXIT
context="$work/context"
mkdir "$context"
python3 "$root/scripts/package-source.py" --output "$work/source.tar.gz"
tar -xzf "$work/source.tar.gz" -C "$context"
image="localhost/framephone:$arch"
echo "Building linux/$arch with $engine; tests run inside the build image."
if ! "$engine" build --platform "linux/$arch" --build-arg "BUILD_JOBS=$jobs" \
    --build-arg "TARGET_ARCH=$arch" \
    --tag "$image" --file "$context/frame/pack/Containerfile" "$context"; then
    echo "Container build failed. For a foreign architecture, configure QEMU/binfmt once." >&2
    echo "See frame/docs/BUILD.md. No package was produced by this attempt." >&2
    exit 1
fi
actual=$("$engine" image inspect --format '{{.Architecture}}' "$image")
[ "$actual" = "$arch" ] || { echo "Expected $arch image, got $actual." >&2; exit 1; }
# Export without running a container on the target desktop.
container=$("$engine" create "$image")
"$engine" cp "$container:/out/FramePhone.run" "$work/FramePhone.run"
chmod 755 "$work/FramePhone.run"
archive="$root/frame/build/dist/FramePhone-$arch.run"
mv "$work/FramePhone.run" "$archive"
(cd "$(dirname "$archive")" && sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256")
echo "Ready: $archive"
echo "Copy this one file to the target desktop, allow execution, and open it."
echo "The target needs neither Podman/Docker nor Frametop."
