# Test on a Steam Frame desktop

Build **`FramePhone-arm64.run`** on Linux desktop or the headset using
[BUILD.md](BUILD.md), or download the ARM64 artifact from a successful repository
workflow. Transfer the single file to Downloads. In file Properties enable
execution, then open it. Frametop and a runtime container are not required.

## Pair and receive sensors

On the phone, enter the outside body/case dimensions and start pairing.
Use **Phone telemetry → Find phones → Pair new phone**, compare the fingerprint
and approve both screens. Live sensor values and dimensions should appear.
Use **Connect saved phone** on later connections. See [pairing](PAIRING_AND_IMU.md).

## Set up the front cameras

Choose **Enable cameras** and approve the desktop authorization prompt. The app
starts its bundled broker; no separate install is needed. Refresh if necessary.
Select the two front streams and their matching factory cameras in **Markerless
tracking**. **Camera setup → Show front camera views** exposes only that pair;
open full-size views to inspect native source pixels. Cover each physical lens
to verify the streams.

Defaults use the owner's front-left `og01a1b_4-0060_video3` with `slam_left`,
and front-right `og01a1b_4-0036_video0` with `slam_right`. Existing available
selections take priority. These factory associations remain provisional;
sensor names/video numbers do not prove calibration identity. Missing defaults
stay unselected instead of substituting another stream. Ignore the side cameras.

**Geometry self-test** exercises the native body-pose solver without hardware.
The integrated log shows discovery, source dimensions and broker failures.

## Try markerless pose

Follow the [markerless diagnostic](MARKERLESS_DIAGNOSTIC.md): capture a synchronized
pair, label the same physical front corners in each view, estimate pose, and
start local outline tracking. Hold still during initialization and move slowly.
It needs a clear front boundary in both cameras. Capture again after loss.

Use opt-in recordings for difficult cases and measure pose against an independent
reference. Camera calibration/mapping, clock assumptions and real tracking
accuracy remain to be verified. See [validation](TRACKING_VALIDATION.md).
