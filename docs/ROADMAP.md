# Roadmap

Stereo marker tracking and the ARCore-driven VR rectangle have been demonstrated
on the test devices. The current milestone is reliable recovery and measured
motion timing, Bluetooth device validation and then screen video.

## Current components

- Automatic screen-width marker overlay, width/height setup and pinned LAN control.
- Bluetooth companion association, authenticated trust/LAN bootstrap and BLE poses
  implemented for device testing; explicit Wi-Fi fallback retained.
- Native AprilTag detection, factory KB4 calibration, stereo pose and replay.
- Marker-to-ARCore world registration with two observations spanning 80 ms with up to 8 cm relative movement.
- A latest-only renderer channel, bounded gyro/velocity prediction and rate/age diagnostics.
- Camera access as a standalone module, a bundled broker and one desktop executable.
- Optional bounded recordings of camera, sensor, ARCore and clock evidence.

Metric scale, sensor-to-screen and factory/runtime-head extrinsics are still
provisional. Sleep recovery and the latest prediction changes need physical
validation; software tests do not establish tracking accuracy or latency.

## Next milestones

1. Measure wake/reacquisition, delivered/render rates, motion-to-display delay,
   jitter and steady-state battery/CPU behavior on the actual devices.
2. Calibrate sensor/screen and factory/runtime-head transforms and verify the
   headset exposure clock against historical headset world poses.
3. Handle drift, recenter, tracking resets and pocket relocalization with clear
   validity rules; keep marker reacquisition as the reliable fallback.
4. Validate Bluetooth companion wake, secure Wi-Fi bootstrap and measured pose
   transport on the devices, including Android's cold camera-start restrictions.
   See the [companion session plan](COMPANION_SESSION_PLAN.md).
5. Stream Home and ordinary phone apps into the tracked surface, respecting
   Android's capture lifecycle, and evaluate accessory/input integration.

Full display streaming, shared room maps and a registered virtual controller
are not implemented. Earlier phone-object/photo-matching
experiments have been removed. Private captures and working notes are not source
assets. See [the handoff guide](../frame/docs/ARCORE_HANDOFF.md) for current limits.
