# Brief-marker ARCore handoff

An opt-in tracking prototype: acquire a marker while both devices are steady,
establish an offset to SteamVR's standing space, then drive the existing VR
rectangle from phone ARCore poses. The existing continuously visible marker
mode remains available. Bluetooth and screen streaming are separate future work;
this test uses the existing authenticated LAN connection.

## Run the test

1. Rebuild/install the Android APK and rebuild the Frame executable. Connect the
   apps as usual and leave SteamVR running on the headset.
2. On the phone, tap **Start ARCore + brief marker**. Approve camera access and
   installation/update of Google Play Services for AR if requested. Keep the
   phone's rear camera uncovered with a view of a lit, textured room.
3. On Frame, select **Use ARCore after brief marker alignment (experimental)**,
   then **Start tracking**. This mode enables the VR display automatically.
4. Hold both the phone and your head still, with the complete tag visible to
   both front cameras. Acquisition requires at least four distinct accepted
   observations spanning 600 ms. Initialization/processing can take longer.
5. After the headset acknowledges alignment, the phone marker closes and the
   app task moves behind Home/the previous app. Move the phone and your head
   independently and compare the rectangle with the physical phone.
6. To realign, tap **Show marker** in the phone's tracking notification. After
   tracking loss, this first version also requires another marker observation;
   automatic recovery without it is deliberately not yet implemented.

**Stop ARCore** or the tracking notification's **Stop tracking** releases the
phone camera. **Stop connection** also stops ARCore. Stopping tracking on Frame
hides its rectangle; stop ARCore on the phone when finished to release camera
resources. This prototype does not start tracking automatically after unlock.

The camera foreground service owns a small offscreen EGL context and ARCore
session, so leaving the marker activity does not intentionally pause tracking.
Camera contention, device restrictions, lock/sleep and actual tracking quality
still require physical-phone testing. Error/status text appears in Android's
setup screen; the Frame dashboard reports acquisition and loss state.

## Registration and validity

ARCore produces the natural-device sensor pose relative to a local anchor:
`T_AD = inverse(T_world_anchor) * T_world_device`, using same-frame poses.
This avoids treating the raw ARCore world origin as immutable. No cloud anchor
or shared room map is used. Android retains its native ARCore world; the headset
applies a separately estimated offset.

The headset estimates `T_WA = T_WH * T_HM * inverse(T_AD)` during acquisition and
later renders `T_WM = T_WA * T_AD`. This assumes `T_DM = identity`: device sensor
and screen-center axes/origins are provisionally coincident. It targets phones
with a portrait natural orientation. The uncalibrated translation between those
origins introduces error during rotation; this is not calibrated screen tracking.
Factory-head/runtime-HMD extrinsics and display DPI also remain provisional.

Headset pose history is matched to the host time the stereo pair was obtained,
before detector processing. Phone pose history uses elapsed-realtime timestamps
taken after ARCore update and the existing low-RTT clock exchange. ARCore's
original frame timestamp is recorded separately; its epoch is not assumed to be
elapsed realtime. These are approximate observation/update times, not calibrated
exposure timestamps. Stationary gating reduces their motion error rather than
claiming to compensate it.

The gate compares against fixed baselines: approximately 1 cm phone/optical
translation, 8 mm headset translation and 1.4 degrees of rotation. It also checks
recent motion during detector processing, optical RMS, distinct observations,
history proximity and interruptions. Moving observations restart acquisition.
Alignment is acknowledged only for the current connection, anchor generation and
acquisition ID. Delayed acknowledgments cannot close a new marker acquisition.

ARCore loss, stale phone poses, clock failure, anchor/session/acquisition changes,
invalid headset tracking and reported SteamVR recenter events invalidate the
offset and hide the surface. Pose freshness is bounded to 250 ms. Reacquisition
does not silently trust the previous alignment. Drift correction, calibrated
extrinsics, exposure timing, smoothing/prediction and seamless pocket recovery
remain subsequent work.

## CPU use and diagnostics

After acceptance the native stereo worker sleeps behind an acquisition gate:
no AprilTag detection, pose solve or image/log publication runs in that state.
Independent annotated preview workers also stop while a tracker session owns
the cameras, avoiding duplicate detection. Camera broker capture remains active;
this does not claim to turn off camera hardware. Views remain a diagnostic aid,
not a continually processed overlay during ARCore handoff.

The native renderer reads bounded, atomically replaced `phone-pose.json` and
`vr-pose.json`; its `arcore-state.json` heartbeat controls the dashboard's gate
and phone acknowledgment. A missing/failed renderer cannot acknowledge a handoff.
Raw phone sensors remain available. Opt-in recordings include ARCore frames,
clock exchanges and optical observations without pairing credentials.

Relevant code: Android `tracking/ArPoseService.kt` and `ArPoseState.kt`, desktop
`phone_link.py` and `fiducial_panel.py`, native `arcore_handoff.hpp` and
`overlay_main.cpp`. Native registration tests run without SteamVR; synthetic
GUI tests check the acknowledgment/gate lifecycle. Neither establishes physical
accuracy or actual Android background-camera behavior.

ARCore reference: [sensor pose and frame timestamp](https://developers.google.com/ar/reference/java/com/google/ar/core/Frame).
See also [coordinates](COORDINATE_SYSTEMS.md), [VR display](VR_DISPLAY.md) and
the [companion session plan](../../docs/COMPANION_SESSION_PLAN.md).
