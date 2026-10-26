# Test on Steam Frame

1. Build with **`bash frame/build.sh`** on the headset or a Linux PC. Open
   `frame/build/dist/FramePhone-arm64.run` on Frame after allowing execution.
2. Start the Android phone connection. FramePhone automatically enables cameras
   and searches for the saved phone. Approve the desktop camera authorization
   prompt if shown. For first pairing, use **Connection → Pair new phone** and
   verify the fingerprint on both devices.
3. Put on the headset and unlock the phone. The marker appears automatically;
   there are no Start/Stop, ARCore mode or VR visibility switches.
4. The dashboard shows compact telemetry and both front camera previews. Point
   the complete marker at both cameras and keep its headset-relative position
   roughly in view for two accepted stereo observations spanning at least 80 ms
   (up to 8 cm relative movement is allowed). ID 0 counts, outlines and pose axes show
   optical acquisition. Amber outlines can remain when a stereo pose is rejected.
5. A screen-sized VR rectangle appears automatically. After stable alignment,
   the phone marker hides and ARCore supplies motion. Optical detection pauses;
   the rectangle should keep following the phone. Preview capture/detection
   rates and ARCore/render rates measure different stages.
6. Lock/unlock the phone to test reacquisition. Back/Home, recent apps or tapping
   the visible marker cancels tracking until the next screen-off/unlock cycle.
   Taking off the headset disables acquisition when proximity or the fallback
   activity state reports inactive. The activity log identifies the source.
7. Disconnect the phone: current pose and VR display must clear. Reconnect and
   unlock to resume automatically. Native tracker/renderer failures retry without
   pressing a tracking button. If the wear sensor is reported unavailable, keep
   SteamVR running and include the presence-source/error lines from Activity log.

The application uses the confirmed video3/slam_left and video0/slam_right
pair. Saved camera mappings are ignored; there are no camera/calibration
selectors. A missing fixed stream reports an error instead of selecting another.
**Show camera views** controls both previews; hiding them leaves tracking active.
**Activity log** expands the log and geometry self-test on the same page.

For calibration, compare marker-center distance with independently measured
positions at several distances and angles. Scale comes from Android's reported
physical DPI; fullscreen sizing alone does not prove millimeter accuracy. The
rectangle is centered at the marker, not a measured case/body origin.

For debugging, enable **Record cameras + telemetry** before connecting the
phone (disconnect/reconnect to begin a new recorded session). Use **Open results**
and copy the newest complete `tag-*` trial after disconnecting. Include
`tracker.log`, `session.json`, factory data and `run/poses.jsonl`; recording adds
replayable images and phone telemetry, without screen capture.

For "no synchronized pair", read `tracker.log` for left/right frame counts and
the latest capture skew versus the 3 ms gate. Native acquisition retries while
the phone marker is available. Per-camera boxes alone are 2D detections.

Camera startup and process errors appear in **Activity log** and `desktop.log`.
Close the previous FramePhone window before opening a rebuilt executable, so startup creates a fresh camera session.

See [single-marker tracking](FIDUCIAL_TRACKING.md), [VR display](VR_DISPLAY.md),
[calibration](CALIBRATION.md), and [validation](TRACKING_VALIDATION.md).
