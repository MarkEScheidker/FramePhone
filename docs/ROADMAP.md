# Roadmap

FramePhone's goal is to locate a phone in Steam Frame's view and eventually draw
its correctly sized screen in VR. The current milestone is paired live phone
telemetry as a foundation for markerless tracking.

## Implemented

- Android manual body dimensions, user-started sensor service, LAN discovery,
  TLS fingerprint pairing and revocable saved reconnect credentials.
- Frame phone telemetry tab with live values, measured rates, sensor availability,
  drops/gaps and rough clock-offset/sample-age diagnostics.
- Removed the Android fiducial overlay and export UI. Native marker diagnostics
  remain available for old exports, fixtures and camera experiments.
- Native real AprilTag detection, desktop preview, synthetic input and local replay.
- Read-only Frametop camera-ring adapter and factory KB4 camera/head calibration.
- Calibrated planar and stereo rigid-phone estimation, whole-tag outlier checks,
  ambiguity/loss states, and explicit capture/camera/calibration identities.
- Opt-in detection/pose logs and paired grayscale recording for repeatable analysis.
- Automated software tests and build workflows; a separate OpenVR rendering demo.
- Shared Linux build recipe producing one self-extracting desktop executable,
  with bundled libraries, camera broker, layout chooser, live previews, tracking
  controls and a camera-independent startup test.

## Next: validate pairing and sensor delivery

Pair on the real LAN, check sensor axes/rates, Stop/Forget, reconnect after IP
changes, unavailable sensors, Wi-Fi loss and sleep/resume. Measure transport
latency and power. Software tests do not validate Android Keystore/TLS behavior
or sensor delivery on the owner's phone. Then add temporary visual association,
off-the-shelf phone detection and physical outline estimation.

## Camera validation

Build on ARM64, establish the camera broker/identity/clock mapping, and collect
paired captures with the actual phone export. Measure detection coverage,
reprojection error, distance/rotation accuracy, latency and sustained CPU cost.
Repeat across distance, tilt, lighting and headset sleep/restart. The
[headset procedure](../frame/docs/HEADSET_TEST.md) and
[validation guide](../frame/docs/TRACKING_VALIDATION.md) define the starting point.

Factory calibration import and synthetic tests do not establish real camera
accuracy. Tag visibility in headset passthrough does not establish detectability
in the monochrome tracking cameras. Record these separately.

## Then: tracked VR visualization

Establish capture-to-XR time mapping and timestamped headset pose history.
Transform head-relative phone poses into a selected world reference space and
render the measured phone outline. Handle reference-space resets explicitly.

## Then: continuity and prediction

Measure optical noise before choosing rigid-pose filtering, bounded prediction
and reacquisition rules. Keep raw output available; report stale/lost tracking
explicitly. Validate simultaneous phone and headset motion against independent
measurements.

## Later experiments

The next markerless experiment combines a pretrained phone detector and physical
outline geometry with phone inertial data. [LAN pairing and IMU design](../frame/docs/PAIRING_AND_IMU.md)
documents the implemented fingerprint pairing and sensor transport, plus the
remaining QR association, precise timing and headset-owned fusion work. Measure
the connection/clock diagnostics before integrating the estimator.
Screen streaming is separate future work.
Multi-phone tracking, curved/folded screens, general hand tracking
and a full desktop compositor are outside the current scope.
