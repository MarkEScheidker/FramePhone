# Fixed-photo stereo test

This milestone automatically matches one user-selected photo in the two front
Frame cameras and measures its head-relative position, orientation, distance and
physical size. The phone sends the photo once over the existing paired TLS link.
The default test uses pretrained XFeat/LighterGlue with native stereo geometry;
RootSIFT remains a comparison mode. There is no screen recording, per-phone model
training, runtime model download or manual corner selection.

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
   Leave **Learned (XFeat/LighterGlue)** selected for this experiment. Hold still
   while search views cycle; after a valid pose the search stays in that view.
   **RootSIFT baseline** runs the earlier matcher against the same selected photo.

**Camera setup → Model check** verifies the bundled neural assets with synthetic
identity-image matching. **Geometry self-test** checks geometry separately.
Neither establishes real-camera acquisition or accuracy. The packaged terminal
`--self-test` runs both checks.

The same build command works on a Linux PC or the headset:

```bash
bash frame/build.sh
```

Open `frame/build/dist/FramePhone-arm64.run` on Frame. The package includes
OpenCV, Pillow, Python/Tk, CPU PyTorch/Kornia, pretrained weights and the camera
broker. The first build fetches pinned models and CPU wheels into the container;
the headset needs no pip/model installation or internet download at runtime.
No Frametop install is required. The learned runtime increases package size and
extracted disk space; use the normal build command on either Linux architecture.
APK output is `phone/app/build/outputs/apk/debug/app-debug.apk` after the normal
Android build. If phone photo selection/transfer already works, this learned
test needs only a rebuilt Frame app; the Android photo flow is unchanged.

## What to expect

The UI shows reference features and left/right camera features, descriptor
matches, homography inliers, stereo correspondences, triangulated points, pose
inliers, processing time and a rejection reason with a suggested next step.
It also identifies feature matching versus local patch tracking, the backend and
current calibrated search view. During patch tracking the feature/match counts
describe the tracked anchor patches rather than a new descriptor extraction.
Model loading can take several seconds before the first result; Stop remains available.
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

## Collect a headset debugging trial

The current app already records a replayable trial; no rebuild or terminal
commands are needed. Camera pairs are more useful than IMU telemetry for an
optical acquisition/stereo failure.

1. Stop tracking, then enable **Record camera trial (512 MiB max)** before
   starting again. Keep the same selected reference photo and camera mappings.
2. Keep the headset level and hold the displayed photo still where both cameras
   can see it for 20–30 seconds. If inference is especially slow, wait for the
   search-view counter to complete a cycle. Then tilt the phone slowly a little
   each way and briefly cover/reveal the screen. Stop before a long recording
   fills the limit. Use a photo and surroundings you are comfortable sharing.
3. Click **Open results**, sort by modification time and find the newest
   `photo-*` directory. The normal location is
   `~/.local/state/framephone/sessions/` (or the configured XDG state directory).
4. Compress that entire `photo-*` directory with the desktop file manager and
   attach the archive to the debugging conversation, or copy it into the shared
   development workspace under `frame/build/debug-captures/` (ignored by Git).
   Stop first so the files are complete.

Keep these files together:

| Path inside the trial | Purpose |
| --- | --- |
| `session.json` | Selected physical streams, factory camera mapping and matcher. |
| `factory/persist/*.json` | The exact intrinsics and camera-to-head transforms used. |
| `reference/` | The exact color/grayscale reference and its identity. |
| `run/poses.jsonl` | Per-pair rejection reasons, matching counts, search view, processing time, camera timestamps and transport diagnostics. |
| `run/paired-images/` | Recorded native grayscale pairs and capture-time manifest, needed for replay. |

The recorder saves pairs processed by the tracker, not a full-rate camera video.
Without recording enabled, `poses.jsonl` still exists but only three overwritten
preview slots remain; those are not a complete trial. Note the approximate phone
distance and whether each raw view appears clockwise or counterclockwise from
upright. Cover each physical front lens separately in **Camera setup** to check
stream identity before collecting another trial if the assignment is uncertain.

The blue boundary is a **search region**, not a phone detection. Before a pose is
accepted, the tracker cycles through calibrated views; the boundary moves with
that search. Amber points are per-camera evidence. A green outline requires an
accepted stereo pose. The Photo tracking previews update after processing each
pair, so their speed is not a measurement of the cameras' native frame rate.

Raw sensor previews can look sideways because of camera mounting. Learned
matching already uses the imported full camera-to-head rotations, including
roll, to make common head-oriented perspective views before extracting features.
This is separate from rotating the preview for readability. A correctly mapped
factory calibration should account for mounting roll. A stream/calibration or
pixel-orientation mismatch can still break this, so check the saved images and
factory transforms before adding another 90-degree rotation. Curved search
boundaries show the projection model is in use; they do not verify its mapping.

`too_few_stereo_feature_matches` means too few reference feature identities
survived in both views. It precedes triangulation. `stereo_triangulation_rejected`
means enough candidate correspondences were supplied but their calibrated rays
were rejected. The recording distinguishes recognition/overlap problems from
geometry, mapping and timing problems; a sideways preview alone cannot.

## Geometry and robustness

The factory KB4 model already provides exactly the pixel-to-direction mapping
needed here: `RigCamera::ray({u,v})` returns a unit viewing ray in H coordinates.
The ray starts at the calibrated camera origin. Matched observations in both
views are intersected in metric space using the factory stereo baseline.
[OpenCV's fisheye model](https://docs.opencv.org/4.x/db/d58/group__calib3d__fisheye.html)
uses the same angular projection form.

The learned backend caches XFeat reference features at 240/480-pixel long edges
and uses the official LighterGlue matcher. It extracts candidates with XFeat,
then retains up to 768 spatially balanced points per image for matching. The
worker is CPU-only, persistent for the session and limited to two Torch threads.
Runtime downloads are disabled and local model hashes are verified before use.
See [model provenance and pins](../third_party/xfeat/README.md).

The native tracker prepares up to nine overlapping perspective views in common
head-space directions, accounting for both cameras' factory extrinsics. Invalid
source pixels are masked. Each new pair searches one view in both cameras;
views with too little usable source area are omitted. A successful view remains
active until three missed pairs restart the search. These are search hints;
every displayed pose still requires a fresh stereo measurement.
While active, a padded region around the last accepted photo limits the feature
search. Extraction retains a stable sampling grid while filtering observations
by that mask; the blue boundary shows the actual search area. Moving outside it
triggers recovery; the previous pose is never returned as a new measurement.

After acquisition, normalized correlation tracks textured interior patches from
the last accepted learned image pair. Forward/backward checks reject inconsistent
patches; fresh observations in both cameras pass the same metric geometry gates.
The previous pose supplies a search and optimization seed only. This handles
modest exposure changes and partial occlusion without rerunning the network on
every good frame. Learned matching attempts to refresh the anchors every ten
successful patch frames and runs immediately when patch tracking fails. This first version
assumes unchanged photo content and modest inter-frame motion; it does not yet
handle scrolling or app switches.

Both backends map observations to native KB4 pixels, require actual stereo
correspondences, triangulate and fit a scaled rigid plane. In addition to
3D-fit initialization, OpenCV planar IPPE candidates from both cameras initialize
joint native-pixel refinement; their unit-scale translations are related through
the factory baseline. Acceptance thresholds remain unchanged. This avoids relying
only on a noisy triangulated plane for initialization. The proposed solver using
nonidentical points in each camera and ARCore fusion remain future work.

If both learned views recognize the photo but shared reference feature IDs cannot
produce a pose, each view's verified homography supplies a search hint for direct
left/right patch matching. The tracker reuses normalized correlation with
subpixel sampling, forward/backward checks and duplicate rejection, bounded to
256 candidate patches. It then passes the measured native-pixel correspondences
through the same triangulation, 12-inlier, coverage and reprojection gates. It
does not infer stereo measurements from predicted photo corners. Results identify
this path as `pose_method: stereo_patch_refinement`; the UI says **stereo patches**.
See the [first recorded headset replay findings](PHOTO_REPLAY_FINDINGS.md).

The RootSIFT baseline caches multi-scale SIFT reference descriptors (long edges
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
error. Missing/weak/inconsistent observations are rejected. RootSIFT uses a
central calibrated perspective view; the learned mode searches additional views.
Neither mode has ARCore prediction yet. Sustained headset speed and ordinary-photo
reliability still need measurement. The CPU learned mode is an experimental
optical test, not the complete motion-tracking product.

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

The saved session records `backend`; replay uses that mode unless overridden:

```bash
./FramePhone-arm64.run -- --photo --session SESSION --replay RECORDING --output NEW_DIR --backend xfeat
```

Use `--backend rootsift` for a baseline replay into a different new output
directory. There is no silent fallback if learned models fail to load. The log
reports the missing dependency/asset or inference error. Native source builds
can still run RootSIFT/geometry tests without Torch; learned source development
also needs the pinned CPU dependencies and fetched model assets. Set
`FRAMEPHONE_PHOTO_MODELS` to their directory. The container recipe handles the
dependency installation and bundling for users.

The existing v1 TLS framing remains at 64 KiB/message. The client opts in with
`photo_reference_v1: true` in hello; the server advertises support in its profile.
An authenticated `request_photo` has a random 32-hex request ID. The response is
photo_begin, sequential photo_chunk messages and photo_end, or photo_missing.
Limits: PNG <=2 MiB, dimensions 64..960, aspect 0.2..5, chunk <=16384 bytes before
base64. Receiver verifies request/session, offsets, size, PNG header dimensions
and SHA-256 before publication. Transfer is requested once; photo_state messages
only report selected identity and whether the photo is displayed. Older clients
do not opt in and continue receiving ordinary sensor telemetry.
