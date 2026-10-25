# Reusing FramePhone components

FramePhone is MIT-licensed. Reusing a component should not require adopting the
phone UI, pairing protocol or VR renderer. Keep the original and third-party
license notices with copied source. See [third-party notices](../THIRD_PARTY_NOTICES.md).

## Repository map

| Location | Role | Dependencies |
| --- | --- | --- |
| [phone/](../phone/) | Android pairing, telemetry and fullscreen marker | Android SDK |
| [frame/modules/camera/](../frame/modules/camera/) | Standalone frame types, ring/recording readers, Steam Frame broker | Linux, C++20; C compiler for broker |
| frame/include/framephone/ and frame/src/ geometry sources | KB4 calibration, stereo pairing, planar pose and AprilTag tracking | Camera module, OpenCV, AprilTag; JSON headers for import |
| [frame/desktop/](../frame/desktop/) | Application workflow, pairing client and native process orchestration | Python/Tk, Pillow |
| frame/src/overlay_main.cpp and vr_surface.hpp | Pose-driven OpenVR screen rectangle | JSON headers, installed SteamVR client |
| [frame/pack/](../frame/pack/) | Full application packaging | Container build tools |

The camera module is independently buildable and copyable today. Geometry and
fiducial tracking are separate in-project CMake libraries, but still share the
application's build and public-header tree. Their standalone packaging is not
complete. Rendering, networking and UI stay outside the capture module.

## Take just camera access

Copy the entire [camera module](../frame/modules/camera/), then add its directory
to your CMake build and link FramePhone::Camera. Its README covers the public
headers, independent builds, example reader, privilege boundary and limitations.
No OpenCV, AprilTag or Android installation is needed for this component.

The module's tests build from a copied directory and from a separate CMake
consumer. The broker's source is unchanged by the extraction, including the
upstream missing-buffer repair. It still depends on Steam Frame's XRService
internals and must be launched with appropriate authorization.

## Use the tracking libraries

In the full native build, framephone_geometry supplies calibrated camera rays,
stereo pairing and recording. framephone_fiducial adds AprilTag detection and
joint planar pose estimation. Its FiducialTracker accepts a metric black-edge
size, a StereoRig and StereoPair frames. Android pairing is not part of that API.

Public interfaces are under frame/include/framephone/. Link the existing targets
from the full build; do not copy the command-line session parser as a tracking
API. The [architecture](../frame/docs/ARCHITECTURE.md) and
[tracking guide](../frame/docs/FIDUCIAL_TRACKING.md) explain coordinate conventions
and acceptance rules. There is no separately versioned tracking SDK or stable
binary ABI yet.

## Contribution boundaries

Keep hardware access, estimation and product workflow separate:

- The camera module returns pixels and explicit metadata; it does not infer
  phone poses, select physical camera roles or synchronize unrelated clocks.
- Tracking consumes frames and calibration; it does not authorize camera access,
  pair phones or display UI.
- The desktop owns authorization, process lifetime, pairing and configuration.
- The renderer consumes accepted poses and screen geometry; it does not track.

Preserve the ownership, timestamp and transform contracts in the public headers.
Behavior changes should have independent fixtures or replay evidence. A working
synthetic example is not a substitute for headset validation.
