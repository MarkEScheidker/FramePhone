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
4. Click **Enable cameras** and approve the desktop's authorization prompt.
   This starts FramePhone's bundled broker; there is no separate broker install.
5. Select the two front streams in the left/right dropdowns. Only normal-exposure
   OG0VE10 front streams are offered; side cameras are excluded. Their factory
   calibration names are fixed to **upper_left / upper_right**. The old defaults
   `slam_left / slam_right` describe the side cameras and are no longer used.
   **Refresh cameras** updates discovery after authorization.
6. Enable **Show front camera views** and cover each physical front lens briefly
   to identify its stream. Use **Swap left/right streams** if needed. Do not infer
   camera identity from dropdown order or sensor/video numbers. Click a preview
   or **Open full-size view** to inspect the actual source pixels.
7. Display the phone's fiducials. Live detection starts automatically once both
   streams are selected, even with previews hidden and without a phone layout.
   The large label reports **I can see N tracking marker IDs**, counting each ID
   once across both views. Each view also reports its own count, IDs and source
   dimensions. **0 tracking markers detected** means frames were processed with
   no decoded phone tags; **Waiting** means no fresh detection result. Stale
   results expire rather than leaving an old count visible.
8. For position/rotation, transfer the measured layout JSON exported by the
   Android app and use **Choose phone layout…**. Keep the matching fiducial
   layout on the phone, with the measured physical display calibration.
   Click **Start tracking** and hold the phone where both front cameras see the
   tags. Marker counts remain visible; a separate pose line reports accepted
   tracking/distance, insufficient shared tags or ambiguity. Stream selection is
   locked during tracking. **Stop** ends the stereo test and resumes detection;
   closing the window also stops FramePhone's camera broker.

If your user has no administrator password yet, desktop authorization may need
that account configured first. If authorization or camera discovery fails, the
window shows the broker error. Leave that log available for debugging. This
Hardware compatibility can vary with headset firmware/kernel versions.

## Resolution and marker visibility

There is no 640×640 capture setting in FramePhone. The broker copies the mono
stream XRService already produces, and detection runs on those source pixels.
The pinned Frametop integration identifies the front pair as OG0VE10 sensors;
OMNIVISION specifies **640×480** for the [OG0VE sensor](https://www.ovt.com/products/og0ve/).
FramePhone reports the actual dimensions beside each view and detection count
so that the stream on your headset can be checked directly.

The old embedded preview reduced 640×480 to approximately 213×160. The new
embedded views are larger, and the full-size windows display native pixels
without that reduction. Changing preview size does not improve capture detail.
FramePhone does not change XRService's camera modes. The appearance of the
headset's passthrough view does not establish the resolution or contrast of
these raw mono tracking streams.

If both counts stay at zero, inspect the full-size images first: all tag cells,
the black boundary and the surrounding white quiet zone must be distinguishable.
Try holding the phone closer or increasing the displayed tag size. Compare each
view's count before starting stereo tracking; decoded markers with a rejected
pose indicate a different problem from no decoded markers.

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
