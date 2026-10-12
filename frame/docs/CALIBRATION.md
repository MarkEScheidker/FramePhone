# Calibration workflow

## Android active display

1. Install and open **FramePhone** from `phone/app` on Android 12+.
2. Use a physical ruler to measure the active display's short width and long
   height in millimeters, in portrait. Exclude bezel/glass margins; include areas
   normally behind system bars.
3. Enter and save both dimensions. There is no automatic DPI-derived calibrated
   fallback; Android's reported DPI is diagnostic only. With markers disabled,
   open **High-contrast calibration ruler** and measure the full 50 mm span on
   each axis. Tick endpoints are integer logical pixels, rounded separately for
   X/Y; no density scaling or antialiasing is used. Correct your measurements if
   either axis differs. Small windows report insufficient space instead of scaling
   the ruler. The ruler checks entered calibration; it is not an independent
   physical measurement.
4. Grant “Display over other apps” in Android settings, return, then enable.
5. Confirm complete quiet zones, no rounded-edge/cutout clipping, and correct
   physical marker sizes with a ruler. Check portrait and both landscape directions.
6. Export JSON once diagnostics show measured marker windows. Save a separate
   snapshot for each configuration used in experiments.

The calibration key includes device manufacturer/model, display ID/name,
orientation-normalized physical mode and logical dimensions, and natural
orientation. Rotations share physical calibration. Resolution, display, and
fold-state changes that alter dimensions require another measurement. Preferences
are local and excluded from backup/transfer. A foldable must be flat for the
rigid planar model; curvature and nonplanar displays are unsupported.

Reported physical resolution is Android's current `Display.Mode`, which is not
a guarantee of the panel's native resolution. Logical dimensions come from the
overlay window context's maximum metrics. Both are exported. xdpi/ydpi and
densityDpi are diagnostics only. Settings remain device/vendor-dependent and
require the ruler check. Manual measurement uncertainty is recorded as unknown;
the label `manual_measured` does not assert metrology-grade calibration.

The marker size setting means the detector boundary, excluding the white ring:
8, 12, 16, and 20 mm targets have approximately 10, 15, 20, and 25 mm total
footprints. Margin is additional clearance outside the white ring and measured
in physical units. Cell dimensions are rounded to whole pixels separately on
each axis; the actual exported dimensions are authoritative.

## Camera calibration

The stereo tracker imports Frametop-compatible factory KB4 intrinsics and
camera-to-head transforms from the headset. See [STEREO.md](STEREO.md) and
[HEADSET_TEST.md](HEADSET_TEST.md). The single-camera estimator accepts explicit
[camera-calibration v1 JSON](../protocol/camera-calibration.md), with pinhole
or KB4 models. Software fixtures are explicitly synthetic and must not be used
for actual hardware.

Prefer hardware-specific calibration only after checking camera identity, image
resolution/crop, units, distortion model and rig coordinates. Frametop's source
offers leads; see STEAM_FRAME_INTEGRATION.md. Approximate intrinsics must remain
explicitly `approximate_diagnostic` and never be promoted to calibrated tracking.

If reliable factory calibration is unavailable, collect a known-size physical
checkerboard or ChArUco target across the field of view, distances and tilts. Use
OpenCV's appropriate pinhole or fisheye calibration and keep separate cameras.
Record resolution, intrinsic matrix, distortion coefficients/model, sample count,
per-view residuals, reprojection RMS, hold-out validation error and version.
Reject nonfinite parameters, inconsistent dimensions, insufficient coverage and
clearly poor fits; establish numerical thresholds from recorded validation data.

Camera intrinsics do not determine `T_HC`. Camera-to-headset extrinsics require
validated factory transforms or a separate rig/hand-eye workflow with synchronized
headset poses and a fixed known target. Image undistortion must match the chosen
model. A four-coefficient fisheye model is not ordinary four-coefficient pinhole
distortion. Keep factory provenance, measured calibration, synthetic fixtures and
approximate diagnostics distinct. The current explicit JSON loader accepts
`calibrated` or `synthetic`; it rejects approximate/unavailable input. Factory
import uses `factory_imported` and still requires hardware validation.
