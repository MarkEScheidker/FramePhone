# Roadmap

The goal is to pull an ordinary phone from a pocket and use its existing apps
and Home screen in Steam Frame, without attached trackers, manual corner picking
or a permanent display marker.

The proposed architecture is ARCore for phone motion, with the phone's streamed
screen content providing automatic visual registration and later corrections
through the two front Frame cameras. See the
[component research and implementation plan](../frame/docs/SCREEN_CONTENT_TRACKING_PLAN.md)
for sources, component choices, calibration, timing and acceptance criteria.

## Working foundation

- Android body dimensions, secure LAN pairing/reconnect and motion telemetry.
- Frame desktop camera views and live paired telemetry confirmed by the owner.
- Bundled camera broker, factory KB4 calibration, stereo pairing and replay tools.
- Shared Linux build producing a single desktop executable with bundled userspace.
- Fixed-photo experiment: Android picker/full-screen view, one-time paired TLS
  transfer and native SIFT/fisheye stereo photo-center pose/scale, with replay and
  synthetic/Tk integration tests. Real-photo headset performance remains unverified.

## Current draft, not the selected product direction

The working tree retains a single-AprilTag implementation and regression tests;
the normal UI now uses the photo experiment. Its code is not evidence
that ARCore, screen capture, headset pose history or world-space fusion exists.
Retain reusable geometry/camera infrastructure; retire the marker-specific path
when the replacement passes device trials.

## Implementation order

1. Capture ordinary phone content and front-camera images; benchmark automatic
   screen matching with ORB, SIFT and an offline pretrained XFeat comparison.
2. Prove ARCore plus whole-display capture survives Home and ordinary app use.
   Handle camera contention and lock/capture-consent recovery explicitly.
3. Estimate metric screen pose and active-display geometry using calibrated
   stereo; validate against independent physical measurements.
4. Add headset pose history, verified clock mappings and automatic calibration
   of both the phone camera-to-screen offset and per-session world alignment.
5. Combine ARCore motion with accepted optical corrections and explicit recovery.
6. Render a tracked outline, integrate the full screen stream, then remove the
   obsolete marker UI/protocol/dependency and update distribution notices.

The first two milestones test the highest-risk assumptions before a full fusion
or rendering rewrite. Screen visibility on actual Frame cameras, background
ARCore and pocket/lock recovery remain unverified. Android requires consent for
each capture session and can stop capture on lock; do not promise silent restart.

## Previous experiment

The owner observed pretrained YOLOX phone detection taking over 1000 ms, missing
phones in roughly 90% of frames and reaching about 40% confidence on the Frame
cameras. Those are trial observations, not a general model benchmark. Known-
screen feature matching solves a different correspondence problem; it still
needs real-device evidence before adoption.
