# Roadmap

FramePhone's goal is to locate a phone in Steam Frame's view and eventually draw
its correctly sized screen in VR. The current milestone is a repeatable optical
tracking experiment, not a complete virtual phone product.

## Implemented

- Android tag36h11 overlays with physical display calibration, configurable
  layouts and versioned measured-corner export.
- Native real AprilTag detection, desktop preview, synthetic input and local replay.
- Read-only Frametop camera-ring adapter and factory KB4 camera/head calibration.
- Calibrated planar and stereo rigid-phone estimation, whole-tag outlier checks,
  ambiguity/loss states, and explicit capture/camera/calibration identities.
- Opt-in detection/pose logs and paired grayscale recording for repeatable analysis.
- Automated software tests and build workflows; a separate OpenVR rendering demo.
- Shared Linux build recipe producing one self-extracting desktop executable,
  with bundled libraries, camera broker, layout chooser, live previews, tracking
  controls and a camera-independent startup test.

## Next: validate the headset path

Build on ARM64, establish the camera broker/identity/clock mapping, and collect
paired captures with the actual phone export. Measure detection coverage,
reprojection error, distance/rotation accuracy, latency and sustained CPU cost.
Repeat across distance, tilt, lighting and headset sleep/restart. The
[headset procedure](../frame/docs/HEADSET_TEST.md) and
[validation guide](../frame/docs/TRACKING_VALIDATION.md) define the starting point.

Factory calibration import and synthetic tests do not establish real camera
accuracy. Tag visibility in color passthrough does not establish detectability
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

Phone IMU fusion and screen streaming are separate future features. They need
explicit transport, clock and alignment contracts and are not included in the
current apps. Multi-phone tracking, curved/folded screens, general hand tracking
and a full desktop compositor are outside the current scope.
