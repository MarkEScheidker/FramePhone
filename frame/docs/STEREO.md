# Stereo tracker implementation

`framephone-stereo` uses the existing real AprilTag detector, phone-layout
loader, Gray8/replay sources, Frametop ring adapter and CSV exporter. It builds
when both AprilTag and OpenCV/JSON are available. The headset build requires
these dependencies; it cannot fall back to a detector-free executable.
See [HEADSET_TEST.md](HEADSET_TEST.md) for the bundled desktop app and camera setup.

## Reused Frametop components

The pinned calibration/ray implementation is adapted under MIT, with provenance
in [third_party/frametop/README.md](../third_party/frametop/README.md):

- `/persist/xrservice.json`: `sourceCamera`, dimensions, `cameraModel=kb`
  intrinsics and `plus_x/plus_z/position` extrinsics.
- `/persist/device_config.json`: `cv.cad_from_cal` and `head`.
- `T_HC = inverse(T_CAD,H) * T_CAD,C0 * T_C0,C`;
  camera extrinsic positions scale by 0.001; device CAD/head positions are meters.
- KB4 angle-polynomial projection/inversion and head-space unit rays.
- Least-squares ray intersection: sum `(I-dd^T)` and `(I-dd^T)*origin`,
  solved with OpenCV SVD rather than the original Cramer's rule/zero fallback.
- Fresh-frame pairing with a maximum 3 ms capture-time spread. Each camera has
  a bounded four-frame queue; old/skewed frames drop and no pair reuses a frame.

Factory and ring identities are separate: the broker uses sensor/video slugs.
The CLI takes explicit factory-to-ring mappings; it never infers them from
array order, left/right words or video numbers. `--list-ring FILE` reads the
bounded ABI header and lists raw names, sensor, node, resolution and flags.
Factory import rejects missing/duplicate/nonfinite data, bad axes, multiple KB
models and a nonmonotonic forward projection model. Stereo rigs must have
different cameras and a baseline between 1 mm and 0.5 m. Forward-hemisphere
pixels only are supported; wider fisheye rays are rejected.

## Rigid phone fit

Tag IDs and AprilTag's canonical corner order establish correspondence between
both images and measured phone geometry. Shared tags require zero hamming and
decision margin >=10 in both views. Margins are not probability weights.

Rays must intersect in front of both cameras, with >=0.01 rad angular separation,
SVD smallest/largest ratio >=1e-5, and <=1 cm RMS line distance. These are seed
gates, not reported metric accuracy. If any corner fails, the entire marker is
excluded from fitting, but still counts when testing majority consensus.

For each valid tag pair, Kabsch/SVD fits one proper rigid transform to the
triangulated corners. Existing monocular IPPE alternatives supply additional
seeds. OpenCV's LM solver refines six rotation/translation parameters using
original distorted image pixels from **both cameras together**. It is not an
average of independently solved camera poses. Rotation uses Rodrigues vectors;
numeric central differences supply the Jacobian. All-point consensus refits
must converge within 60 iterations.

A whole marker is an inlier only when every projected corner is forward and
within three pixels in both images. At least two shared markers are required;
with more than two, a strict majority must agree. Front-facing phone normals
are checked in both views. Equivalent results within 1 degree/1 mm merge;
distinct equal-consensus alternatives with RMS separation <0.5 px produce
`ambiguous`. Multiple seeded minima help diagnose ambiguity; this is not an
exhaustive mathematical guarantee or an uncertainty estimate.

Only `accepted` is usable. Missing tags, degenerate rays, poor fits and ambiguity
never substitute an earlier usable pose. Motion compensation, pose filtering,
capture-to-XR clock mapping, world poses and VR visualization remain separate.

## Outputs and verification

JSONL `framephone.stereo-pose` v1 records **T_HP**, meters, head axes
`right_up_back`, phone-layout revision, both original integer capture timestamps,
shared clock label, skew, ring IDs, factory IDs, calibration revision/status,
ring transport metadata, candidates, inlier IDs and joint pixel RMS. Calibration
status `factory_imported` means parsed factory data, not validation on hardware.
The caller must verify the common capture clock; equality of labels is not proof.

Optional raw recording uses the existing PGM/manifest v1 format, one image per
camera per processed pair. It preserves identifiers and capture clocks for
replay. Ring transport fields stay in JSONL/CSV rather than the legacy manifest.
Neither raw images nor files are created unless explicitly requested.

The stereo geometry CTest uses independent OpenCV fisheye projection with known
head-space poses, noisy corners, bad marker corners, swapped views, missing tags,
parallel rays, invalid calibration, nonidentity CAD/head composition, bounded
queues and the exact 3 ms pairing boundary. It renders actual AprilTag textures
into two distorted views and decodes both with the real detector. The CLI test
independently publishes a binary two-camera ring with sensor/video names, checks
blank-frame loss and >2^53 timestamp precision, then records/replays both views.
These verify software behavior and do not establish headset tracking accuracy.
