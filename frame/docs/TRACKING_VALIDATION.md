# Tracking validation

Software checks do not establish real camera accuracy or headset performance.
Basic pairing and sensor delivery have been observed on the owner's hardware;
markerless tracking still needs independent physical trials.

## Automated checks

- Portable frame validation, timestamped PGM replay and independent ring-writer tests.
- Factory camera discovery and the packaged synthetic geometry self-test.
- Independently projected frontal/tilted corners and distorted stereo raster
  rendering for metric pose, actual contour tracking, invalid input and loss.
- Native session solve/replay, exact frame provenance and bounded previews.
- Real Tk capture/selection/live tracking, camera preview and loss clearing.
- TLS pairing/reconnect, credential pinning and opt-in telemetry recording.

CMake/CTest runs native checks. CI also runs desktop/TLS tests, Tk under Xvfb,
and packaged execution on Linux architectures. Tests require OpenCV and JSON,
plus Python/Tk for GUI integration. No camera privileges are needed.

## Hardware trials

Verify the selected front lenses, factory mapping, native resolution and clock
domain. Use a measured phone/case and independent position/angle references.
Start with a supported stationary phone, clear front boundary and simple background.
Compare labelled-corner geometry before evaluating automatic outline extraction.

Record static poses, distances, tilts, grips, lighting and display content; then
phone-only, headset-only and combined motion. Measure stationary jitter,
position/rotation errors, false associations, ambiguity/loss fraction, processing
latency and time to reacquire. Report failures and projected phone pixel size
alongside successful trials.

Test missing/covered edges, both cameras covered, capture pauses, broker restarts,
phone disconnect/reconnect and changed dimensions. Stale/lost output must clear;
reacquisition must not silently associate the IMU with another rectangle.

See [recording/replay instructions](MARKERLESS_DIAGNOSTIC.md). Low reprojection
error and an attractive overlay are diagnostic evidence, not independent ground
truth. Camera/XR alignment and inertial prediction remain future validation work.
