# Testing and hardware validation

Software tests and hardware measurements answer different questions. Tests verify
frame handling, marker geometry and numerical behavior under controlled inputs.
They do not establish camera access, real detection coverage or headset accuracy.

## Automated checks

Run commands from [DEVELOPMENT.md](../../docs/DEVELOPMENT.md). GitHub Actions
is configured for portable/native Linux, ARM64 and Android host checks; hosted
results are available only after pushing the repository.

| Suite | Coverage |
| --- | --- |
| Android `GeometryTest` | Physical units, display/phone rotation, layout clipping/overlap, raster orientation and exported marker geometry. |
| Android `Tag36h11Test` | Official family raster fixtures and rotation. |
| Native camera source tests | Metadata/stride, PGM parsing, clock separation and deterministic synthetic tags. |
| Native ring tests | Stable/torn slots, stale writer, malformed ABI, replacement, skips and timestamp precision. |
| Diagnostic state/CLI tests | Detection histories, loss/reacquisition, CSV, replay and independent ring input. |
| AprilTag integration tests | Real decoding of the synthetic tag rasters. |
| Calibrated pose tests | Pinhole/KB4, rotated exports/rasters, independent projections, perspective images, noise, outliers and ambiguity. |
| Stereo geometry/CLI tests | Factory transform composition/units, pairing skew/queue bounds, independent projections, two decoded views, explicit ring mapping, paired recording/replay and loss. |
| Linux package script checks | Clean source handoff, default/native architecture, executable/checksum export, failed-update preservation and build-container cleanup using a simulated engine. |
| Desktop frontend checks | All normal mono candidates, explicit selected-pair handoff, reported dimensions/identities, fresh result directories, live marker ID counts, loss/stale handling, host-tool library isolation and bounded previews. |
| Front-camera GUI integration | Actual Tk window and native detection on independent 1280×1024 ring streams: all four candidates, obsolete mapping reset, calibration dimension mismatch rejection, selected-pair counts without a layout, loss/stale/reacquisition and native-pixel views. |
| Broker checks | Static linking and strict caller UID/primary-group resolution without opening cameras or requesting privileges. |
| Linux package CI | Docker native AMD64/ARM64 and emulated ARM64, plus rootless Podman chroot on native ARM64; image build/CTest and extracted executable detector/CSV and virtual-display GUI startup on native runners. |

`make -C frame test all` covers only the portable subset. Full CMake/CTest checks
require AprilTag, OpenCV and JSON. SDL's preview smoke test uses its dummy driver,
which tests rendering code without establishing desktop/VR display behavior.
Android device instrumentation is separate from host unit/lint checks.

Pose acceptance/loss/reacquisition checks use a tilted raster so the two planar
pose hypotheses are distinguishable. Frontal raster checks allow `accepted` or
`ambiguous`: AprilTag versions can refine edges enough to change that decision.
Those checks still require all four markers, low reprojection error and the
original pose accuracy bounds. Separate tests require ambiguous poses to be
rejected; the estimator's production acceptance thresholds are unchanged.

Run the package script checks with `python3 frame/tests/test_linux_package.py`
and desktop checks with `python3 frame/tests/test_desktop.py`. The broker's static
build/identity checks use `python3 frame/tests/test_broker.py` (C compiler required).
These simulated-engine checks do not establish container or ARM64 compatibility;
the real image jobs and headset run cover those separately.

With Tk and Xvfb installed, run the front-camera window integration against a
full native build (for example `frame/build/desktop`):

```bash
xvfb-run -a python3 frame/tests/test_front_camera_gui.py frame/build/desktop
```

This exercises real decoding and widgets with generated camera images. It does
not establish phone-screen visibility in the headset's mono sensors.

## Android device checks

- Measure both active-display dimensions and confirm the 50 mm calibration ruler
  on both axes. Check portrait and landscape with the same saved calibration.
- Verify complete marker boundaries/quiet zones for each layout and selected size;
  rejected geometry must explain clipping or overlap.
- Test overlay permission grant/denial, notification permission, Stop, lock,
  display-off and process death. No overlay should silently restart at boot.
- Check touch behavior inside/outside marker windows and apps that hide overlays.
- Check rotation/update intervals, measured exports and the temporary white
  interval. Logcat `FiducialTiming` measures CPU callbacks/drawing, not physical
  screen presentation or GPU completion.

## Steam Frame feasibility

Follow [HEADSET_TEST.md](HEADSET_TEST.md) for setup and a bounded first capture.
The owner has run the app and observed up to six fiducials updating live on a
headset. The OG0VE10 pair previously forced by the app showed side views, with
reported 640×640 images; the owner recalls video0/video3 as the front views.
Front-camera identity, detection range and pose accuracy remain unverified.
Before tuning the solver:

1. Verify the two actual front mono views, factory-to-ring mapping, resolution/crop,
   bright-frame selection and shared capture clock.
2. Inspect raw images for full marker boundaries and quiet zones. Visibility in
   headset passthrough alone is not evidence of mono-camera detectability.
   Check per-camera marker counts with and without previews, then with stereo
   tracking enabled. Remove/cover all tags and stop camera input: counts/poses
   must clear, and detection must reacquire after tags/input return.
3. Record phone layout export/revision, measured display dimensions, marker size,
   phone brightness, lighting, exposure if available, distance and tilt.
4. Compare detection rate and projected tag size across distances and tilts.
   Include occlusion/blank intervals and reacquisition; keep both images of a pair.
5. Compare pose against independent physical measurements, including rotation
   and simultaneous phone/headset motion. Reprojection RMS alone cannot reveal a
   consistently wrong phone scale or calibration.
6. Measure sustained processing time, skipped/unpaired frames and tracking
   continuity with capture enabled. Repeat after headset sleep/wake and broker
   restart; readers must fail clearly on stale/replaced input.

For each experiment, retain the exact build/dependency versions, factory-file
checksums, frozen phone export, commands, logs and paired captures. Use new
output filenames. Default software thresholds are diagnostic starting points,
not confidence bounds measured on this hardware.

## Future world tracking acceptance

Before rendering a tracked phone in world space, validate capture-to-XR clock
mapping, camera/head transform direction and historical headset interpolation.
Test recenter/reference-space changes, fast head rotation, lost tracking and
reacquisition. Filtering/prediction needs raw-versus-filtered measurements and
explicit stale/lost output; it must not hide bad calibration or timestamp skew.
