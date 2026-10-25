# Steam Frame camera module

A self-contained Linux camera-access component, extracted from FramePhone.
Copy **this entire directory**, including licenses, into another project.
It requires C++20 and the Linux standard system headers; it has no OpenCV,
AprilTag, Android, JSON-library or SteamVR-client dependency.

## Responsibilities

- CameraFrame: owned Gray8 pixels, dimensions/stride, capture timestamp,
  explicit clock/calibration labels and optional transport metadata.
- FrametopRing: bounded, read-only access to FHRING01 v1. poll() returns
  the next stable image, or no value when there is no new frame.
- RecordedFrameSource: read [PGM recordings](RECORDINGS.md) for offline work.
- broker/: a separate Frametop-derived executable that borrows XRService's
  capture buffers and publishes the private per-user ring.

Detection, stereo pairing, calibration, pose estimation, networking and rendering
belong to the consuming application. The module does not install a service,
start its broker, request authorization or choose physical camera identities.

## Add to a project

In CMake:

    add_subdirectory(third_party/framephone-camera)
    target_link_libraries(my_app PRIVATE FramePhone::Camera)

In C++:

    #include <framephone/frametop_ring.hpp>

    framephone::FrametopRing camera({
        ring_path, stream_name, calibration_id, capture_clock_domain
    });
    if (auto frame = camera.poll()) {
        // Use frame->image.pixels, width, height and stride_bytes.
        // Pixels are owned by this returned frame, not shared DMA memory.
    }

Supply clock/calibration labels from your application's actual source metadata.
The reader does not establish clock synchronization or camera calibration.
An empty poll is not end-of-stream; the caller owns polling, cancellation and
timeouts. Malformed/replaced rings, stale writers and non-increasing capture
timestamps produce exceptions. Recreate the reader after broker replacement.
Enumerate with list_frametop_cameras(path), then select the desired stream.
Copying this module does not prove a sensor is front/left/right.

## Build independently

From this directory:

    cmake -S . -B build
    cmake --build build --parallel 2
    ctest --test-dir build --output-on-failure

The default standalone build includes a reader example and synthetic C++ tests.
To build the broker too, add -DFRAMEPHONE_CAMERA_BUILD_BROKER=ON.
For a host-portable static broker, also add
-DFRAMEPHONE_CAMERA_STATIC_BROKER=ON; this requires a static libc toolchain.
The FramePhone executable continues to use its existing packaged static broker.

With a broker already running as your user:

    build/framephone-camera-read /run/user/$(id -u)/framephone-camera/cam-ring
    build/framephone-camera-read /run/user/$(id -u)/framephone-camera/cam-ring STREAM_NAME

The example lists streams or prints ten new frame headers. Its metadata labels
are explicitly unverified; it does not estimate poses. It times out if frames stop.
A standalone cmake --install build --prefix /path/to/prefix installs the static
reader library, headers, broker (if enabled), documentation and license notices.

The broker regression script tests/test_broker.py checks mapping and caller
handling without hardware or privileges. It requires Python 3, a C compiler with
static libc, and readelf. The test_standalone.py integration check verifies that
a copied module builds independently and as another project's CMake dependency.

## Runtime and compatibility

The reader requires access to a live ring owned by its broker's desktop user.
The broker needs privileges during discovery to borrow XRService DMA buffers and
open the V4L2 capture tracepoint. FramePhone launches it through desktop
authorization; it drops privileges before publishing frames. Reusing the broker
means supplying your own authorized launch and process-lifetime management.
The ring path remains /run/user/UID/framephone-camera/cam-ring; only one writer
can own it. Consumers can share the existing ring rather than start another writer.

This broker is **Steam Frame-specific**, not a general camera driver or a public
Valve capture API. It depends on XRService, Linux tracepoints and DMA-BUF layouts;
OS/runtime changes may require maintenance. No hardware reconfiguration or
generic USB-camera support is provided. Synthetic tests check the reader and
mapping logic; they cannot establish live hardware compatibility.

The public headers are the intended integration surface. Changes should preserve
explicit ownership, timestamp domains, bounds checks and read-only behavior.
There is no promised stable binary ABI or separately versioned release yet.

## License

MIT. Keep [LICENSE](LICENSE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
and both upstream notices in broker/ when redistributing this module.
