# Steam Frame integration

FramePhone reuses the Frametop camera broker/ring protocol, factory calibration
import, ray math and bounded stereo pairing policy. It does not install
Frametop or run its neural hand tracker/compositor. Source provenance and retained
licenses are in [third_party/frametop](../third_party/frametop/README.md).

The supported build is `bash frame/build.sh` on Linux desktop or the headset.
The single executable contains its runtime and privileged camera broker. The
desktop, TLS link and fiducial estimator run as the user; only camera setup
uses graphical authorization.

The owner has confirmed camera views and paired live telemetry on Frame.
Single-tag accuracy, front-camera factory mapping and timing still need hardware
validation. The tracker needs the same complete marker in
both selected cameras; it produces a head-relative marker pose, not a VR overlay.

See [build](BUILD.md), [headset setup](HEADSET_TEST.md),
[marker tracking](FIDUCIAL_TRACKING.md), [coordinates](COORDINATE_SYSTEMS.md)
and [validation](TRACKING_VALIDATION.md). Historical headset poses and precise
capture-to-XR mapping are prerequisites for future world-space rendering/fusion.
