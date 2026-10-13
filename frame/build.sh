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
case "$(uname -m)" in
    aarch64|arm64) host_arch=arm64 ;;
    x86_64|amd64) host_arch=amd64 ;;
    *) host_arch=unknown ;;
esac
if [ "$arch" = native ]; then
    case "$host_arch" in
        arm64|amd64) arch=$host_arch ;;
        *) echo "Unsupported native architecture." >&2; exit 2 ;;
    esac
fi
case "$arch" in arm64|amd64) ;; *) usage >&2; exit 2 ;; esac
for tool in python3 tar sha256sum tee tail; do
    command -v "$tool" >/dev/null || { echo "Missing $tool." >&2; exit 1; }
done
source "$root/frame/pack/engine.sh"
choose_engine
engine_command=("$engine")
engine_build_options=()
if [ "$engine" = podman ]; then
    # Desktop sessions may not expose a working systemd user bus. These options
    # apply only to this build/export; leave the user's containers.conf alone.
    engine_command+=(--cgroup-manager=cgroupfs --events-backend=file)
    # Run image build steps through Buildah's internal chroot runner, avoiding
    # crun/systemd startup failures in headset desktop sessions.
    engine_build_options+=(--isolation=chroot)
fi
jobs=${FRAMEPHONE_BUILD_JOBS:-2}
[[ "$jobs" =~ ^[1-9][0-9]?$ ]] || { echo "FRAMEPHONE_BUILD_JOBS must be 1–99." >&2; exit 2; }
mkdir -p "$root/frame/build/dist"
work=$(mktemp -d "$root/frame/build/package.XXXXXX")
container=
cleanup() {
    if [ -n "$container" ]; then "${engine_command[@]}" rm "$container" >/dev/null 2>&1 || true; fi
    rm -rf "$work"
}
trap cleanup EXIT
context="$work/context"
mkdir "$context"
python3 "$root/scripts/package-source.py" --output "$work/source.tar.gz"
tar -xzf "$work/source.tar.gz" -C "$context"
image="localhost/framephone:$arch"
echo "Building linux/$arch with $engine; tests run inside the build image."
echo "Build host: linux/$host_arch; target: linux/$arch."
build_log=$(mktemp "$root/frame/build/build-$arch.XXXXXX.log")
echo "Build log: $build_log"
if [ "$engine" = podman ]; then
    echo "Using Podman chroot build isolation, cgroupfs and file events."
fi
build_status=0
"${engine_command[@]}" build "${engine_build_options[@]}" \
    --platform "linux/$arch" --build-arg "BUILD_JOBS=$jobs" \
    --build-arg "TARGET_ARCH=$arch" \
    --tag "$image" --file "$context/frame/pack/Containerfile" "$context" \
    2>&1 | tee "$build_log" || build_status=$?
if [ "$build_status" -ne 0 ]; then
    echo "Container build failed (exit $build_status); last engine output:" >&2
    tail -n 25 "$build_log" >&2
    echo "Full build output: $build_log" >&2
    if [ "$host_arch" != unknown ] && [ "$host_arch" != "$arch" ]; then
        echo "Host linux/$host_arch differs from target linux/$arch; this build needs QEMU/binfmt." >&2
    fi
    echo "See frame/docs/BUILD.md. No package was produced by this attempt." >&2
    exit 1
fi
actual=$("${engine_command[@]}" image inspect --format '{{.Architecture}}' "$image")
[ "$actual" = "$arch" ] || { echo "Expected $arch image, got $actual." >&2; exit 1; }
# Export without running a container on the target desktop.
container=$("${engine_command[@]}" create "$image")
"${engine_command[@]}" cp "$container:/out/FramePhone.run" "$work/FramePhone.run"
chmod 755 "$work/FramePhone.run"
archive="$root/frame/build/dist/FramePhone-$arch.run"
mv "$work/FramePhone.run" "$archive"
(cd "$(dirname "$archive")" && sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256")
echo "Ready: $archive"
echo "Copy this one file to the target desktop, allow execution, and open it."
echo "The target needs neither Podman/Docker nor Frametop."
