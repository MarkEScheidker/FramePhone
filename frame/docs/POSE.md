# Camera-relative phone pose

The optional OpenCV/nlohmann JSON module loads the Android phone-layout v1
export and [camera calibration v1](../protocol/camera-calibration.md). It validates
the measured display scale, rotation transform, meter corners and marker ID set.
The exported actual boundary coordinates are authoritative, including rectangular
pixel quantization; nominal requested marker size is not used for fitting.

AprilTag canonical p[0..3] correspond to BL/BR/TR/TL for this project's upright
tag raster. A clockwise raster quarter turn advances each display-corner index
by one. The loader applies that permutation using
`image_rotation_clockwise_deg`. Real decoded images at all four camera rolls
and exports at all four display rotations test this association.

At least two distinct tags from the loaded layout, zero corrected bits and
decision margin >=10 are required. Unknown layout IDs are ignored; duplicate
known IDs reject the frame. IPPE fits pairs to seed marker consensus, rejecting
whole tags if any corner exceeds three pixels of reprojection error. With more
than two observed tags a strict majority must agree. Each distinct best consensus
is refit using all its corners, retaining both IPPE plane hypotheses. No temporal
prior, nonlinear refinement, uncertainty estimate or prediction is applied yet.

Pinhole or fisheye-KB4 observations are undistorted to normalized camera rays
for fitting. Candidates must put fitted corners in front of the camera and the
phone's front toward the camera. Scoring projects through the original calibrated
model and measures RMS in original pixels. Candidates within one degree and
one millimeter are treated as equivalent. Distinct alternatives with equal
inlier count and RMS difference <0.5 pixels yield `ambiguous`; these thresholds
are diagnostic defaults, not measured hardware confidence bounds.

Results are `accepted`, `ambiguous`, `insufficient_tags`, or `rejected`. Only
`accepted` supplies a usable pose; blank or rejected frames do not retain the
previous pose. An accepted result means the configured geometric checks passed,
not a measured accuracy guarantee. Bad physical size or camera calibration can
produce a consistent but wrong scale. Freeze the phone rotation/configuration
and load its matching export for each experiment.

Try the controlled software fixture locally from the workspace root:

```bash
bash frame/run-diagnostic.sh --headless --frames 120 --blank-every 30 \
  --phone-layout frame/tests/fixtures/synthetic-phone-layout.json \
  --camera-calibration frame/tests/fixtures/synthetic-camera.json
```

Add `--pose-jsonl /tmp/phone-pose.jsonl` for explicit local export (existing
files are refused). Remove `--headless` for preview. These fixtures describe the
synthetic raster only; their intrinsics and display dimensions must never be used
as real phone/headset calibration. `--motion` exercises translation in the image
plane, not physical perspective motion. The test suite separately decodes a
perspective-warped raster with a known tilted pose.

Each JSONL record has schema `framephone.camera-pose`, version 1, `transform:T_CP`,
units meters, camera/calibration identity and status, phone layout revision,
original integer capture timestamp and clock domain, result status, and up to
two candidates. Each candidate has a row-major 3x3 rotation, translation in
meters, original-pixel RMS and inlier IDs. T_CP maps canonical phone coordinates
(X right, Y up, Z toward viewer) into optical camera C. Ambiguous candidates
are diagnostic only. Ring frames additionally retain host transport timestamps.

The desktop preview reports pose status; JSONL carries full metric transforms.
The OpenVR demo remains separate. No headset/world pose is generated. That needs
verified T_HC, a capture-to-XR clock map, and historical full 6DoF headset poses
for `T_WP(t) = T_WH(t) * T_HC * T_CP(t)`. Joint multi-camera fitting is implemented
in the separate [stereo tracker](STEREO.md), which returns T_HP. Filtering,
VR pose visualization and hardware accuracy measurements remain future work.

Dependencies: OpenCV 4 `core`/`calib3d` and nlohmann JSON headers. Tests also use
`imgproc`. CMake enables pose when these are found; `POSE_SDK_ROOT` selects a
nonstandard install prefix. `FRAMEPHONE_ENABLE_POSE=OFF` keeps the portable
diagnostic; requesting pose in that build fails explicitly. This workspace's
launcher uses ignored local x86_64 OpenCV 4.5.4/JSON 3.10.5 packages when present;
an ARM64 build needs matching target libraries. No dependencies are downloaded
by the launcher. See the [OpenCV PnP documentation](https://docs.opencv.org/4.x/d5/d1f/calib3d_solvePnP.html)
for the model and IPPE solver contracts.
