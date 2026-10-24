# Single large AprilTag tracking

The supported optical path uses **tag36h11 ID 0**, displayed once at the center
of the phone. No neural model, model download, manual corners or multi-tag layout
is required. One tag is sufficient; the same tag is observed in both front cameras.

## Try it

1. Install the updated Android APK. Save phone/case dimensions and start/reconnect.
2. Tap **Show fullscreen tracking marker**. It opens a white portrait surface with a
   single sharp, centered marker. Tap anywhere or use Back to return. Telemetry
   continues while the marker is shown.
3. Build Frame using `bash frame/build.sh`, open the new ARM64 executable and
   connect the phone in **Phone telemetry**.
4. Open **Marker tracking**, enable/refresh cameras and verify the two physical
   front streams and their factory associations. Cover lenses to check them.
5. Click **Start tracking** and point the marker at the front cameras. The UI
   reports ID 0 counts for left/right, processing time and pose quality. Tilt and
   move slowly, then hide/reveal the marker to test loss and automatic reacquisition.

Both camera tabs show live per-camera AprilTag outlines and center crosses as
soon as cameras are available, even before Start and without a synchronized
stereo pair. Native preview workers detect on their own frames; they do not need
phone pairing or a calibration/pose solve. A 2D marker outline alone is not a 3D
pose. Missing/stale streams show an explicit per-camera message. The preview
reader accepts padded grayscale rows, as does the tracker.

During tracking the second tab also displays current headset-relative XYZ,
distance, Z/Y/X rotation and RMS. Accepted poses add red X, green Y and blue Z
axes projected through each camera's KB4 model onto the exact tracking frame.
Raw preview frames never borrow pose axes from a different frame. If a rotating
preview slot is unavailable, pose telemetry still updates while the view uses
its independently annotated camera preview.

If no stereo pair arrives, the log reports per-camera frame counts and the latest
capture-time difference against the 3 ms limit. After a timeout, both independent
previews continue. Verify stream selection, freshness and camera timing rather
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
edge refinement. Only ID 0, no corrected bits, and decision margin at least 15
can support pose. A margin is a detector quality metric, not a percentage.
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
