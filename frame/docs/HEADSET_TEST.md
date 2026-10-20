# Test on Steam Frame

The primary experiment is now **Photo tracking**. Install the updated Android
APK, pair/connect, and choose a detailed photo on the phone. Keep it displayed.
On Frame choose **Photo tracking → Use phone photo → Enable cameras → Refresh
cameras → Start photo tracking**. Confirm inlier counts, outline, XYZ/distance,
rotation and photo size. Cover/reveal the screen to test loss/reacquisition.
Use **Learned (XFeat/LighterGlue)** for the new static-image experiment. It searches
calibrated front-camera views and narrows the search around the last accepted
photo. Hold still for a search cycle. **Camera setup → Model check** tests model
loading separately from the geometry self-test. A working Android photo transfer
needs no new APK for this change; rebuild the Frame `.run` with the normal command.
See [the fixed-photo procedure](PHOTO_TRACKING.md) for details and limits.

The historical instructions below describe the retained marker source/tool;
that workflow is no longer exposed in the normal app UI. Use the photo procedure
above for current headset testing.

Build with **`bash frame/build.sh`**, on the headset or a Linux PC, and open
`frame/build/dist/FramePhone-arm64.run` on Frame after enabling execution in file
Properties. Runtime libraries and the camera broker are bundled.

Install the updated Android APK, enter phone/case dimensions and start the
connection. In **Phone telemetry**, find/pair the phone and approve matching
fingerprints, or connect the saved phone. Tap **Show large tracking marker** on
Android. It automatically fills the screen width with one centered tag plus
the required white margin; there is no marker-size input.

In **Marker tracking**, enable cameras and approve desktop authorization.
Refresh cameras, choose the two front streams and their matching factory
calibrations, then **Start tracking**. No frozen capture or corner labelling.
The expected front defaults are `og01a1b_4-0060_video3` with `slam_left` and
`og01a1b_4-0036_video0` with `slam_right`. Cover each front lens to verify the
stream. Factory-to-stream association remains provisional; sensor names alone
do not prove identity. Side cameras are not used.

**Camera setup → Show front camera views** provides previews and full-size
native pixels. The geometry self-test exercises detection/pose plumbing using
synthetic inputs, not headset accuracy.

Start with the entire marker visible to both views, then tilt/move it slowly.
You should see ID counts, marker outlines and marker-center XYZ/rotation.
Hide it: current pose must disappear. Reveal it: tracking should reacquire.
A single view's detection is shown but cannot produce this stereo pose.
Use optional camera/telemetry recording for difficult trials.

Distance scale comes from Android's unverified physical display DPI. Check it
against known distances before interpreting accuracy. See
[single-marker tracking](FIDUCIAL_TRACKING.md), [calibration](CALIBRATION.md)
and [validation](TRACKING_VALIDATION.md). Whole-phone screen recording is
separate and has [on-screen marker constraints](SCREEN_CAPTURE.md).
