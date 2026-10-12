# Local fiducial diagnostic

`framephone-diagnostic` is a native C++20 Linux application. Its optional SDL2
window displays Gray8 images with real AprilTag 3 tag36h11 detections (IDs 0–5).
Synthetic and local recorded inputs share the same detector and diagnostic code.
Optional [Frametop ring input](LIVE_CAMERA.md) and [camera-relative calibrated
pose](POSE.md) now use the same diagnostic. Both are locally tested; hardware
capture and XR/world alignment remain unverified.

## Run in this workspace

From the FramePhone root in a Linux/WSL terminal:

```bash
bash frame/run-diagnostic.sh --synthetic --motion --blank-every 30
```

The launcher builds the app under `frame/build/diagnostic` and runs it. It uses
the workspace's local CMake/AprilTag/SDL2/OpenCV/JSON dependencies when present on x86_64;
otherwise it uses installed development tools/libraries. It never downloads,
installs packages, connects to a headset, or grants camera privileges.
The desktop preview needs a working display (such as WSLg).

Controls: **Space** pauses/resumes, **Right** advances one frame and pauses,
**R** restarts the input, **Esc/Q** quits. End of input keeps the final frame
visible; use `--quit-at-end` for automated runs. A synthetic run defaults to 300
frames; `--frames` changes its length, `--marker-px` changes the boundary in whole
eight-cell multiples, and `--blank-every N` makes every Nth frame blank.
`--motion` translates the synthetic image; it does not simulate perspective,
lens distortion or a known physical trajectory.

```bash
# No window; processes as fast as possible with real detection.
bash frame/run-diagnostic.sh --headless --motion --frames 120 --blank-every 30

# Process a local recording (manifest.tsv and PGM P5 images).
bash frame/run-diagnostic.sh --replay /path/to/recording

# Explicit CSV export; existing files are refused.
bash frame/run-diagnostic.sh --headless --replay /path/to/recording --csv /tmp/phone-tags.csv

# Report compiled features without opening a window.
bash frame/run-diagnostic.sh --capabilities
```

The lower-level `framephone-frame --synthetic` command can generate the recording
format; see [RECORDINGS.md](RECORDINGS.md). `--fps` sets a target preview playback
rate (default 30). Replay does not synchronize independent camera clocks or
reconstruct original wall-clock playback intervals; capture timestamps are
preserved verbatim. Headless processing is unpaced.

## What the display measures

- Green polygons and ID labels come from decoded detections; the yellow square
  marks canonical detector corner 0, which rotates with the tag.
- **Coverage** is the fraction of processed frames with at least one accepted tag
  in the displayed camera/clock history. It is not all-marker visibility, detector
  accuracy, or a ground-truth detection rate.
- **Missing** counts consecutive processed frames without tags. **Reacquired**
  increments when any tag returns after a gap, following an initial acquisition.
  Camera IDs and clock domains have independent histories.
- **Detect ms** measures the real detector call. **Process ms** includes reading/
  generating the frame, detection, optional pose and history update, excluding
  drawing, CSV/JSONL output, playback waits, and camera latency. **Work FPS** is 1000 / Process ms;
  it is processing capacity for this input, not measured live-camera throughput.
- **Min margin** is the lowest AprilTag decision margin in the current frame,
  not a probability/confidence percentage.
- Original capture nanoseconds are shown without comparing them to the local
  clock. Camera-to-host clock alignment is required before calculating frame age.

Restart resets diagnostic histories and increments the CSV session number.
CSV contains one row per detection, or one row with empty detection fields for a
miss/preview frame. It retains camera, clock, calibration, optional exposure,
original integer timestamps, decoder hamming/margin, and ordered corner pixels.
Live ring input adds source frame number, host dequeue/publish timestamps,
V4L2 sequence and skipped published frames. See [LIVE_CAMERA.md](LIVE_CAMERA.md).
CSV export and `--snapshot FILE.bmp` (final preview image at EOF) are opt-in and
local. Existing output files are refused. Recording/replay files are never uploaded.

## Build on another Linux host

Install a C++20 compiler, CMake 3.20+, AprilTag 3, and SDL2 development headers and
libraries. The tested detector is AprilTag 3.4.5. `APRILTAG_ROOT` and `SDL2_ROOT`
can identify nonstandard installation prefixes.

```bash
cmake -S frame -B frame/build/cmake -DCMAKE_BUILD_TYPE=Release
cmake --build frame/build/cmake --parallel
ctest --test-dir frame/build/cmake --output-on-failure
frame/build/cmake/framephone-diagnostic --motion --blank-every 30
```

CMake enables each dependency only when found. Missing AprilTag produces an
explicit unavailable error unless `--no-detect` is selected. Missing SDL2 requires
`--headless`. Neither case substitutes simulated detections.
For an intentionally dependency-free build:

```bash
make -C frame test all
frame/build/portable/framephone-diagnostic --headless --no-detect --frames 3
```

Use CMake to enable real detection and preview; the portable Makefile builds only
the dependency-free paths. Tests cover histories/clock isolation, CSV escaping and
64-bit timestamp preservation, CLI validation, replay/corrupt input, optional real
decoding of moving/blank synthetic frames, and optional SDL dummy-driver rendering.

## Next hardware step

After SSH setup, verify a compatible broker/ring on the Frame and run the same
diagnostic with its exact camera/clock identity. Load the current phone layout
JSON and validated camera intrinsics/distortion to test metric T_CP. World
tracking additionally needs extrinsics, capture-to-XR clock alignment and
capture-time headset poses. Synthetic tests do not establish phone detectability
or accuracy on the headset.
