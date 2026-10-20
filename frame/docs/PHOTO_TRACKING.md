# Fixed-photo stereo test

This milestone automatically matches one user-selected photo in the two front
Frame cameras and measures its head-relative position, orientation, distance and
physical size. The phone sends the photo once over the existing paired TLS link.
There is no screen recording, neural model download or manual corner selection.

## Run on the devices

1. Install the updated Android APK. Start the phone connection and pair/connect
   in Frame's **Phone telemetry** tab as before.
2. On the phone, tap **Choose tracking photo** and select a detailed ordinary
   photo. Avoid a largely blank image. The app prepares a bounded reference and
   opens it full-screen in a fixed portrait layout so the reference stays rigid
   to the phone when it rotates. Tap the photo or Back to return; **Show tracking photo**
   opens it again. The selected reference lives in memory for this app process.
   The app leaves brightness under Android/user control, including adaptive
   brightness when enabled; it no longer forces maximum brightness. If the
   display looks white/clipped in the Frame cameras, lower brightness or reduce
   glare. Room-based adaptive brightness does not guarantee correct camera exposure.
3. On Frame, open **Photo tracking** and click **Use phone photo**. Confirm the
   thumbnail and downloaded dimensions. This is a one-time request, not streaming.
4. Enable cameras, approve desktop authorization and refresh. Verify the physical
   two front streams and corresponding factory calibrations. Expected defaults
   are video3/slam_left and video0/slam_right; cover lenses to check identity.
5. Keep the photo visible on the phone and click **Start photo tracking**. Begin
   at a normal viewing distance with slow motion and both cameras seeing it.

The same build command works on a Linux PC or the headset:

```bash
bash frame/build.sh
```

Open `frame/build/dist/FramePhone-arm64.run` on Frame. The package includes
OpenCV, Pillow, Python/Tk and the camera broker. No Frametop install is required.
APK output is `phone/app/build/outputs/apk/debug/app-debug.apk` after the normal
Android build. Both applications need updating for the new photo commands.

## What to expect

The UI shows reference features and left/right camera features, descriptor
matches, homography inliers, stereo correspondences, triangulated points, pose
inliers, processing time and a rejection reason with a suggested next step.
A dashed blue boundary shows the area searched in each raw camera view; keep the
photo inside both boundaries. Amber dots show per-view homography inliers even
when no pose is accepted. These are image observations, not a valid 3D pose.
Green features and a curved photo outline mark an accepted stereo pose. It reports photo-center
XYZ in meters, distance from factory head origin, Z/Y/X Euler angles, estimated
photo width/height and two-view reprojection RMS.

This is **T_HP**, where P is the displayed photo center, X is photo right, Y is
photo up and Z points out of the display. H is the imported factory head frame:
X right, Y up, Z backward. A forward phone normally has negative Z. Black
letterbox bars are outside the photo. Photo size is not phone/case size; the
camera-to-phone/screen rigid offset is not yet calibrated.

No accepted pose means no current pose. Loss, stale results, leaving the photo,
reference changes, camera mapping changes and disconnect clear the displayed
pose. Reveal the photo to test optical reacquisition; if the phone leaves its
photo Activity, show it again and restart the test. Changing the selected photo
requires another download. Camera recording is optional and bounded to 512 MiB.

## Geometry and robustness

The factory KB4 model already provides exactly the pixel-to-direction mapping
needed here: `RigCamera::ray({u,v})` returns a unit viewing ray in H coordinates.
The ray starts at the calibrated camera origin. Matched observations in both
views are intersected in metric space using the factory stereo baseline.
[OpenCV's fisheye model](https://docs.opencv.org/4.x/db/d58/group__calib3d__fisheye.html)
uses the same angular projection form.

The implementation caches multi-scale SIFT reference descriptors (long edges
60/120/240/480/960 pixels, limited to the source size). It applies
[RootSIFT normalization](https://www.robots.ox.ac.uk/~vgg/publications/2012/Arandjelovic12/arandjelovic12.pdf)
to reference and camera descriptors. Matching retains up to a 1280-pixel camera
long edge instead of resizing 1280-pixel inputs to 960. It matches in calibrated
perspective images, filters homographies and joins observations using both shared
reference locations and direct descriptor matching between the verified camera
observations. Multiple SIFT orientations at one location are grouped; stereo
observations are not counted twice. Direct stereo matches must also agree with
the other view's reference homography. It maps those observations back to raw pixels,
triangulates, robustly fits a scaled rigid plane and jointly refines rotation,
translation and scale against native KB4 projections in both views. Orientation
comes from the photo's known coordinate layout; scale comes from stereo, not DPI
or entered body dimensions. No requirement to detect all four photo corners.

Acceptance requires at least 12 surviving stereo features, at least 12% reference
convex-hull coverage, plausible scale/facing/depth and bounded native reprojection
error. Missing/weak/inconsistent observations are rejected. Matching currently
uses the central calibrated perspective view, so extreme peripheral/fisheye views
can fail to acquire. This first CPU SIFT implementation has no ARCore prediction
or learned feature matcher yet; headset speed and ordinary-photo reliability
still need measurement.

A QR code selected as a photo is currently ordinary reference texture: this path
does not decode QR codes or use their finder-pattern geometry. Repetitive patterns
can fail descriptor matching even when a purpose-built marker detector would see
them. Start with a detailed photo containing distinctive larger shapes. Sparse
feature matching still needs enough visible image detail; the code cannot recover
detail lost to clipping, blur or a very small screen footprint.

If acquisition fails, the diagnostic stages separate the causes:

- Few camera features: inspect visibility, clipping, blur and the blue search area.
- Camera features but few reference matches: the reference is not recognized in
  both views; try a closer, less reflective view or a different photo.
- Photo inliers in both views but few stereo matches: cross-camera association
  failed; a 2D recognition is not sufficient for a stereo pose.
- Many stereo matches but few triangulated points: verify the two physical front
  stream/calibration assignments and hold still. Wrong mapping or inconsistent
  observations can reject the stereo rays.
- Triangulated points but no accepted pose: the plane fit, coverage or
  reprojection checks failed. Read the displayed reason; acceptance is not relaxed.

The optical test preserves camera timestamps and clock identity. It does not
claim camera-to-XR clock alignment, motion compensation, tracking covariance or
Valve-controller-level reliability. Controller tracking has known emitter
geometry and visual/inertial fusion; merely observing that it works does not
provide an interchangeable arbitrary-photo tracker.

## Next: anchored phone motion and incremental alignment

After verifying optical pose on real captures, add ARCore anchored camera poses,
the camera-to-photo/screen rigid offset, historical headset world pose and clock
mapping. At matching exposure time t, with T_AB mapping B into A:

`T_WA_observed(t) = T_WH(t) * T_HP(t) * inverse(T_AQ(t) * T_QP)`

W is the headset runtime world, A the phone anchor and Q the phone camera. Verify
the factory-head/runtime-head transform before composing them. Gate and robustly
combine successive alignment observations; the moving headset frame itself is
not a fixed world reference. Reject weak visual corrections and let healthy
ARCore motion bridge them. Camera-to-screen calibration and world alignment
cannot both be determined from one arbitrary pose.

These integrations are **not active in this milestone**. Outputs explicitly say
`alignment_status: not_implemented`. See the
[full implementation plan](SCREEN_CONTENT_TRACKING_PLAN.md).

## Replay and wire format

A private `photo-*` session contains copied factory calibration, canonical color
PNG, derived grayscale PGM and `framephone-photo-session-v1` metadata. Its run
directory contains bounded JSONL results, three overwritten preview slots and,
if enabled, a paired-camera recording. The selected reference is saved locally
as part of starting this explicit photo test.

```bash
./FramePhone-arm64.run -- --photo --session SESSION --replay RECORDING --output NEW_DIR
```

New `framephone-photo-pose-v1` results include reference identity, capture times,
per-stage counts, per-view homography observations (`view_points`, up to 256 per
view), matching boundaries (`search_outline`), raw accepted correspondences,
pose/scale, coverage and quality. Diagnostic observations are emitted on rejected
results too; `matches` and `pose` remain reserved for accepted stereo poses.
Rejected results contain no current pose. Scale is factory-derived and still
needs independent accuracy validation.

The existing v1 TLS framing remains at 64 KiB/message. The client opts in with
`photo_reference_v1: true` in hello; the server advertises support in its profile.
An authenticated `request_photo` has a random 32-hex request ID. The response is
photo_begin, sequential photo_chunk messages and photo_end, or photo_missing.
Limits: PNG <=2 MiB, dimensions 64..960, aspect 0.2..5, chunk <=16384 bytes before
base64. Receiver verifies request/session, offsets, size, PNG header dimensions
and SHA-256 before publication. Transfer is requested once; photo_state messages
only report selected identity and whether the photo is displayed. Older clients
do not opt in and continue receiving ordinary sensor telemetry.
