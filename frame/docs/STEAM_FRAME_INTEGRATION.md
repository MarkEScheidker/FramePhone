# Steam Frame integration

The tracker targets native Linux ARM64. The Android app remains the marker
source; it does not read headset cameras. The single-file desktop app bundles
a broker adapted from Frametop and reads its local camera ring. This uses
internal firmware interfaces rather than a standard OpenXR raw-camera API.

See [HEADSET_TEST.md](HEADSET_TEST.md) for the complete build/run procedure.
Factory import, ring input and stereo geometry are implemented. The owner has
run the app and observed up to six fiducials updating live on a Steam Frame.
Physical front-camera mapping, pose accuracy and sustained performance remain
unverified.

## Reuse boundary

The integration is audited against Frametop commit
`24a86dc02669caaef8386ea5bfeb08fcb2819944`. Adapted code is MIT licensed with
[notice and provenance](../third_party/frametop/README.md).

| Frametop component | FramePhone use |
| --- | --- |
| `hands/camd/` | Vendored camera broker, statically compiled and started by the GUI through pkexec; adapted caller identity, lifetime and private ring path. |
| `hands/camd/fhring.h` | FHRING01 v1 contract implemented by the bounded read-only ring adapter. |
| `hands/track/calib.cpp` | Adapted KB4 factory importer, CAD/head transforms, projection/rays and least-squares intersection. |
| `hands/track/main.cpp` | Adapted fresh-frame/3 ms capture-spread policy for two explicit views. |
| Neural hand tracker, gestures, compositor | Not required for rigid fiducials and not included. |

Frametop's hand tracker detects 21 learned landmarks, triangulates observations
and applies hand-specific priors/filtering. FramePhone instead knows marker IDs,
canonical corners and measured rigid phone geometry. It reuses platform geometry
and capture contracts while fitting one rigid phone transform against both images.
Tag decision margins are not neural presence probabilities or uncertainty weights.

## Camera acquisition

XRService owns the tracking camera streams. Upstream `ft-camd` borrows DMA-BUFs
and observes V4L2 dequeue tracepoints, then publishes copied frames. Its setup
requires host privileges; it drops them before processing. It is experimental
and depends on internal firmware/kernel interfaces. Do not assume compatibility
from a matching source build alone.

The broker runs directly on SteamOS. The GUI and dynamically linked tracker
use the libc/libraries inside the self-extracting executable, without a runtime
container. [BUILD.md](BUILD.md) defines the same build process for PC and headset.
No Frametop installation, system service or persistent capability is installed.
The broker uses `/run/user/UID/framephone-camera/cam-ring`, preventing ring-path
collisions with Frametop; simultaneous capture coexistence is deferred.

The broker exposes all normal mono candidates so the actual front views can be
identified. The desktop detects/previews/tracks only the selected two views;
side views should remain unselected. The previous fixed OG0VE10 / `upper_left/right`
choice selected side views on the owner's headset. Sensor models, upstream
factory names and video numbers do not establish physical placement here.
Ring names are sensor/video slugs. FramePhone requires an explicit mapping.
Verify current
XRService sensor/device logs and prefer exact `VIDIOC_QUERYBUF` bindings over
queue-order fallbacks. GUI previews support identifying the front lenses; the
tracker does not automatically exchange camera names.
The GUI displays reported stream identity/dimensions and offers all discovered
KB4 calibrations without choosing a factory pair automatically. It rejects a
stream/calibration dimension mismatch before creating a tracking session; equal
dimensions still require a correct identity mapping.

Live marker counts use native AprilTag detection without a phone layout. During
stereo tracking the same detectors provide the counts; separate workers run
before and after stereo sessions. The optional preview never resizes detector
input. Capture dimensions come from XRService, and full-size windows show native
pixels; the broker does not configure a higher-resolution camera mode.

## Calibration and time

The importer reads `persist/xrservice.json` and `persist/device_config.json`
relative to an explicit device root. It selects KB4 intrinsics and composes
camera-to-head transforms. Camera extrinsic translations convert mm to meters;
CAD/head positions are meters. Imported data is labelled `factory_imported`,
which records its origin rather than measured accuracy.

Stereo requires fresh captures from a verified shared clock and accepts at most
3 ms skew. Upstream's mono tracker assumes `CLOCK_MONOTONIC_RAW`; the ring does
not encode that claim. The initial GUI labels its mono V4L2 timestamps as one
shared camera domain, an explicit assumption still requiring hardware validation;
it does not claim a measured capture-to-XR mapping. Color-camera clocks and cropped/scaled calibration need
separate work and are outside the current mono test procedure.

Head-relative T_HP is not a world pose. Historical headset poses and a verified
capture-to-XR clock map are still required for motion-compensated world rendering.
See [coordinates](COORDINATE_SYSTEMS.md) and [validation](TRACKING_VALIDATION.md).

## Primary references

- [Pinned Frametop hands documentation](https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/README.md)
- [Calibration source](https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/track/calib.cpp)
- [Tracker loop](https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/track/main.cpp)
- [Ring ABI](https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/camd/fhring.h)
- [Valve Steam Frame custom-engine documentation](https://partner.steamgames.com/doc/steamhardware/steamframe/engines/custom)
