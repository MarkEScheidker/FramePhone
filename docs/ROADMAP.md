# Roadmap

FramePhone's goal is to locate a phone in Steam Frame's view and eventually draw
its correctly sized screen in VR. The current milestone is paired live phone
telemetry and an initial markerless optical diagnostic.

## Implemented

- Bundled pretrained YOLOX-S phone detection with live native-pixel boxes,
  confidence/counts, optional visible 2D quadrilateral/axis and automatic search
  after disappearance. No manual corner selection is needed for detection.

- Markerless desktop workflow: synchronized capture, physically labelled corners,
  calibrated T_HB body-pose estimation, local complete-front-outline tracking,
  explicit ambiguity/loss, saved calibration and optional raw telemetry/replay.
- Android manual body dimensions, user-started sensor service, LAN discovery,
  TLS fingerprint pairing and revocable saved reconnect credentials.
- Frame phone telemetry tab with live values, measured rates, sensor availability,
  drops/gaps and rough clock-offset/sample-age diagnostics.
- Front-camera desktop previews and native grayscale recording/replay.
- Read-only Frametop camera-ring adapter and factory KB4 camera/head calibration.
- Joint calibrated stereo body estimation,
  ambiguity/loss states, and explicit capture/camera/calibration identities.
- Opt-in pose logs and paired grayscale recording for repeatable analysis.
- Automated software tests and build workflows; a separate OpenVR rendering demo.
- Shared Linux build recipe producing one self-extracting desktop executable,
  with bundled libraries, camera broker, live previews, tracking
  controls and a camera-independent startup test.

## Next: validate and extend markerless tracking

The owner has confirmed pairing and live telemetry on the phone and Steam Frame.
The [markerless tracking research and plan](../frame/docs/MARKERLESS_TRACKING.md)
proposes OpenCV outline acquisition, IPPE hypotheses, joint stereo validation
and a RAPID silhouette tracker, followed by aligned gyro prediction. The
[first diagnostic](../frame/docs/MARKERLESS_DIAGNOSTIC.md) implements manual
initialization and a complete-front-outline baseline. A separate
[automatic detection view](../frame/docs/AUTO_DETECTION.md) now provides
pretrained phone boxes and 2D outline proposals. Collect actual Frame
recordings and independent pose references next; compare automatic acquisition
and RAPID on those trials. Partial occlusion, automatic visual association and
gyro fusion are not implemented yet.

## Continue validating the sensor link

Pair on the real LAN, check sensor axes/rates, Stop/Forget, reconnect after IP
changes, unavailable sensors, Wi-Fi loss and sleep/resume. Measure transport
latency and power. Software tests do not validate Android Keystore/TLS behavior
or sustained sensor delivery on the owner's phone. Basic pairing/telemetry has
now been observed; rates, timing, reconnect and loss behavior still need trials.

## Camera validation

Build on ARM64, establish the camera broker/identity/clock mapping, and collect
paired captures with measured body geometry and independent pose references.
Measure outline coverage,
reprojection error, distance/rotation accuracy, latency and sustained CPU cost.
Repeat across distance, tilt, lighting and headset sleep/restart. The
[headset procedure](../frame/docs/HEADSET_TEST.md) and
[validation guide](../frame/docs/TRACKING_VALIDATION.md) define the starting point.

Factory calibration import and synthetic tests do not establish real camera
accuracy. Phone visibility in headset passthrough does not establish outline contrast
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

The next markerless experiment connects the pretrained detector's proposals to
validated stereo physical outlines, then phone inertial data. [LAN pairing and IMU design](../frame/docs/PAIRING_AND_IMU.md)
documents the implemented fingerprint pairing and sensor transport, plus the
remaining QR association, precise timing and headset-owned fusion work. Measure
the connection/clock diagnostics before integrating the estimator.
Screen streaming is separate future work.
Multi-phone tracking, curved/folded screens, general hand tracking
and a full desktop compositor are outside the current scope.
