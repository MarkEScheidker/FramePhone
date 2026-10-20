# Decision: tracking a changing display through the Frame cameras

Research and decision: 2026-10-19. Proposed implementation, not a hardware result.
This refines the [full implementation plan](SCREEN_CONTENT_TRACKING_PLAN.md).

Implementation update, 2026-10-19: the [static-photo test](PHOTO_TRACKING.md) now
integrates XFeat/LighterGlue, calibrated search views and a last-pose search region.
It bundles pinned CPU inference and models, with normalized patch tracking after
acquisition. Dynamic references, photometric pose refinement, TinyRoMa comparison
and ARCore/world alignment below remain planned.
Synthetic model/replay tests do not establish real headset acquisition.

## Chosen approach

Use **pretrained XFeat + LighterGlue for acquisition and recovery**, followed by
**local alignment against the time-appropriate screen reference**. Keep factory
KB4 geometry and robust stereo pose fitting. Use **ARCore and headset pose
histories for continuous motion**, with screen observations correcting their
registration when visibility and content allow it.

The next experiment compares XFeat/LighterGlue and TinyRoMa against the existing
RootSIFT baseline on the same real recordings. XFeat/LighterGlue is the first
integration target. TinyRoMa is the bounded dense-matching alternative if sparse
feature repeatability is the problem. No phone-specific network training.

The important change is that the target is a physical display with a stream of
known textures. A texture change must not become a change in physical pose.

## Evidence and component selection

| Component | Relevant evidence | Decision |
| --- | --- | --- |
| XFeat + LighterGlue | Official pretrained models, compact XFeat descriptors, CPU-oriented extraction, learned association. XFeat's network processes grayscale. Published CPU results use a laptop; they do not establish Frame performance. | First acquisition/recovery backend. Cache reference features; bound feature counts and candidate views. |
| TinyRoMa | Official small dense matcher built on XFeat, with pretrained weights and correspondence confidence. Its implementation forms an all-pairs correlation volume. | One offline comparison, particularly for cases where repeatable sparse keypoints are absent. Bound input size/regions; do not run dense matching across every full-resolution view/reference. |
| RootSIFT | Already integrated, with replay support; the owner reports no hardware acquisition. | Baseline and diagnostic comparison, not the assumed product solution. |
| Ordinary EfficientLoFTR | Pretrained semi-dense matching; the authors note an indoor domain gap for default outdoor weights. | Defer behind the two lightweight candidates; its standard GPU examples do not prove an ARM64 runtime. |
| MatchAnything-ELOFTR | Specifically targets appearance differences across imaging modalities. Upstream currently uses a registration license while the community model card says Apache-2.0. | Not a bundled dependency for this experiment. Revisit only with established artifact/license provenance and a demonstrated appearance-gap need. |
| Full RoMa / RoMa v2 | Dense correspondence alternatives; v2 includes a DINOv3 dependency with its own license. | Defer: unnecessary initial runtime/dependency scope for the first acquisition test. |
| Normalized patches / ECC | Local image alignment is reusable once the rough geometric alignment is known. ECC explicitly requires suitable initialization for large motion. | Fast refinement after acquisition, with fresh reference content and explicit validity masks. Not a global detector. |

Sources: [XFeat and LighterGlue](https://github.com/verlab/accelerated_features),
[XFeat grayscale model](https://github.com/verlab/accelerated_features/blob/main/modules/model.py),
[TinyRoMa](https://github.com/Parskatt/RoMa#tiny-roma),
[TinyRoMa implementation](https://github.com/Parskatt/RoMa/blob/main/romatch/models/tiny.py),
[EfficientLoFTR](https://github.com/zju3dv/EfficientLoFTR),
[MatchAnything upstream license](https://github.com/zju3dv/MatchAnything/blob/main/LICENSE),
[community model card](https://huggingface.co/zju-community/matchanything_eloftr),
[RoMa v2](https://github.com/Parskatt/RoMaV2),
[OpenCV local alignment](https://docs.opencv.org/4.x/dc/d6b/group__video__track.html).

There is precedent for matching changing display content: Sörös et al. separate
target detection from patch tracking and refresh the target database when content
changes. However, their prototype assumes relatively infrequent changes, reports
interruption/reinitialization on abrupt updates, and failed a glossy-screen test
with significant reflections. It supports the architecture, not a claim that
rapid phone scrolling or our cameras are solved.
[Author-hosted paper](https://www.cg.tuwien.ac.at/research/publications/2011/Soros_AVN_2011/Soros_AVN_2011-Paper.pdf).

## Treat reference time as part of the measurement

Every reference needs an immutable frame ID, source timestamp and clock domain,
capture/receive times, geometry generation, dimensions, crop/rotation mapping and
the image or retained feature representation. Every camera observation also keeps
its capture time, camera/calibration identity and exposure metadata when available.

Start with a bounded one-second reference history, initially capturing/transferring
up to 30 images/s with a 960-pixel long edge and explicit gaps when work is dropped.
These are prototype settings to measure, not sufficient rates for every display
animation. Deduplicate unchanged images while preserving their observed time
intervals. Bound history by both time and memory. Cache learned features only for
the small candidate set actually being evaluated.

Map phone and headset clocks using the existing probes, extended with uncertainty
and drift checks. Android Image timestamps are source-dependent; neither those
timestamps nor packet arrival time establish physical screen presentation time.
Measure the relationship between captured references and visible updates using a
temporary test sequence in our own app. Preserve separate clock mappings for
screen capture, ARCore camera images and headset camera capture. ARCore exposes
both frame and Android camera timestamps for correlation.
[Android Image timestamps](https://developer.android.com/reference/android/media/Image#getTimestamp()),
[ARCore Frame](https://developers.google.com/ar/reference/java/com/google/ar/core/Frame).

At a camera exposure, choose a small set of plausible reference times based on
the mapped timestamps and their uncertainty, including neighboring references
that have arrived by processing time. Verify image agreement to select among
them. Do not always use the newest network image, search the entire history, or
stall the pipeline indefinitely waiting for a reference. If none is compatible,
skip the optical correction and retain explicit uncertainty.

Display refresh, exposure and motion can produce observations incompatible with
one pristine screenshot. First reject inconsistent patches or the measurement;
record the residuals. A row/readout or mixed-reference model is a later addition
only if recordings show it is necessary. Do not assume the Frame sensors use a
particular shutter/readout model without verifying it.

## Acquire in calibrated views, then track locally

1. Cover the usable field of the **two front cameras** with overlapping calibrated
   perspective tiles. Preserve sufficient native angular detail. Keep tile-to-raw
   pixel/ray mappings and deduplicate overlap; avoid stretching the entire
   fisheye into a single extreme perspective image. Bound global search work.
2. Match the candidate reference using XFeat/LighterGlue, at scales appropriate
   to the observed footprint. Preserve aspect ratio/padding maps. Estimate a
   robust planar correspondence hypothesis in the perspective tile; validate
   spatial support and competing hypotheses. No complete outline or four visible
   screen corners is required.
3. Map observations to factory-calibrated native rays and estimate the rigid
   screen pose. Retain geometric inliers and image evidence separately.
4. After acquisition, use predicted pose to search a small native-detail region.
   Warp the **candidate current reference** toward each camera. Refine supported
   patches with normalized correlation/local alignment and reject outliers.
   Prototype the alignment with existing OpenCV functions; the eventual pose
   update must remain constrained by common screen geometry and both cameras.
5. Periodically run learned matching to refresh associations and detect drift.
   Increase acquisition effort after loss, under a bounded fresh-work schedule.
   Prediction is only a search prior: large residuals trigger recovery.

KB4 calibration already provides pixel-to-ray conversion. Additional perspective
views use the rectification rotation/destination matrix exposed by OpenCV; final
pose quality is evaluated with native KB4 projections, not a homography on raw
fisheye pixels. This is our proposed tiling design using established mappings.
[OpenCV fisheye mapping](https://docs.opencv.org/4.x/db/d58/group__calib3d__fisheye.html).

### Prevent scrolling from moving the phone

For an unchanged reference, forward/backward-checked optical flow may propagate
verified observations. For a changed reference, invalidate affected patches and
seed or match them from the new reference at their **current screen coordinates**.
Initially discard/reseed changed areas rather than implementing screenshot-to-
screenshot content-flow compensation. A complete app switch discards all old
texture associations but keeps healthy motion/geometry state.

For example, a stationary phone displaying a scrolling page must still estimate
zero physical motion. A text feature that moves down the page no longer has its
old screen coordinate. Carrying its old identity through ordinary camera optical
flow would create a false pose update. Alignment against the current reference
tests what the camera should see for a candidate physical pose.

Phone screenshots are obtained with authorized whole-display MediaProjection
for Home/app switching. Capture geometry changes create a new geometry generation;
content frame changes do not. Secure/unavailable capture and empty content yield
no screen correction. Existing fixed-photo mode remains a useful test source;
continuous reference capture/transport is not implemented yet.
[Android MediaProjection](https://developer.android.com/media/grow/media-projection).

## Appearance, partial views and stereo

Keep canonical color references for replay, derive grayscale matching inputs and
compare raw/normalized contrast variants on identical captures. XFeat internally
uses grayscale, but this does not establish a photometric match between Android
RGB and each camera. Compare blur scales representing the actual screen footprint
and conservative noise reduction. Avoid aggressive preprocessing that removes text
strokes or amplifies noise. Mask clipped, reflective or occluded patches based on
measured image evidence and robust residuals; adaptive phone brightness does not
control camera exposure.

Fit one screen pose to **all verified reference-to-camera observations**. The
current code requires a common stereo feature set; that can discard useful
partial views when each camera recognizes different parts of the screen. After
screen metric geometry is established, a joint rig reprojection solve can use
different screen points in each camera. This proposed extension must retain
outlier rejection and conditioning checks; it is not implemented.

For normalized screen point q, estimate pose R,t and initial physical scale s by
minimizing robust native-pixel residuals between observed pixels and each
camera's projection of `R * (s * q) + t`. Known factory camera origins fix the
metric baseline. Initialize scale from good overlapping stereo as today; later
joint pose-and-scale initialization from nonidentical observations is a separate
validation task. PoseLib's generalized-camera solvers are a research reference,
not a claim that its minimal solver is a verified drop-in for our planar case.
[PoseLib generalized cameras](https://github.com/PoseLib/PoseLib#generalized-cameras).

Assess uncertainty from view geometry, residuals, spatial support and competing
planar solutions. Numerous dense samples in one small patch do not create
independent geometric evidence. A narrow/collinear visible region or weak scale
conditioning must not be promoted into a confident 6DoF correction.

## Continuous pose and delayed corrections

The product's fast motion source should be ARCore, with calibrated phone-camera
to screen/body offset and timestamped headset poses. Optical matching supplies
occasional observations of the transform between their worlds. Apply each
observation at its exposure time through pose histories; do not compose an old
visual pose with the headset's current pose. Reset/invalidate registration on
anchor/session/recenter changes as specified in the full plan.

Report measured, ARCore-bridged and lost states explicitly. A blank screen,
occlusion or a content transition can suspend corrections while healthy ARCore
motion continues. Unhealthy ARCore plus missing optical observations is real
tracking loss; raw accelerometer integration is not a position substitute.
Proposed initial optical correction rate: 5–10 Hz, independent of the pose/render
loop. All rates need measurement on the headset.
[ARCore motion fundamentals](https://developers.google.com/ar/develop/fundamentals).

## Next implementation experiment and decision gates

1. Build a development-only replay harness with native camera/calibration input
   and interchangeable RootSIFT, XFeat/LighterGlue and TinyRoMa backends. Start with
   official pretrained inference on a desktop; do not add a model to the release
   package before correspondence quality is demonstrated. Run the selected
   backend on Frame to measure actual latency/memory before adopting it.
2. Evaluate current fixed-photo captures first, preserving selected photo and
   exact native stereo images. If none are available, add a convenient bounded
   export of the existing recorded session. Annotating evaluation examples is
   test work and does not require training a network or manual user initialization.
3. Add a controlled changing-image source in the Android app: known photo/page
   sequences with frame IDs and logged update/capture times. Hold both devices
   stationary while content changes, then repeat with physical motion. It tests
   reference selection and motion/content separation before whole-display capture.
4. Add timestamped MediaProjection reference history and real Home/app switching.
   Include scrolling, animation, rotation, partial hand occlusion, camera-edge
   views, lighting/brightness variation and negative scenes. Hold out content and
   recording sessions from parameter selection; record native screen footprint.
   Test physical phone roll (including 90 degrees) separately from capture-layout
   rotation. Do not assume learned descriptors are rotation invariant; if needed,
   compare bounded rotated-reference hypotheses with exact inverse coordinate
   maps. Include competing screens with similar UI in negative/ambiguity tests.
5. Add bounded local alignment and ARCore/headset registration after optical
   measurements pass the preceding gates. Export/port the selected inference
   backend only with parity tests against official inference, pinned weights and
   complete notices. Keep runtime installation inside the existing single .run.

Proposed go/no-go targets, not achieved results:

- At normal viewing distances, textured-screen acquisition in at least 90% of
  clearly visible trials within one second; report results by native screen size,
  camera angle and visible fraction rather than hiding hard cases in one average.
- Useful acquisition with roughly half the textured screen visible; measure the
  actual support/conditioning boundary. No universal visibility percentage is
  assumed sufficient.
- Zero accepted poses in the collected negative-scene set, including other
  rectangles, repeated text and stale/wrong references. Report sample counts and
  false hypotheses; a finite test does not establish a zero false-positive rate.
- With phone/headset stationary, scrolling/app changes should not introduce pose
  excursions beyond the proposed 1 cm / 2 degree bench target. This tests content
  leakage; physical accuracy also needs independent measurements.
- Target 5–10 optical checks/s with a bounded queue; record p50/p95 latency, CPU,
  peak memory, thermal behavior and time spent without usable corrections on
  Frame. A desktop benchmark or neural match count alone is not the acceptance
  criterion.

If all candidates fail on the same real reference/camera crops, investigate
appearance, clipping, calibration or missing reference times before selecting
another network. If matches are strong but pose is rejected, investigate geometry
and association separately. This experiment must identify the failing stage.
