# Tracking validation

Software checks do not establish real camera accuracy or headset performance.
Pairing, stereo fiducial pose tracking and the VR rectangle have been
demonstrated on the owner's headset. Reported stability and apparent accuracy
are informal observations; metric errors still need independent physical trials.

## Automated checks

- Portable frame validation, timestamped PGM replay and independent ring-writer tests.
- Factory camera discovery and the packaged synthetic geometry self-test.
- Independently rendered frontal/tilted/rotated KB4 stereo tag rasters, decoded
  corner orientation, metric pose, invalid calibration/skew and loss/reacquisition.
- Android marker pixels checked against the official tag36h11 renderer.
- Native automatic decode/pose replay, exact frame provenance and bounded previews.
- Real Tk start/counts/live pose, camera preview and loss/disconnect clearing.
- TLS pairing/reconnect, credential pinning and opt-in telemetry recording.

CMake/CTest runs native checks. CI also runs desktop/TLS tests, Tk under Xvfb,
and packaged execution on Linux architectures. Tests require AprilTag, OpenCV and JSON,
plus Python/Tk for GUI integration. No camera privileges are needed.

## Hardware trials

Verify the selected front lenses, factory mapping, native resolution and clock
domain. Use a measured phone/case and independent position/angle references.
Start with a supported stationary phone and fully visible marker/white margin.
Verify reported display-DPI scale against independent distances before claiming
metric accuracy; phone/case width is not the marker's black-edge width.

Record static poses, distances, tilts, grips, lighting and display content; then
phone-only, headset-only and combined motion. Measure stationary jitter,
position/rotation errors, false associations, ambiguity/loss fraction, processing
latency and time to reacquire. Report failures and projected phone pixel size
alongside successful trials.

Test missing/covered edges, both cameras covered, capture pauses, broker restarts,
phone disconnect/reconnect and changed dimensions. Stale/lost output must clear;
reacquisition must not silently associate the IMU with a second phone using ID 0.

See [recording/replay instructions](FIDUCIAL_TRACKING.md). Low reprojection
error and an attractive overlay are diagnostic evidence, not independent ground
truth. Camera/XR alignment and inertial prediction remain future validation work.
