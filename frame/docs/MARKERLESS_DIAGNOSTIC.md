# Markerless phone-body diagnostic

For automatic acquisition without clicking corners, use **Start phone detection**
and the [automatic detection guide](AUTO_DETECTION.md). The manual workflow below
is an optional geometry diagnostic; it does not gate the detector.

This is the first optical implementation from the [tracking plan](MARKERLESS_TRACKING.md):
labelled stereo initialization, metric body pose, a conservative live outline
tracker, and reproducible recordings. It is a development baseline, not yet the
final automatic phone acquisition or occlusion-tolerant tracker. No neural model,
custom training, permanent fiducial, or new Android build is required.

## Build and try it on Frame

Use the existing **`bash frame/build.sh`** build and open the resulting
**`frame/build/dist/FramePhone-arm64.run`** on the headset. The new native tool
and its OpenCV dependencies are included in the same package. The build process
is unchanged on a Linux PC or the headset.

1. Connect the phone in **Phone telemetry**. Check that the entered dimensions
   describe the outside **body/case**, in its natural portrait orientation.
2. Open **Markerless tracking**, choose **Enable cameras**, and approve camera
   access. Refresh if necessary. Verify the two front streams by covering lenses;
   their factory-calibration mapping is still provisional. The native estimator
   rejects camera/calibration image-size mismatches.
3. Hold the phone facing the headset, with all four front edges visible in both
   views, against a contrasting background. Support the phone and headset if
   possible: the first trial starts from this pose. Choose **Capture pair**.
4. In **each frozen image**, click the body's physical **top-left → top-right →
   bottom-right → bottom-left** corners. Physical top is the phone's top, even if
   rotated in the image. Select the outside front rim, not the active display or
   a rear silhouette edge. For rounded corners, use the intersection of the
   extrapolated straight sides. **Open full-size** provides native pixels and
   scrollbars; right-click undoes a point.
5. Confirm that you identified the physical top and front, then **Estimate pose**.
   Inspect the body wireframe in both images. Green denotes the best measured
   fit; amber denotes diagnostic alternatives. XYZ/distance are in meters relative
   to the head. The displayed Z/Y/X Euler angles are a convenience; the saved
   rotation matrix is the authoritative orientation.
6. Return to/hold the captured pose and choose **Track outline**. Move slowly at
   first. Each update fits the visible front boundary in both views. Loss or
   competing outlines ends the trial and clears the live pose; **Capture pair**
   starts a new association. A one-second GUI watchdog also clears stale output.

If the frozen pose is poor, correct the corner labels, dimensions and camera
mapping before evaluating live tracking. Low reprojection error does not prove
that the selected edges belong to the phone or that the factory calibration is
correct. A blank screen with a contrasting case/background may make this first
outline experiment easier than a busy screen.

## What the baseline does

- Defines body **B** at the center of the measured body/case, with X right, Y
  toward the physical top, and Z through the front. The output is **T_HB** in
  head right/up/back axes. Body dimensions do not define the active display.
- Uses ordinary OpenCV IPPE in normalized camera coordinates for both views,
  keeps distinct refined pose alternatives, and optimizes one common pose against
  all eight calibrated corner observations. A triangulated rigid-fit seed handles
  exact frontal cases. The front-plane offset is removed before publishing the
  body center, so thickness does not silently shift the reported origin.
- Rectifies native KB4 frames into perspective views at the original image size.
  Searches near the previous projected front face using OpenCV Canny, contours,
  polygon approximation and robust line fits to the straight sides. This avoids
  treating a detector bounding box or rounded arc extrema as physical corners.
- Requires support along all four sides in both views, a consistent stereo fit,
  bounded image/pose motion, and increasing frame timestamps. It has no raw-image
  right-angle/aspect-ratio filter; calibrated stereo geometry validates the fit.
- Retains competing poses/outlines as ambiguity. Blank/missing evidence, excessive
  skew, calibration mismatches, or a gap greater than 250 ms after the first live
  update cannot silently reuse a previous measured pose. Full loss is latched;
  there is no automatic switch to another rectangle after loss.

This tracker requires a mostly frontal, complete **front-face** outline. It is
not yet a cuboid-silhouette tracker: the cuboid wireframe visualizes thickness,
but tracking observations are the front plane. Fingers, weak contrast, reflections,
screen borders, oblique side/back silhouettes, fast motion and multiple nearby
rectangles can cause rejection or incorrect association. Proximity is not visual
identity. Manual top/front labelling resolves the shape symmetry only for this
trial. Do not interpret an attractive overlay as validated tracking accuracy.

## Captures, telemetry and replay

Each **Capture pair** explicitly saves two original grayscale PGM images and
the calibration/dimensions needed to inspect that capture. **Record live trial
images + raw phone telemetry** must be selected **before capture** to retain
subsequent live images and raw sensor/clock messages. It is off by default.

Use **Open results** for the local session directory (normally
`~/.local/state/framephone/sessions/body-*`). Recordings are local diagnostic
data, outside the source export. They may contain personal surroundings visible
to the cameras. Nothing is uploaded.

| Artifact | Contents |
| --- | --- |
| `session.json` | Versioned body dimensions, phone session identity, camera mapping, calibration hash, capture-clock assumption and recording choice. |
| `factory/persist/` | Exact factory calibration files used by the trial. |
| `initial/` and `capture.json` | Frozen synchronized PGM pair, replay manifest, native dimensions, capture timestamps and identities. |
| `corners.json` | Eight ordered native-pixel observations tied to the exact frozen frame metadata. |
| `run-*/poses.jsonl` | Every processed pair's status, reason, T_HB candidates, RMS/maximum residuals, edge coverage, timing and wireframe projections. |
| `run-*/paired-images/` | Optional raw live stereo images and replay manifest. |
| `initial-telemetry.jsonl`, `run-*-telemetry.jsonl` | Optional profile, validated raw sensor batches, clock replies and host receipt timestamps. No pairing credentials or private keys. |
| `run-*/preview-*` | Three rotating preview slots; token checks prevent drawing a pose over a different image pair. These remain bounded even when recording is off. |

Live image recording stops at 512 MiB per run; pose logs stop at 128 MiB. Sensor
recording is capped at 32 MiB with a bounded asynchronous queue. Queue loss and
write errors are reported; the receiver does not wait on disk writes. Sensor
recording failures do not invalidate independently measured optical poses.
Trials are not deleted automatically; remove unneeded session directories using
the file manager. A missing sensor-log end record indicates an incomplete log.

To replay, **Open trial** and select the `body-*` directory, **Estimate pose**,
then **Replay images** and select a recorded `run-*/paired-images` directory from
that trial. Replay uses the saved calibration and dimensions and does not require
the phone, headset cameras or a network connection. It writes a new result run.
Replay uses capture timestamps for gap checks; playback runs at processing speed.

The command-line equivalent, for automation with an unpacked native build, is:

```bash
framephone-markerless --session /path/to/body-trial --solve
framephone-markerless --session /path/to/body-trial --replay /path/to/body-trial/run-old/paired-images --output /path/to/new-results
```

The single executable also forwards `-- --markerless` to this tool.
`--capture`, `--solve`, `--track` and `--replay DIRECTORY` are mutually exclusive;
track/replay require a new output directory. The desktop creates the inputs.

## Interfaces for the next stages

`PhoneBodyModel`, `BodyObservation`, `BodyPoseResult`, `MarkerlessPoseEstimator`
and `MarkerlessTracker` are native APIs independent of Tk. Native result JSON uses schema `framephone-body-pose-v1`;
session and corner schemas are `framephone-markerless-session-v1` and
`framephone-body-corners-v1`. Integer capture and sensor timestamps retain their
source clock domains. Candidate transforms are diagnostic unless status is
`measured`. The implemented states are `measured`, `ambiguous` and `lost`;
there is no inertial `predicted` state yet.

Phone IMU is **recorded, not fused**. Phone/camera/XR time alignment, sensor-to-body
axes, independent headset motion and clock drift remain unverified. Authenticated
dimensions are fixed per trial; disconnecting/changing the phone ends live
tracking. Reconnect and recapture to start another trial.

Next, collect real Frame trials and measure pose error with an independent
reference. Add detector proposals without changing the geometry API; compare
RAPID's cuboid-silhouette tracking against this complete-outline baseline for
partial occlusion/tilt. Only then add gyro prediction after timing/axes validation.
Pretrained YOLOX phone boxes and 2D contour proposals are available separately.
Their automatic connection to metric pose, RAPID, robust visual identity, screen
mapping, world-space fusion and VR rendering remain future work.

If **Track outline** stays disabled, confirm all eight points and check the
physical top/front checkbox, then click **Estimate pose**. Tracking requires a
`measured` result. Rejected/ambiguous fits now show their exact reason in the
status text; point selection alone does not start the tracker.

## Validation

Native tests independently project known metric corners with OpenCV and render
distorted grayscale stereo rasters. They check frontal/tilted body-center pose,
actual contour tracking, wrong observations/calibration/skew, loss latching and
timing gaps. CLI tests solve/replay real files and verify loss/provenance checks.
A Tk integration test exercises capture, corner selection, solve, live raster
tracking and pose clearing using an independent camera-ring writer. Sensor tests
cover opt-in recording and preservation of integer timestamps.

These software checks do not measure performance or tracking accuracy on Frame.
