# Frametop camera ring input

For the new **two-camera** tracker, factory calibration import, explicit
factory-to-ring name mapping and ARM64 headset instructions, see
[HEADSET_TEST.md](HEADSET_TEST.md) and [STEREO.md](STEREO.md). The commands below
describe the existing single-camera diagnostic.

The desktop app now starts its own bundled broker through **Enable cameras**,
using `/run/user/UID/framephone-camera/cam-ring`. The direct CLI below remains
useful for development and can consume either that ring or an external compatible
broker. No Frametop installation is needed for the desktop app.

`framephone-diagnostic --frametop-ring FILE` consumes an **existing** Frametop
camera broker ring. It opens the file read-only; it does not install or start
`ft-camd`, open V4L2 nodes, attach to XRService, set capabilities, or SSH anywhere.
Hardware compatibility is unverified. Local tests use an independent binary
fixture producer, not a Steam Frame camera.

The adapter targets FHRING01 version 1 from Frametop commit
[`24a86dc02669caaef8386ea5bfeb08fcb2819944`](https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/camd/fhring.h).
The MIT notice is retained in `third_party/frametop/LICENSE`. Review ABI changes
before using newer broker builds. This is an experimental Frametop interface,
not an OpenXR camera API.

Example on a host where the operator has already configured the broker:

```bash
bash frame/run-diagnostic.sh \
  --frametop-ring /run/user/1000/framephone-camera/cam-ring \
  --camera EXACT_RING_CAMERA_NAME \
  --calibration-id YOUR_CAMERA_CALIBRATION_ID \
  --capture-clock YOUR_CAMERA_CAPTURE_CLOCK \
  --frames 300 --csv /tmp/frame-camera.csv
```

Use the actual runtime directory, exact ring camera name, calibration identity
and independently identified clock domain. No camera-name-to-calibration mapping
is inferred. A matching [camera calibration JSON](../protocol/camera-calibration.md)
and current phone-layout JSON enable pose via `--camera-calibration FILE
--phone-layout FILE`. `--no-detect` previews without estimating pose. `--headless`
polls and processes without playback pacing; the preview processes at `--fps`
(default 30). This is a single-camera consumer.

The reader validates version, file size, dimensions/stride, slot ranges and
overlaps. It copies the newest slot and checks its seqlock before and after the
copy. Incomplete/overwritten copies are discarded. Already delivered frames
are not repeated. New frame counters and capture timestamps must increase;
restarted/replaced/resized files or changed descriptors require restarting the
reader. Bounded `pread` avoids a mapped-file SIGBUS on truncation.

A heartbeat older than three seconds fails. Live input with no new stable
frame fails after `--idle-timeout-ms` (default 5000, maximum 60000); no new frame
is not EOF. Ctrl+C and window quit remain available during polling. Pause retains
the displayed frame; resume consumes the newest frame. R reopens the ring.
Dark-exposure streams are rejected. Color-luma streams can be read, but require
their own calibration and capture clock; no camera clocks are synchronized here.

CSV records source frame number, original camera `capture_timestamp_ns`, host
`dequeue_monotonic_ns`, host `publish_monotonic_ns`, V4L2 sequence and skipped
published frame count. Capture time is never replaced by host dequeue time.
Pose JSONL also includes this transport metadata. Skips between delivered frames
are intentional newest-frame behavior and do not measure the broker's own drops.
The first delivered frame has no prior baseline for counting skips.

The simple recording manifest remains unchanged and does not retain ring-only
transport fields. This adapter does not record raw camera images. Exports remain
explicit, local, and refuse an existing output file.

The hardware gate remains operator setup of a compatible broker, verification
of camera identity/geometry/clocks, a measured camera model, and a phone export
matching the frozen screen configuration. Headset extrinsics, capture-to-XR
clock mapping and historical headset poses are separate work.
