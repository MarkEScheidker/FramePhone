# Steam Frame integration

FramePhone reuses the Frametop camera broker/ring protocol, factory calibration
import, ray math and bounded stereo pairing policy. It does not install
Frametop or run its neural hand tracker/compositor. Source provenance and retained
licenses are in [third_party/frametop](../third_party/frametop/README.md).

The supported build is `bash frame/build.sh` on Linux desktop or the headset.
The single executable contains its runtime and privileged camera broker. The
desktop, Bluetooth/TLS links and fiducial estimator run as the user; only camera setup
uses graphical authorization.

Camera views, paired telemetry, live stereo pose tracking and the VR rectangle
have been demonstrated on the owner's headset. The tracker needs the same
complete marker in both selected cameras and publishes a head-relative pose.
A separate [OpenVR renderer](VR_DISPLAY.md) displays the screen-sized rectangle.
Metric accuracy, factory-head/runtime-HMD alignment and capture timing still need
independent measurement.

See [build](BUILD.md), [headset setup](HEADSET_TEST.md),
[marker tracking](FIDUCIAL_TRACKING.md), [coordinates](COORDINATE_SYSTEMS.md)
and [validation](TRACKING_VALIDATION.md). The [ARCore handoff](ARCORE_HANDOFF.md)
uses headset pose history and clock mapping for world-space rendering; factory
extrinsics and exposure timing still require independent calibration.
