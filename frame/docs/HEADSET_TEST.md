# Build and test on Steam Frame

This is a native Linux ARM64 diagnostic, built **on the headset**. It uses
Frametop's existing `ft-camd` broker, factory camera calibration, and two
explicitly selected monochrome views. It reports decoded tags and a rigid
stereo phone pose in a terminal, with optional CSV, JSONL and raw PGM recording.
It is not an APK or a SteamVR overlay; no VR rendering is needed for this test.

The source and tests build on the development PC. ARM64 compilation, camera
identity/timing and tracking accuracy still need your headset run. This bundle
contains source, not a prebuilt ARM64 binary or bundled runtime libraries.
It includes both apps and shared documentation; only the native component is
built for this headset test.

## 1. Transfer the source

On the PC, from the project root:

```bash
bash frame/package-headset.sh
```

Transfer `frame/build/dist/framephone-headset-src.tar.gz` and its `.sha256` file
to the headset, using your preferred method. Also transfer the phone app's
current **measured layout export** as `phone-layout.json`. Keep the phone's
orientation, layout, marker size and overlay placement fixed after export.
The included synthetic layout/calibration files are test fixtures only.

On the headset host, assuming the archive is in `~/Downloads`:

```bash
cd "$HOME/Downloads"
sha256sum -c framephone-headset-src.tar.gz.sha256
mkdir -p "$HOME/FramePhone-test"
tar -xzf framephone-headset-src.tar.gz -C "$HOME/FramePhone-test"
```

Put the real `phone-layout.json` in `~/FramePhone-test/`.

## 2. Build in an ARM64 Linux development container

Use Frametop's Fedora Distrobox named `dev`, if already configured. The commands
below assume it exists; container setup is described in the
[Frametop repository](https://github.com/Frametop/frametop/tree/24a86dc02669caaef8386ea5bfeb08fcb2819944/setup).
Run `uname -m` inside it: the result must be `aarch64`.

From the headset host, install development dependencies **inside the container**:

```bash
distrobox enter dev -- sudo dnf install gcc-c++ cmake make file python3 apriltag-devel opencv-devel json-devel
distrobox enter dev -- bash "$HOME/FramePhone-test/frame/build-headset.sh"
```

Fedora's package is [`json-devel`](https://packages.fedoraproject.org/pkgs/json/json-devel/),
the nlohmann headers; [`apriltag-devel`](https://packages.fedoraproject.org/pkgs/apriltag/apriltag-devel/)
provides AprilTag 3. An Ubuntu ARM64 container can instead install
`build-essential cmake file python3 libapriltag-dev libopencv-dev nlohmann-json3-dev`
with apt, then run the same build script there.

The build script refuses x86_64, requires the real detector and pose dependencies,
builds Release, checks the binary's architecture, runs CTest, and installs under:

```text
~/FramePhone-test/frame/build/headset-aarch64/install/bin/
```

No OpenVR SDK, ncnn, neural models, SDL or compositor is required. Run these
binaries in the **same container**: its OpenCV/AprilTag/glibc versions may differ
from SteamOS. Copying just the executable to the host is not a deployment method.
Build scripts perform no sudo, downloads, SSH, capability changes or service setup.

## 3. Supply frames using Frametop's broker

If you already have a compatible `ft-camd` running, keep that instance and skip
building/starting another. The supported ring ABI is FHRING01 v1 at commit
`24a86dc02669caaef8386ea5bfeb08fcb2819944`.

For a standalone broker, these are manual operator steps using upstream code.
On the headset host, clone into a fresh directory:

```bash
git clone https://github.com/Frametop/frametop.git "$HOME/frametop-framephone"
git -C "$HOME/frametop-framephone" checkout 24a86dc02669caaef8386ea5bfeb08fcb2819944
distrobox enter dev -- sudo dnf install gcc make glibc-static
distrobox enter dev -- make -C "$HOME/frametop-framephone/hands" build/ft-camd
```

This explicit Make target builds **only the static camera broker**, avoiding
the upstream `all` target's hand tracker and ncnn download. In an Ubuntu
container, install `build-essential` for the corresponding static C build.

With SteamVR running and the headset awake, start the broker on the **host**,
in a separate terminal. Its upstream implementation uses privileges to borrow
XRService buffers and attach the dequeue tracepoint, then drops them. For this
manual test, upstream supports starting it through sudo:

```bash
sudo "$HOME/frametop-framephone/hands/build/ft-camd" --status 1
```

Leave that terminal open; Ctrl+C stops it after testing. Do not use
`hands/run.sh install` or start `ft-hands` for this test. Keep the mono defaults;
do not enable `--with-color` or `--with-dark`. A broker restart/replaced ring
requires restarting FramePhone. The application itself remains unprivileged.
For long-lived capabilities/services, follow
[upstream's broker instructions](https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/README.md#ft-camd).

## 4. Select and verify the camera pair

Enter the container and stay there for the remaining commands:

```bash
distrobox enter dev
cd "$HOME/FramePhone-test"
tracker="$PWD/frame/build/headset-aarch64/install/bin/framephone-stereo"
factory_root=/run/host
ring="/run/user/$(id -u)/frametop-hands/cam-ring"
```

If `/persist` is directly readable inside your environment, use
`factory_root=/` instead. If the shared ring is only visible through the host
mount, use `ring="/run/host/run/user/$(id -u)/frametop-hands/cam-ring"`.

```bash
test -r "$factory_root/persist/xrservice.json"
test -r "$factory_root/persist/device_config.json"
test -r "$ring"
sha256sum "$factory_root/persist/xrservice.json" "$factory_root/persist/device_config.json" > factory-checksums.txt
"$tracker" --list-cameras --factory-root "$factory_root" --calibration-id frame-factory-test-1
"$tracker" --list-ring "$ring"
```

The importer reuses Frametop's KB4 projection and CAD/head transform composition;
camera extrinsic positions are converted from millimeters to meters. It reports
`factory_imported`, which records provenance rather than measured accuracy.
Retain `factory-checksums.txt` with results and change the revision ID if the
factory files change.

Use the two actual forward-view mono cameras. `slam_left` and `slam_right` are
upstream's side/front **factory** pair names. The ring uses sensor/video slugs,
not those factory names. Match its listed sensors/video nodes to XRService's
`Found camera` and `TrackingCameraInit` lines from the current camera start in
`~/.local/share/Steam/logs/xrservice.txt`, and check the broker's binding log.
Prefer `bound by VIDIOC_QUERYBUF` over fallback queue order. Set the two actual
ring names in this container shell (replace these placeholders):

```bash
left_ring=EXACT_LEFT_RING_NAME
right_ring=EXACT_RIGHT_RING_NAME
```

`--left-ring` maps to the factory `--left` calibration; the corresponding right
options map the other view. Both identities are retained in JSONL. The tracker
deliberately does not guess or automatically exchange camera names.
Swapped observations should reject as behind-camera/inconsistent geometry.

The two cameras must share a capture clock. Upstream's mono tracker assumes
`CLOCK_MONOTONIC_RAW`; the ring does not encode that fact. Confirm it for your
broker/firmware before supplying that label below. The app compares original
capture timestamps and never substitutes dequeue/publish times. A <=3 ms match
limits skew; it does not synchronize exposures or compensate headset/phone
motion during the difference.

## 5. Run a short live test

From that container shell, after verifying the names/clock above:

```bash
"$tracker" \
  --ring "$ring" --left slam_left --right slam_right \
  --left-ring "$left_ring" --right-ring "$right_ring" \
  --factory-root "$factory_root" --calibration-id frame-factory-test-1 \
  --capture-clock CLOCK_MONOTONIC_RAW --phone-layout "$PWD/phone-layout.json" \
  --frames 60 --pose-jsonl "$PWD/first-stereo.jsonl" \
  --csv "$PWD/first-tags.csv" --record-dir "$PWD/first-frames"
```

Use new output names on each run; existing exports are refused. Recording is
optional and contains both full grayscale images for each processed pair,
including missed detections. Sixty 640x480 pairs use about 35 MiB; larger images
use proportionally more space. JSONL retains ring transport metadata; the PGM
recording manifest retains source/camera/clock/calibration and capture times.

Hold the phone steadily in the overlap, initially near 30–50 cm with the tags
large and unobstructed. Try modest translations and tilts, then cover the tags
briefly. Measure distance from the headset/head reference approximately, and
record phone brightness, tag size, lighting and whether Room View was enabled.

Each pair prints `tags=L/R`, shared IDs, capture skew, processing time and status.
`accepted` includes head-relative XYZ, distance from head origin, and pixel RMS;
the JSONL stores the full rotation and translation. Acceptance requires at least
two common usable tags, well-conditioned forward rays, whole-tag consensus and
joint reprojection <=3 pixels at every inlier corner in both views. A strict
majority is required with >2 shared tags. `ambiguous` candidates are diagnostic,
and only `accepted` poses are usable. These thresholds are initial defaults.

The transform is **T_HP**, phone meters into OpenVR-style head axes: X right,
Y up, Z backward. A phone ahead normally has negative Z. There is no world pose,
OpenXR clock mapping, historical headset motion compensation or smoothing here.
Lost/rejected pairs emit no usable pose; an old pose is never held as current.

## 6. Interpret failures and keep the evidence

- `tags=0/0`: examine the recorded PGM images. Visible color passthrough does not
  establish visibility in the mono tracking cameras. Check phone brightness,
  glare, projected tag pixels, exposure, focus and whether the broker supplies
  the intended bright frames.
- Tags in one view only: check camera overlap, identity, occlusion and distance.
  Stereo requires both views; this app does not silently substitute monocular pose.
- Tags in both, but `rejected`: verify the exact exported layout, measured screen
  dimensions, raster orientation, camera names, calibration model and timing.
  CSV stores all decoded corners/margins for analysis.
- No synchronized pair/timeout: compare capture timestamps; verify the shared
  clock and fresh bright-frame cadence. Do not increase tolerance beyond 3 ms
  just to force pairing. `dropped_unpaired` counts queue/skew drops; ring transport
  separately records frames skipped by newest-frame reading.
- Stale/replaced ring: inspect the broker log, keep the headset awake, and restart
  the reader after a broker/SteamVR restart. No camera service restart is automated.

Replay the paired capture in the same container without a running broker:

```bash
"$tracker" --replay "$PWD/first-frames" --left slam_left --right slam_right \
  --left-ring "$left_ring" --right-ring "$right_ring" \
  --factory-root "$factory_root" --calibration-id frame-factory-test-1 \
  --phone-layout "$PWD/phone-layout.json" --pose-jsonl "$PWD/replay-stereo.jsonl"
```

Useful results for the next iteration: build/CTest output, terminal tracker and
broker logs, `factory-checksums.txt`, the matching phone export, JSONL/CSV, and
a few corresponding left/right PGM pairs. Factory files can stay on your headset
unless debugging the importer requires their relevant structure.
