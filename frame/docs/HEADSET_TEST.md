# Test on Steam Frame

1. Build with **`bash frame/build.sh`** on the headset or a Linux PC. Open
   `frame/build/dist/FramePhone-arm64.run` on Frame after allowing execution.
2. Build/install the updated Android APK. Save phone/case dimensions, start its
   connection, then pair/connect through Frame's **Phone telemetry** tab.
3. On the phone tap **Show fullscreen tracking marker**. Keep it displayed.
4. On Frame open **Marker tracking**, enable cameras and approve authorization.
   Refresh cameras and verify the two physical front streams and factory mappings.
   Both live views should already show tag outlines/centers without Start. If one
   stream is missing, its caption identifies it while the other view stays live.
5. Click **Start tracking**. Look for left/right ID 0 counts, marker outlines,
   XYZ, distance, angles and reprojection RMS. Tilt and move the phone slowly.
   Red/green/blue axes on the matched camera frames show the accepted 3D pose.
   Amber tag outlines can remain when a stereo pose is rejected.
6. Enable **Show tracked screen in VR (SteamVR)**. With SteamVR active, a thin
   screen-shaped object should follow the marker. This renderer needs hardware
   validation; its head alignment and motion timing are provisional. Details
   appear under **Camera setup** if loading fails.
7. Cover the marker: pose and VR object must disappear. Reveal it: they should
   return automatically. Leaving the marker Activity stops the test; show it and
   Start tracking again. Stop/disconnect must clear the pose and VR display.

Expected front defaults are video3/slam_left and video0/slam_right, but cover
lenses to verify both physical identity and calibration mapping. Side cameras
are not used. **Camera setup → Show front camera views** provides native/full-size
previews. Geometry self-test exercises synthetic detection and pose, not hardware
accuracy or successful SteamVR integration.

For calibration, compare marker-center distance with independently measured
positions at several distances and angles. Scale comes from Android's reported
physical DPI; fullscreen sizing alone does not prove millimeter accuracy. The
screen slab is centered at the marker, not a measured case/body origin.

For debugging, enable **Record cameras + telemetry** before
Start. Stop, then use **Open results** and copy the newest complete `tag-*` trial.
Include `tracker.log`, `session.json`, factory data and `run/poses.jsonl`; enable
recording for replayable images. No screen capture or ARCore is involved.

For "no synchronized pair", read `tracker.log`: it now includes left/right frame
counts and the latest capture skew versus the 3 ms gate. Camera previews continue
even after this failure; boxes in those views are per-camera 2D detections.

For a black camera view, check its sequence/published/dropped counters. Zero
published frames means no usable image has reached that stream's ring; increasing
dropped counts means the broker is rejecting buffers. Increasing published counts
with no annotated image suggests a reader/detector issue. These counters narrow
the failure; they do not prove its hardware cause. Allow camera startup to settle.
Use **Open results** to find `camera-status.json` alongside the trial folders and
include it with the Camera setup log. It is saved when previews are unavailable
or paused and contains camera identifiers/counters, not images or pairing secrets.
The updated broker also reports capture events, candidate buffer count and whether
the queue is mapped or still learning. Zero published/dropped counts can occur
during learning; they alone do not prove the sensor is inactive. Events increasing
while learning identifies a queue-mapping problem. The learning-event count may
reset when a failed attempt expands the buffer candidates; the Camera setup log
reports that expansion. A rising capture-event count with zero published frames
does not require changing tag size, lighting or pose settings. No candidate buffers means
discovery could not attach the DMA buffers; no events with candidates/mapping
requires checking the capture event route or XRService's stream activity.
Close the previous FramePhone window fully before launching a rebuilt executable,
then enable cameras again so the new broker owns a fresh discovery session.

See [single-marker tracking](FIDUCIAL_TRACKING.md), [VR display](VR_DISPLAY.md),
[calibration](CALIBRATION.md), and [validation](TRACKING_VALIDATION.md).
