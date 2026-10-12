# Steam Frame integration

The tracker targets native Linux ARM64. The Android app remains the marker
source; it does not read headset cameras. Current integration uses an external
Frametop camera broker and a read-only local ring, not a verified standard
OpenXR raw-camera interface.

See [HEADSET_TEST.md](HEADSET_TEST.md) for the complete build/run procedure.
Factory import, ring input and stereo geometry are implemented; compatibility
and performance on an actual Steam Frame remain unverified.

## Reuse boundary

The integration is audited against Frametop commit
`24a86dc02669caaef8386ea5bfeb08fcb2819944`. Adapted code is MIT licensed with
[notice and provenance](../third_party/frametop/README.md).

| Frametop component | FramePhone use |
| --- | --- |
| `hands/camd/` | External `ft-camd` camera supplier, built/started separately on the host. No privileged capture implementation is included here. |
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

The broker runs on SteamOS; the dynamically linked tracker runs in its ARM64
Linux development container. This avoids assuming container glibc/OpenCV libraries
are available on the host. The source handoff does not bundle either environment.

Ring names are sensor/video slugs, whereas factory `sourceCamera` fields use names
such as `slam_left`. FramePhone requires an explicit mapping. Verify current
XRService sensor/device logs and prefer exact `VIDIOC_QUERYBUF` bindings over
queue-order fallbacks. The tracker does not automatically exchange camera names.

## Calibration and time

The importer reads `persist/xrservice.json` and `persist/device_config.json`
relative to an explicit device root. It selects KB4 intrinsics and composes
camera-to-head transforms. Camera extrinsic translations convert mm to meters;
CAD/head positions are meters. Imported data is labelled `factory_imported`,
which records its origin rather than measured accuracy.

Stereo requires fresh captures from a verified shared clock and accepts at most
3 ms skew. Upstream's mono tracker assumes `CLOCK_MONOTONIC_RAW`; the ring does
not encode that claim. Color-camera clocks and cropped/scaled calibration need
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
