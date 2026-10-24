# Roadmap

The immediate milestone is a continuously visible fullscreen AprilTag tracked
by the two front Frame cameras, with a simple pose-driven screen object in VR.
This establishes an optical baseline for testing geometry, scale and timing.

## Current components

- Android fullscreen marker, saved body dimensions and secure LAN telemetry.
- Native AprilTag detection, factory KB4 calibration, stereo pose and replay.
- Camera previews, marker counts, pose diagnostics and opt-in trial recording.
- A single executable with desktop controls and the bundled camera broker.
- An optional head-relative SteamVR screen-slab renderer awaiting hardware validation.

## Next milestones

1. Validate physical front-camera/calibration associations, marker distance scale,
   orientation, loss/reacquisition and VR surface alignment on the headset.
2. Add historical headset world poses, exposure-clock mapping and verified
   factory-head/runtime-head calibration. Measure latency before compensation.
3. Prove ARCore camera tracking can continue across Home and ordinary app use on
   the actual phone. Calibrate its camera-to-screen rigid transform separately.
4. Use a brief marker observation batch to align anchored ARCore motion with
   headset world tracking. Hide the marker only after verified alignment; handle
   drift, tracking loss, recenter, session reset and pocket recovery explicitly.
5. Stream ordinary phone apps/Home into the tracked screen and evaluate whether
   native SteamVR accessory registration/input bindings are useful.

ARCore, shared room maps, full display capture/streaming and a registered virtual
controller are not implemented. The discarded phone-object and arbitrary-photo
matching experiments have been removed rather than retained as alternate product
paths. Local private recordings and working notes are not source assets.
