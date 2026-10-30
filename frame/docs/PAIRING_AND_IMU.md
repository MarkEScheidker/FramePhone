# Pinned Wi-Fi control and sensor link v1

Pairing is exclusively [Bluetooth](BLUETOOTH.md). The phone's TLS listener accepts
only reconnect authentication with the credential established over verified TLS carried by
Bluetooth. UDP discovery, manual IP entry and LAN enrollment have been
removed from the applications.

## Connection lifecycle

Frame advertises while running. Pair it once from the Android app. Bluetooth
provides the current phone route and certificate pin; Wi-Fi connects automatically.
Initial connection failures and transient transport loss retry with capped 1–5
second backoff. A phone screen-on/unlock requests another Bluetooth route exchange
if Wi-Fi is disconnected. Identity/protocol failures stop the current retry loop
and remain visible; an address is never treated as identity.

The dashboard shows Bluetooth and Wi-Fi state plus compact gyro, accelerometer
and magnetometer diagnostics. Neither app offers transport selection or manual
network setup. Android Disconnect disables companion wake until Connect is used;
Forget removes application trust and the phone's companion association. Remove
the OS Bluetooth bond separately in system settings when needed.

## Authentication

The phone serves TLS 1.3 on TCP port 47643 with a persistent P-256 identity in
Android Keystore. Frame checks the complete saved SHA-256 certificate hash before
sending the reconnect credential. New trust and endpoint hints arrive over TLS 1.3 carried by Bluetooth.
First enrollment requires matching hashes approved on both devices after OS
bonding; Wi-Fi cannot enroll another device. Reinstalled or desynchronized
apps recover over Bluetooth with Frame confirmation; see the
[Bluetooth enrollment flow](BLUETOOTH.md#first-connection). An OS bond must still exist
for a new TLS authentication. Manual unpairing closes the active phone connection.

Frame stores the pin and credential atomically in a private mode-0600 pairing
file. Android keeps the SHA-256 verifier in private preferences; its temporary
Bluetooth enrollment secret is removed after acknowledgment. One paired headset
and one active TLS connection are supported. See the Bluetooth contract for
TLS enrollment, session binding and background camera restrictions.

Networking runs as the desktop user. Camera authorization is separate and may
appear once on startup. Camera interception/AprilTag previews remain idle unless
a fresh authenticated phone message says the marker is visible. ARCore handoff
retains clock/control traffic and raw sensor recordings while optics sleep.

## Wire format

TLS carries unsigned 32-bit big-endian byte length followed by UTF-8 JSON,
maximum 65,536 bytes per message. Nanosecond timestamps and sequences are JSON
integers (Kotlin Long / Python int); never route these through floating-point
JSON consumers. Android bounds JSON nesting before parsing. Version mismatch,
malformed data, unexpected sessions and reordered samples close the connection.

| Message | Fields and direction |
| --- | --- |
| `hello` | Frame → phone: `version:1`, `mode:reconnect` and the Bluetooth-established `credential`. LAN pairing mode is rejected. |
| `profile` | Phone → Frame: version, fresh session UUID, phone name, dimensions, sensor capabilities, axes and clock. Sent only after authentication. |
| `ping` / `pong` | Frame sends `h0`; phone returns it with receive/send `p1,p2` and session; Frame records receive `h3`. |
| `samples` | Phone → Frame: session, cumulative queue-drop count, array of at most 64 sensor events. |
| `error` | Phone → Frame, after TLS: fixed `code` for closed pairing, rejected/expired approval, failed authentication or protocol error. No credentials or raw request contents. |

The profile's `dimensions` has `width_m`, `height_m`,
`boundary:body_or_case`, `source:manual`. Older thickness fields are ignored. These dimensions do not imply active
screen size, physical IMU location or a camera pose. Single-tag pose uses the separate fiducial profile's black edge and decoded
orientation. Its initial scale is from unverified Android display DPI; body size
is not substituted for marker size.

## Wearer presence

A phone profile with `headset_presence_v1:true` accepts `headset_presence` commands
containing the authenticated connection `session` and Boolean `worn`. Frame sends
changes immediately and renews the value every 500 ms. The network worker forces
`false` if the original OpenVR report is older than one second; forwarding the
same report does not renew its timestamp. The phone requires a positive receipt
within 1.5 seconds before showing its marker or running ARCore. Disconnect clears
this permission. The updated phone defaults to disabled until a fresh positive
command; rebuild both applications together. This is presence control on the
existing pinned TLS link, not a new pairing or wakeup transport.

## Optional ARCore extension

Frame advertises `arcore_pose_v1:true` in `hello`; the updated phone echoes it
in `profile`. Older peers retain the original sensor/marker behavior. An opted-in
peer can receive `arcore_pose` messages over the same authenticated TLS stream.
Raw sensor messages are unchanged.

A pose has the connection `session`, anchor `generation`, marker `acquisition`,
monotonic `seq`, `state` (`tracking`, `paused`, `error`, `stopped`) and
`marker_required`. Tracking messages contain `translation_m` and a unit
`quaternion_xyzw`, expressing `T_AD` (anchor-relative natural-device sensor pose).
`t_ns` uses `update_elapsed_realtime_ns`, sampled after session update;
`frame_timestamp_ns` retains ARCore's original unspecified-epoch frame clock.
Optional `capture_t_ns` with `capture_time_source:camera2_realtime_center_exposure`
is accepted only for verified Camera2 REALTIME clocks with exposure metadata and
a plausible capture-to-update interval. Unknown epochs keep the update-time
fallback; they never enable raw gyro prediction.

Frame bounds pose history to 90 entries, validates transforms and ordering, and
maps update timestamps with the existing clock exchange. The handoff requires a
recent exchange with RTT at most 40 ms. Stale poses do not drive the VR surface.

The headset may send `alignment_accepted` or `alignment_lost` with the connection
session, generation and acquisition. The phone accepts an acknowledgment only
for its current fresh tracked acquisition. Loss requests a new acquisition;
delayed commands cannot dismiss a newer marker. Commands use a bounded queue on
the existing network worker. No new socket, trust authority or cryptography is
introduced. See [ARCore handoff](ARCORE_HANDOFF.md) for acquisition and limits.

Each capability names `gyro`, `accel` or `mag`, with `available`, Android
sensor type, units, calibrated/uncalibrated flag, requested rate, minimum delay
and sensor name when present. Events contain `sensor`, per-sensor `seq`,
original integer `t_ns`, three-component `v`, Android `accuracy`, and
optional three-component vendor `bias` kept separate from values.

| Sensor | Units | Requested rate |
| --- | --- | --- |
| Gyroscope | rad/s | 200 Hz |
| Accelerometer, including gravity | m/s² | 200 Hz |
| Magnetometer | µT | 50 Hz |

These are requested rates; actual delivery is measured. Uncalibrated channels
are preferred, with explicit calibrated fallbacks. Missing sensors are reported.
Axes are `android_natural_device`: X right, Y up in the device's natural
orientation, Z out of the screen; UI rotation does not change them. A future
canonical-phone transform must handle landscape-natural devices explicitly.

Sensor callbacks copy to a bounded 256-record queue. The writer drops observations
older than 100 ms, sends up to 64 every nominal 10 ms, and reports cumulative
drops. Sequence gaps remain visible. Stalled writes trigger socket closure;
missing heartbeats also disconnect. TCP latency and actual throughput need
measurement on the phone/headset LAN. GUI values become stale after one second
without a fresh observation and clear after disconnect.

## Clock diagnostics and future fusion

Android timestamps use `elapsedRealtimeNanos()`; Frame uses host monotonic
nanoseconds. Four-timestamp probes run every two seconds. The best round-trip
exchange from the last ten seconds gives a **rough** offset and network timing
budget for displayed sample age. Large offset changes discard old samples.
Clock state resets on every new connection.

This is not a calibrated fusion clock: it does not fit clock drift or align
camera capture time to host/OpenXR time. Round-trip timing cannot identify
network asymmetry; displayed age can be slightly negative. The diagnostic shows
a half-round-trip timing budget, not a guarantee of measurement accuracy.

Future pose estimation must account for independently moving phone and headset.
Ordinary camera-rigid IMU odometry is not a drop-in replacement. Use historical
headset poses for optical observations; gravity/magnetometer need reliability
gates, and inertial integration cannot maintain reliable position indefinitely
without optical corrections. QR/optical target association, axis/lever-arm
calibration, camera/XR clock alignment and visual-inertial fusion remain future work.

## Validation

The marker test negotiates `marker_state_v1` in hello/profile. Approximately
every 250 ms, `marker_state` reports the authenticated session, whether the marker
surface is displayed and its current fiducial profile. Actual screen_width_px,
screen_height_px and black_edge_px describe the drawn fullscreen layout. These
fields are validated before use. A hidden/stale state, changed geometry or
disconnect clears the optical test and VR pose. Older marker profiles still
support camera-based tracking without this visibility extension.

These state messages contain no screen image. The old one-time photo-transfer
protocol has been removed. Sensor observations and marker state are opt-in
recordable evidence; credentials and arbitrary peer fields are excluded.

`python3 frame/tests/test_phone_link.py` exercises real local TLS enrollment,
rejection, reconnect, changed-key rejection before credential transmission,
credential rejection, bounded framing, integer precision, stale/gap/rate handling
and private persistence. Android `ProtocolTest` checks physical units, invalid
dimensions, bounded parsing and matching wire/fingerprint conventions.
These checks do not replace Android Keystore/sensor and Steam Frame LAN trials.

Android's host `TlsSelfCheckTest` exercises pinned TLS 1.3 and wrong-pin rejection.
The device `IdentityTlsTest` exercises the real Android Keystore and Conscrypt;
run `:app:connectedDebugAndroidTest` on a connected phone/emulator. The same TLS
self-check runs during normal phone startup. Connection errors identify the
failed stage; handshake details are visible on the phone and under the FramePhone
Android log tag. Encrypted application rejections use fixed error codes, rather
than closing without an explanation. Frame still requires TLS 1.3 and its saved
certificate pin for reconnects.

Hardware check: pair, rotate the phone and verify changing gyro/accel/magnetic
values; check rates and unavailable sensors; stop/restart both apps and reconnect;
reject a pairing; revoke on the phone and verify reconnect fails; test Wi-Fi loss
and suspend/resume. Confirm no old readings remain labeled live after disconnect.

References: [Android sensors](https://developer.android.com/reference/android/hardware/SensorEvent),
[TLS signing authorizations](https://developer.android.com/reference/android/security/keystore/KeyProtection.Builder),
[Keystore](https://developer.android.com/privacy-and-security/keystore),
[foreground service types](https://developer.android.com/develop/background-work/services/fgs/service-types)
and [TLS 1.3](https://www.rfc-editor.org/rfc/rfc8446.html).
Android currently targets SDK 36; future target-37 builds must account for
[local-network permissions](https://developer.android.com/privacy-and-security/local-network-permission).

Updated phones also report `automatic_marker_v1:true`. Frame selects ARCore
handoff automatically and starts when the authenticated marker state becomes
visible. Tracking and VR rendering are automatic, with capped retries after native failures. Phone-side Back/Home dismissal remains suppressed until the next unlock. The
phone arms its camera foreground service from the visible Connect action, opens
ARCore only after authentication, and controls a TYPE_APPLICATION_OVERLAY window.
Lock/disconnect/loss fence acquisition IDs. Successful acknowledgment requires
native `visible:true` after the OpenVR update succeeds. See the handoff guide.

Renderer publication is independent of Tk. Live compact packets contain the
latest six measured poses and up to 64 bias-corrected natural-device gyro samples; an
acquiring packet retains up to 90 poses for history matching. Sensor and camera
clocks map through the same validated exchange. A detected clock discontinuity
clears both histories. Raw sensor/ARCore recordings retain original timestamps.
See the handoff guide for prediction bounds and rate/age diagnostics.
