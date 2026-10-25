# Test on Steam Frame

1. Build with **`bash frame/build.sh`** on the headset or a Linux PC. Open
   `frame/build/dist/FramePhone-arm64.run` on Frame after allowing execution.
2. Start the Android phone connection. FramePhone automatically enables cameras
   and searches for the saved phone. Approve the desktop camera authorization
   prompt if shown. For first pairing, use **Connection → Pair new phone** and
   verify the fingerprint on both devices.
3. On the phone tap **Show fullscreen tracking marker**. Keep it displayed.
4. The single dashboard shows compact telemetry and both front camera previews.
   Tag outlines appear before tracking starts. Use **Retry cameras** after a
   startup failure, and **Connection → Reconnect** to retry the saved phone.
5. Click **Start tracking**. Look for left/right ID 0 counts, marker outlines,
   XYZ, distance, angles and reprojection RMS. Tilt and move the phone slowly.
   Red/green/blue axes on the matched camera frames show the accepted 3D pose.
   Amber tag outlines can remain when a stereo pose is rejected.
6. Enable **Show rectangle in VR (SteamVR)**. With SteamVR active, a translucent
   screen-sized rectangle with a green outline should follow the marker. This renderer needs hardware
   validation; its head alignment and motion timing are provisional. Details
   appear under **Activity log** if loading fails.
7. Cover the marker: pose and VR object must disappear. Reveal it: they should
   return automatically. Leaving the marker Activity stops the test; show it and
   Start tracking again. Stop/disconnect must clear the pose and VR display.

The application uses the confirmed video3/slam_left and video0/slam_right
pair. Saved camera mappings are ignored; there are no camera/calibration
selectors. A missing fixed stream reports an error instead of selecting another.
**Show camera views** controls both previews; hiding them leaves tracking active.
**Activity log** expands the log and geometry self-test on the same page.

For calibration, compare marker-center distance with independently measured
positions at several distances and angles. Scale comes from Android's reported
physical DPI; fullscreen sizing alone does not prove millimeter accuracy. The
rectangle is centered at the marker, not a measured case/body origin.

For debugging, enable **Record cameras + telemetry** before
Start. Stop, then use **Open results** and copy the newest complete `tag-*` trial.
Include `tracker.log`, `session.json`, factory data and `run/poses.jsonl`; enable
recording for replayable images. No screen capture or ARCore is involved.

For "no synchronized pair", read `tracker.log`: it now includes left/right frame
counts and the latest capture skew versus the 3 ms gate. Camera previews continue
even after this failure; boxes in those views are per-camera 2D detections.

Camera startup and process errors appear in **Activity log** and `desktop.log`.
Close the previous FramePhone window before opening a rebuilt executable, so startup creates a fresh camera session.

See [single-marker tracking](FIDUCIAL_TRACKING.md), [VR display](VR_DISPLAY.md),
[calibration](CALIBRATION.md), and [validation](TRACKING_VALIDATION.md).
