# Brief-marker ARCore handoff

An automatic tracking prototype: acquire a marker while the phone/headset relative position is stable,
establish an offset to SteamVR's standing space, then drive the existing VR
rectangle from phone ARCore poses. The existing continuously visible marker
mode remains available for phones without ARCore. Poses use the
[pinned Wi-Fi path](PAIRING_AND_IMU.md); Bluetooth handles pairing and setup.
Wi-Fi connects automatically after Bluetooth pairing. Screen streaming is future work.

## Run the test

1. Rebuild/install both apps and leave SteamVR running on the headset.
2. Enter phone width/height and tap **Connect**. Grant camera, notification and
   **display over other apps** access; install/update ARCore when requested.
3. Connect or pair on Frame as usual and put on the headset. Authentication plus a fresh positive wearer signal enables the overlay, and
   Frame automatically starts ARCore handoff and enables the VR rectangle.
4. Briefly show the complete tag to both front cameras. Two distinct accepted
   stereo observations spanning at least 80 ms can align, with up to 8 cm of
   headset-relative movement. The candidate world offsets must also agree within
   5 cm/0.12 rad. Camera/ARCore startup and processing add time. This faster gate
   deliberately accepts more initial alignment uncertainty.
5. The renderer confirms a visible rectangle before Frame acknowledges alignment.
   The overlay then closes without changing the foreground app. ARCore continues
   while Home or another app is visible.
6. Tracking loss, lock/unlock and new connections request another overlay
   acquisition automatically. A failed 20-second acquisition closes the overlay;
   **Retry tracking** in the phone UI or **Retry** in the notification starts a new
   attempt. Timeout never accepts or restores an alignment.

Back, Home, recent apps or a tap on the marker cancel tracking for the current
screen-on session. This suppression survives reconnect, Retry and session/anchor
changes; a real screen-off/unlock cycle clears it. The temporary overlay receives
Back input (including Android's predictive-back callback); system navigation and
focus loss dismiss it without launching an activity. A screen lock is not user
cancellation.

An independent `framephone-overlay --presence ACTION_MANIFEST` client runs before
acquisition. Its hidden OpenVR action set binds only `/user/head/proximity` through
the headset's reported input profile (using private, temporary binding files).
If the driver does not expose that action, the monitor falls back to OpenVR's
HMD activity state, as used by [Frametop's power service](https://github.com/Frametop/frametop/blob/adebd7d6cfc938477bf8e42a8bcb1c41a32a6f9c/power/ft-powerd.cpp).
UserInteraction/Timeout counts as active, Idle/Idle_Timeout/Standby as inactive,
with a 500 ms debounce. Unknown state and disconnect remain unavailable.
Direct proximity takes precedence, including a negative reading. Activity is
an approximation: movement can keep an unworn headset active, and inactivity
can take time to register. The activity log identifies the signal in use.
Missing proximity alone never blocks a known active headset.
The desktop forwards a session-scoped wearer heartbeat over the existing TLS link.
Unknown, disconnected or stale signals fail closed. The phone pauses its
ARCore camera and hides the marker when the headset is not worn; resuming requests
a fresh generation and alignment. SteamVR/input failure is visible in Frame's
status/log. The binding and navigation paths require validation on the devices.

**Disconnect** stops the link, camera service and overlay. Android requires one
special-access approval for drawing over other apps. The overlay is hidden on
lock, disconnect, camera contention or fatal tracking errors. Stop/Retry remain
available from the notification, and a timeout prevents indefinite screen cover.
Automatic recovery still uses a fresh marker; trusted marker-free pocket
relocalization and screen streaming are not implemented.

The camera foreground service owns a small offscreen EGL context and ARCore
session, so leaving the setup activity does not intentionally pause tracking.
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
before detector processing. Phone timestamps are mapped through the existing
low-RTT clock exchange. When Camera2 declares a REALTIME timestamp source and
provides exposure/rolling-shutter metadata, the phone also supplies an estimated
center-row exposure timestamp. It shares the IMU's elapsed-realtime epoch.
Otherwise the phone explicitly falls back to update-completion time, and raw
IMU prediction is disabled. ARCore's original frame timestamp is recorded
separately; its unspecified epoch is never assumed to match the sensor clock.
Headset camera exposure timing and factory/runtime extrinsics remain unverified.

Acquisition permits up to 8 cm of headset-relative marker position spread over
two or more distinct observations spanning at least 80 ms. It does not require
separate absolute-phone/head stillness.
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
offset and start a one-second visual fade. An invalid headset pose or tracking-origin
reset clears presentation immediately. Pose freshness is bounded to 250 ms. Reacquisition
does not silently trust the previous alignment. Drift correction, calibrated
extrinsics, complete headset exposure timing and trusted marker-free pocket
relocalization remain subsequent work. Screen-off detaches the paused phone
anchor; unlocking recreates it and requests a fresh optical alignment. A lost
offscreen GL context is rebuilt and camera textures rebound without dropping
the authenticated connection. Displayed
markers are detected even while ARCore is resuming; detection is not gated on
ARCore readiness or renderer availability. Display geometry changes restart the
optical session without blocking the paired link.

## Automatic lifecycle

The dashboard has no Start/Stop, VR visibility or ARCore mode switches. A connected
phone showing its marker starts the native tracker and VR renderer automatically.
Optical acquisition pauses after handoff or while the marker is hidden; valid
ARCore poses continue to render. Disconnect, lock, wearer state and deliberate
Back/Home dismissal still control phone-side availability. Worker or renderer
failure retries with a capped backoff; failure after handoff requests a fresh
phone marker so recovery cannot wait on a hidden target. Retry does not override
phone-side dismissal. A replacement renderer must publish its own visibility
heartbeat before alignment is acknowledged.

## CPU use and diagnostics

Active detector workers process the latest available camera frame/pair immediately,
without a per-frame delay or backlog. Both eyes use independent full-resolution
AprilTag detectors in parallel; corner refinement and pose rejection thresholds
are unchanged. Optical poses publish before the UI draws them. Alignment changes
and acknowledgments bypass the periodic diagnostic heartbeat, retaining the
two-observation, 80 ms, 8 cm acquisition requirement. Camera captions distinguish
published capture rate (sequence/capture-time deltas) from completed detection/
solve rate. These are sliding estimates; preview repaint rate is separate.

After acceptance the native stereo worker sleeps behind an acquisition gate:
no AprilTag detection, pose solve or image/log publication runs in that state.
Independent annotated preview workers also stop while a tracker session owns
the cameras, avoiding duplicate detection. Camera broker capture remains active;
this does not claim to turn off camera hardware. Views remain a diagnostic aid,
not a continually processed overlay during ARCore handoff.

A latest-only publisher delivers validated poses directly from the network
state to `phone-pose.json` at up to 90 Hz, independently of Tk callbacks. The
renderer runs at the reported headset display rate (60–144 Hz, 90 Hz fallback)
and caches unchanged metadata. During tracking, publications contain up to six measured
ARCore poses and a bounded recent gyro history; acquisition retains a longer
pose history. Paused packets retain bounded gyro history for the visual loss fade. No queue of stale poses
builds up, and publication never refreshes capture/receive timestamps.
ARCore poses and raw IMU samples use the pinned Wi-Fi connection. Bluetooth
handles enrollment and automatic connection setup. Handoff requires a recent
Wi-Fi clock exchange with round-trip time no greater than 40 ms.

Between ARCore frames the renderer predicts rotation using bias-corrected gyro
samples after the verified camera exposure time. Missing/old samples, unknown
clock epochs or gaps disable this correction. Integration is capped at 80 ms
and 0.35 radians; it restarts from an ARCore measurement on every render. Position
uses a least-squares fit to up to six measured ARCore poses within 100 ms,
requiring three samples, at least 20 ms span and fit RMS at most 1 cm. Prediction
stops at 40 ms/2 cm. Accelerometer-only
position integration is not used. Predicted values never feed registration or
become subsequent measurements. The 250 ms stale-data cutoff invalidates tracking
and starts a one-second fade. During that fade, fresh gyro samples can advance
orientation frame by frame; gaps, stale samples, an invalid clock or a changed
phone connection/ARCore generation stop that integration. Position is held. This
visual continuation never feeds registration or acknowledges an alignment.
See [VR display](VR_DISPLAY.md) for shell geometry and rear diagnostics.

A visual-only speed-adaptive filter follows prediction, based on the 1 Euro
principle of smoothing the derivative before adjusting the cutoff. Resting
cutoffs are 4 Hz for position and 3.5 Hz for rotation, rising to at most 10 Hz
during motion (roughly 16–45 ms filter time constants). Rotation stays on SO(3).
This light smoothing favors responsiveness. Missing poses, long render gaps, large corrections and new
acquisitions reset the filter. Neither smoothing nor prediction changes the raw
alignment/history, and smoothing does not correct accumulated ARCore/world drift.

The dashboard shows estimated phone-published pose rate, received pose rate,
actual render cadence, approximate pose age and prediction duration.
`arcore-state.json` also exposes camera-processing and delivery age estimates,
and whether gyro prediction was active. Missing camera metadata means age uses
update time instead of exposure time. Rate, freshness and prediction duration
are separate measurements; a faster render loop does not imply faster ARCore.
The phone requests a supported 60 FPS camera configuration when available;
actual camera/pose rate still depends on the device and lighting.

`vr-pose.json` remains the raw optical channel. The renderer's state heartbeat
controls the acquisition gate and acknowledgment. Raw phone sensors remain
available, and opt-in recordings include ARCore/capture timestamps, clock
exchanges and optical observations without pairing credentials. Transient LAN
loss after authentication retries the saved pinned endpoint with 1–5 second
backoff. Manual Disconnect/Forget cancels retries; identity/protocol failures
stop them. Reconnect never enrolls a new device.

Relevant code: Android `tracking/ArPoseService.kt` and `ArPoseState.kt`, desktop
`phone_link.py`, `pose_stream.py` and `fiducial_panel.py`, native
`arcore_handoff.hpp`, `pose_prediction.hpp`, `pose_smoothing.hpp` and `overlay_main.cpp`. Native registration tests run without SteamVR; synthetic
GUI tests check the acknowledgment/gate lifecycle. Neither establishes physical
accuracy or actual Android background-camera behavior.

See [tracking research and decisions](TRACKING_RESEARCH.md) for source evidence,
tuning rationale, damaged-cell recovery and the limits of partial occlusion.

ARCore reference: [sensor pose and frame timestamp](https://developers.google.com/ar/reference/java/com/google/ar/core/Frame).
See also [coordinates](COORDINATE_SYSTEMS.md), [VR display](VR_DISPLAY.md) and
the [companion session plan](../../docs/COMPANION_SESSION_PLAN.md).

Android overlay access uses the standard [Settings permission](https://developer.android.com/reference/android/provider/Settings#canDrawOverlays). No accessibility service or background activity launch is used.

Wearer input: [Valve headset action and binding manifest](https://github.com/ValveSoftware/steamvr_unity_plugin/blob/master/Assets/SteamVR/Input/ExampleJSON/actions.json).

Timing references: [Camera2 REALTIME clock](https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics#SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME), [ARCore capture metadata](https://developers.google.com/ar/reference/java/com/google/ar/core/ImageMetadata).
