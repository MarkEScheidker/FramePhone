# Single large AprilTag tracking

The supported optical path uses **tag36h11 ID 0**, displayed once at the center
of the phone. No neural model, model download, manual corners or multi-tag layout
is required. One tag is sufficient; the same tag is observed in both front cameras.

## Try it

1. Install the updated Android APK. Save phone/case dimensions and start/reconnect.
2. While the phone is unlocked and the headset is active, a white overlay with
   one centered marker appears automatically. Back/Home or a tap dismisses it
   and pauses tracking until the next screen-off/unlock cycle.
3. Build Frame using `bash frame/build.sh`, open the new ARM64 executable and
   pair once from Android's **Pair headset** Bluetooth picker. Wi-Fi connects
   and retries automatically; there are no network controls.
4. Approve camera authorization if prompted. The confirmed front camera pair
   is fixed; selectors are not exposed. Its interceptor stays idle until the
   phone marker is visible, and sleeps again after ARCore handoff.
5. Point the marker at the front cameras. Tracking and the VR rectangle start automatically. The UI
   reports ID 0 counts for left/right, processing time and pose quality. Tilt and
   move slowly, then hide/reveal the marker to test loss and automatic reacquisition.

**Show camera views** on the dashboard displays the two front cameras with
AprilTag outlines, center crosses and marker counts. Each native worker annotates
its own frame during active acquisition. A fresh paired-phone marker-visible
signal is required, but a stereo pose need not have been accepted. A 2D outline
alone is not a 3D measurement. Waiting streams and errors have per-camera status.
Images fit and center within their panes, preserving aspect ratio; pose overlays
use the same display transform. Hide the views to stop preview processing while
tracking continues.

During optical acquisition the dashboard displays current headset-relative XYZ,
distance, Z/Y/X rotation and RMS. Accepted poses add red X, green Y and blue Z
axes projected through each camera's KB4 model onto the exact tracking frame.
Raw preview frames never borrow pose axes from a different frame. If a rotating
preview slot is unavailable, pose telemetry still updates while the view uses
its independently annotated camera preview.

If no stereo pair arrives, the log reports per-camera frame counts and the latest
capture-time difference against the 3 ms limit. After a timeout, both independent
previews continue. Check fixed-stream availability, freshness and camera timing rather
than treating per-camera 2D recognition as an accepted stereo pose.

The marker occupies the available screen width including one white quiet cell
around its 8-cell black square. Cells use whole device pixels without interpolation.
The black edge is therefore 8/10 of the complete raster, not the phone width.
No size adjustment or ruler entry is required. Android's reported display DPI
converts that known pixel edge to an estimated metric edge. OEM DPI reports,
multi-window/compatibility scaling, foldables and resolution changes can bias
scale. Use full-screen portrait on an ordinary phone and validate distance
against an independent reference. The negotiated marker-state messages refresh the profile from the actual drawn fullscreen surface. Leaving that surface stops the tracking trial.

## Pose and quality

AprilTag 3 detects the native Gray8 image with two CPU threads, decimation 1 and
edge refinement. ID 0 supports pose with at most two corrected data cells;
minimum margin is 15 for intact codes and 25 for corrected codes. A margin is a detector quality metric, not a percentage.
Duplicate ID 0s in either view prevent pose; other tag IDs are drawn but ignored.
Keep the black border and white margin visible; a finger covering the only tag
can lose tracking. Angled tags are supported within visibility/calibration limits.

The decoded corner order resolves the marker's orientation without a user
labelling top/front. Factory KB4 rays seed IPPE hypotheses and a triangulated
rigid fit; a joint two-view raw-pixel refinement estimates one common pose.
Capture skew must be <=3 ms in one shared clock. Reprojection gates remain
2.5px RMS and 4px maximum, with competing minima retained as ambiguity.
There is no stale-pose extrapolation, IMU fusion or world transform.

Output is **T_HM**: marker center to head, meters, marker X right/Y decoded top/
Z toward the viewer; head axes right/up/back. The phone body's dimensions do
not determine the marker's physical offset from the case or active display.
No unmeasured marker-to-body transform is claimed. Scale is marked
`phone_reported_unverified`.

When either view lacks a unique usable marker, pose is lost and old pose text
is cleared. Decode continues and reacquires automatically. If one camera sees
a marker the counts still show it, but this stereo path requires both for pose.
No monocular fallback is silently accepted. Stopped/stale/disconnected states
also clear current pose.

## Partial image damage

The decoder permits up to two corrected data cells using AprilTag's upstream
error-correction facility. Corrected codes need margin >=25; intact codes need
margin >=15. Both views must still supply ID 0 and pass the joint stereo gates.
This can recover small interior damage; it does not reconstruct a covered border
or corner, nor does it use a stale pose as a fresh observation. See
[tracking research](TRACKING_RESEARCH.md) for the bounded optical-flow and board
alternatives considered for more substantial occlusion.

## Local recording and replay

Optional **Record cameras + telemetry** is off by default.
It records the two camera streams, not the phone's screen.
Results live under `~/.local/state/framephone/sessions/tag-*/`:
`session.json`, exact `factory/persist/` files, `run/poses.jsonl`,
three rotating preview slots, optional `run/paired-images/`, and optional
`telemetry.jsonl`. Startup/errors are saved to `tracker.log`; `vr-pose.json` is a transient pose publication for the VR helper. Images stop at 512 MiB, pose logs at 128 MiB, telemetry at
32 MiB with a bounded queue. Preview tokens bind overlays to their exact pair.

```bash
framephone-fiducial --session /path/to/tag-trial --replay /path/to/tag-trial/run/paired-images --output /path/to/new-output
```

Replay needs no phone/cameras but uses the saved factory calibration/profile.
There is no compatible replay of the removed markerless session schema.

Session schema: `framephone-fiducial-session-v1`. Result schema:
`framephone-fiducial-pose-v1`, with status/reason, per-view detections
(ID/hamming/margin/corners), capture identities/times, processing time, marker
profile and diagnostic pose candidates. Only status `measured` is a current pose.

See [calibration](CALIBRATION.md), [validation](TRACKING_VALIDATION.md),
[VR calibration display](VR_DISPLAY.md) and
[AprilTag license](../third_party/apriltag/LICENSE).

ARCore registration needs two distinct consistent stereo observations, with no
additional timed dwell; geometric and clock-quality checks still apply.
