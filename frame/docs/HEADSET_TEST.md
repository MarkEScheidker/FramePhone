# Test on a stock Steam Frame desktop

Build **`FramePhone-arm64.run`** on your Linux PC using
[BUILD.md](BUILD.md), or download the ARM64 package from a successful repository
workflow. Transfer that single file to the headset's Downloads folder. Frametop,
Docker, development containers and separate libraries are not needed to run it.

## Open it without terminal commands

1. In the desktop file manager, right-click `FramePhone-arm64.run`, open
   **Properties → Permissions**, and enable **Is executable** / **Allow executing
   file as program**. A transfer or ZIP download may remove this permission.
2. Open the file and choose **Execute/Run** if the file manager asks.
3. Click **Self-test**. A passing test decodes three synthetic frames through the
   real detector. This checks software startup and does not need the phone.
4. Transfer the measured layout JSON exported by the Android app, then use
   **Choose phone layout…** to select it. Keep the matching fiducial layout on
   the phone, with the measured physical display calibration.
5. Click **Enable cameras** and approve the desktop's authorization prompt.
   This starts FramePhone's bundled broker; there is no separate broker install.
6. Use the front left/right factory calibration choices and corresponding live
   stream dropdowns. **Refresh cameras** updates discovery after authorization.
   Check the previews: cover each physical front lens briefly to identify its
   stream. Do not infer camera identity from dropdown order or sensor/video names.
7. Click **Start tracking**. Hold the phone where both selected front cameras can
   see the tags. The window shows detection/pose output. **Stop** ends the test;
   closing the window also stops FramePhone's camera broker.

If your user has no administrator password yet, desktop authorization may need
that account configured first. If authorization or camera discovery fails, the
window shows the broker error. Leave that log available for debugging. This
first hardware run is expected to establish firmware/kernel compatibility.

## Results and repeatability

**Open test results** opens `~/.local/state/framephone/sessions` in the file
manager (or the equivalent `XDG_STATE_HOME` path). Each run has a new directory
containing the frozen phone layout, calibration SHA-256 identity, stream mapping,
pose JSONL and tracking CSV. Desktop/broker output is in
`~/.local/state/framephone/desktop.log`. Settings remember the layout path and
camera choices in `~/.config/framephone/settings.json`.

Enable **Record paired images** when collecting evidence for debugging. It
records grayscale image pairs and their manifest and can use substantial disk
space. Check actual images for complete tag boundaries and quiet zones. Phone
visibility in color passthrough alone does not establish visibility in these
mono tracking cameras.

The GUI uses the pinned broker's mono V4L2 timestamp convention as a shared
capture clock, with a maximum stereo skew of 3 ms. That is an assumption to check
on hardware, not a measured clock mapping. Verify front camera identity,
resolution/crop, tag detectability, metric scale and sustained processing cost
before trusting pose measurements. Full validation is in
[TRACKING_VALIDATION.md](TRACKING_VALIDATION.md).

Poses are **head-relative** T_HP, with head axes right/up/back and translations
in meters. This is a desktop tracking test, not a VR screen or world-space pose.
The app reuses Frametop's camera/calibration foundations but runs independently;
coexistence with a Frametop installation is deferred.
