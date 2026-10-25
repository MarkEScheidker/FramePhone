# Brief-marker ARCore handoff

An automatic tracking prototype: acquire a marker while their relative position is stable,
establish an offset to SteamVR's standing space, then drive the existing VR
rectangle from phone ARCore poses. The existing continuously visible marker
mode remains available. Bluetooth and screen streaming are separate future work;
this test uses the existing authenticated LAN connection.

## Run the test

1. Rebuild/install both apps and leave SteamVR running on the headset.
2. Enter phone width/height and tap **Connect**. Grant camera, notification and
   **display over other apps** access; install/update ARCore when requested.
3. Connect or pair on Frame as usual. Authentication triggers the overlay, and
   Frame automatically starts ARCore handoff and enables the VR rectangle.
4. Keep the complete tag visible to both front cameras. Its position relative
   to the headset must stay within 2 cm over at least 500 ms, with at least four
   distinct accepted observations. The devices may move together in the room.
5. The renderer confirms a visible rectangle before Frame acknowledges alignment.
   The overlay then closes without changing the foreground app. ARCore continues
   while Home or another app is visible.
6. Tracking loss, lock/unlock and new connections request another overlay
   acquisition automatically. A failed 20-second acquisition closes the overlay;
   **Retry tracking** in the phone UI or **Retry** in the notification starts a new
   attempt. Timeout never accepts or restores an alignment.

**Disconnect** stops the link, camera service and overlay. Android requires one
special-access approval for drawing over other apps. The overlay is hidden on
lock, disconnect, camera contention or fatal tracking errors. Stop/Retry remain
available from the notification, and a timeout prevents indefinite screen cover.
Automatic recovery still uses a fresh marker; trusted marker-free pocket
relocalization and screen streaming are not implemented.

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

Stability is a maximum 2 cm spread in headset-relative marker position over a
minimum 500 ms batch, rather than separate limits on absolute phone/head motion.
Current ARCore/headset poses also check relative movement during detector work.
The gate validates registration consistency, optical RMS, distinct observations,
history proximity and interruptions. Acquisition tolerates detector intervals
longer than the 250 ms live-render timeout without repeatedly erasing its batch;
phone pose freshness for rendering remains bounded to 250 ms.

Alignment acknowledgments require a fresh native renderer heartbeat with a
visible overlay and matching connection/generation/acquisition IDs. A delayed
acknowledgment cannot dismiss a new acquisition. Missing or failed rendering
leaves the marker visible until recovery or timeout.

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

Android overlay access uses the standard [Settings permission](https://developer.android.com/reference/android/provider/Settings#canDrawOverlays). No accessibility service or background activity launch is used.
