# Bluetooth companion sessions

Proposed direction, researched 2026-10-25. Most of this flow is future work; an
automatic [brief-marker ARCore handoff test](../frame/docs/ARCORE_HANDOFF.md) now uses
the existing LAN link. The working stereo marker tracker, LAN pairing and VR rectangle remain
the baseline. See the [roadmap](ROADMAP.md) and
[coordinate conventions](../frame/docs/COORDINATE_SYSTEMS.md).

## Intended experience

The phone is a persistent companion to FramePhone on the headset. Bluetooth
establishes presence and carries pose telemetry; Wi-Fi carries the screen image.
The Android setup screen collects width and height and manages pairing. Ongoing
work belongs to a companion service, with visible session/stop controls.

First setup:

1. Open both apps and enter phone width and height. Setup uses width/height; older thickness preferences are ignored.
2. Select the headset in Android's companion-device picker, approve Bluetooth
   pairing on both devices and establish application trust.
3. Grant the required Bluetooth, notification and camera permissions. Check
   ARCore availability and explain the separate screen-sharing approval.
4. Verify screen scale and camera-to-screen calibration. Body dimensions are
   not active-display dimensions; reported Android DPI remains unverified.

Normal use:

1. The running Frame app advertises its companion service. The associated phone
   detects it and reconnects without opening the setup screen.
2. The devices authenticate, exchange current LAN endpoints over Bluetooth and
   establish the pinned Wi-Fi connection automatically.
3. On unlocking, start the tracking/capture session through the UI route Android
   permits. The practical baseline is a notification action followed by the
   system screen-sharing approval when required.
4. The running phone session starts ARCore and shows its marker overlay. Aim
   for two consistent stereo observations spanning at least 80 ms, allowing up to 8 cm relative movement once ARCore is ready. Hide it only after the
   headset acknowledges a valid alignment from several observations.
5. Return to Home or another app. ARCore poses travel over Bluetooth; the entire
   display travels over Wi-Fi into the existing SteamVR screen surface.

The network connection should become automatic. The marker now uses an approved application overlay and reappears after unlock
when the running session needs alignment. Fully unattended screen capture
remains constrained by per-session consent.

## Android constraints to validate first

CompanionDeviceManager associates a device with the app and offers presence and
background-service support. Association does not itself create a Bluetooth
connection. Use the presence API appropriate to the OS: Android 16 introduced
replacement APIs for the older callbacks. Waking a companion service and opening
an activity are separate operations; check the applicable activity-launch
exceptions on the actual phone. See Android's
[companion pairing](https://developer.android.com/develop/connectivity/bluetooth/companion-device-pairing)
and [activity launch rules](https://developer.android.com/guide/components/activities/secure-bal).

Android requires consent for each new MediaProjection session, and current
Android documentation specifies that locking the display stops projection.
After that, unlocking requires a newly approved capture session. Select full
display sharing to include Home and app switching. A setup-time permission
cannot stand in for later capture approvals. See
[MediaProjection](https://developer.android.com/media/grow/media-projection).

A camera foreground service can continue camera access after leaving the app,
but starting it from the background is restricted. That does not establish that
an ARCore session and its GL update loop will work reliably outside an activity
on every device. Start while visible and test Home, app switching, screen lock,
camera contention and process recreation before building the product around it.
See [foreground-service types](https://developer.android.com/develop/background-work/services/fgs/service-types)
and the [ARCore Session API](https://developers.google.com/ar/reference/java/com/google/ar/core/Session).

If this test fails, the next decision is a different supported session workflow
or tracking approach; a transport rewrite cannot fix camera lifecycle limits.

## Transport and trust

| Responsibility | Proposed implementation |
| --- | --- |
| Presence and initial connection | Frame advertises a custom BLE service while running; Android is the central/GATT client, with companion association and presence observation. |
| Headset Bluetooth integration | Host BlueZ through system D-Bus; use its existing adapter, pairing agent and security. No replacement Bluetooth daemon or custom HCI stack. |
| Reliable session control | Acknowledged GATT operations for capabilities, endpoint changes, alignment requests/acknowledgments and session state. |
| Phone-to-headset poses | Small binary GATT writes without response, with bounded application queues and sequence/timestamp checks. |
| Wi-Fi bootstrap/control | Keep the existing phone TLS server and Frame client; pass endpoint hints over authenticated Bluetooth instead of requiring broadcast discovery. |
| Video | Full-display MediaProjection, hardware H.264 where supported, and a maintained encrypted real-time video stack; WebRTC is the preferred candidate to validate. |

Linux BlueZ exposes local GATT services through
[its GATT D-Bus API](https://bluez.readthedocs.io/en/latest/gatt-api/) and handles
pairing interaction through the [agent API](https://bluez.readthedocs.io/en/latest/agent-api/).
Advertising/peripheral support and user-level D-Bus permissions on Frame must
be demonstrated before treating this role assignment as settled.

The first version assumes both devices already use the same reachable LAN.
Bluetooth exchanges addresses and ports, not Wi-Fi passwords. Hotspot/Wi-Fi
Direct provisioning is a separate feature. A shared SSID does not guarantee
reachability when an access point isolates clients; report that explicitly.

Use authenticated, encrypted Bluetooth bonding with user-confirmed numeric
comparison where supported. Bind that approved bond to the application pairing
record; do not authorize telemetry from an arbitrary nearby or merely named
device. Require encrypted/authenticated GATT access for sensitive operations.
Do not silently downgrade enrollment to unauthenticated pairing.

Reuse the current pinned phone certificate and reconnect credential for Wi-Fi.
The Bluetooth setup can carry the public certificate fingerprint through the
approved link; keep explicit first-enrollment confirmation. Persist the approved
peer identities, and verify the complete saved certificate before sending any
reconnect credential. An IP address is only a route to a peer, not its identity.

Private identity keys remain on their originating devices. Bluetooth and TLS
negotiate their own encryption keys; there is no reason to transmit private keys
or implement an encryption algorithm. Bind the two authenticated connections to
one fresh application session, with challenge/session checks before accepting
cross-transport commands. Specify and review this binding before implementation.
Forgetting a peer must revoke application trust as well as remove its companion
association/bond as requested; changing identities requires deliberate pairing.

## Pose delivery and latency

Start with BLE, not an audio/headset profile. The earbuds analogy describes
reconnection; the payload needs a custom data service.

Each pose carries a protocol version, session/anchor generation, sequence number,
phone monotonic capture timestamp, position, quaternion and tracking state.
Negotiate packet size and capabilities; never assume a particular MTU or PHY.
Request high connection priority while actively tracking, and 2M PHY when both
ends support it. These are requests, not guaranteed latency settings. See the
[Android BluetoothGatt API](https://developer.android.com/reference/android/bluetooth/BluetoothGatt).

Keep only the newest unsent pose. Reliable control commands must not sit behind
a backlog of old motion samples. Retain optional raw gyro/accelerometer/
magnetometer diagnostics as requested, but batch/rate-limit them independently
so they cannot delay ARCore poses. Do not add another sensor-fusion estimator
until measurements establish a need.

Measure pose age and jitter, loss, reconnect time, clock-offset uncertainty and
p50/p95/p99 latency while Wi-Fi video is active. Measure against the current LAN
path too: Bluetooth is the requested primary transport, not automatically the
lowest-latency radio. Prefer freshness to delivery of obsolete poses.

## Shared coordinates and brief marker alignment

ARCore and SteamVR maintain independent coordinate systems. We do not need
access to either device's internal room map. A synchronized view of the marker
establishes the transform relating the two systems.

The existing renderer is head-relative. Before marker-free operation, add:

- Headset world-pose history at optical exposure times, with verified conversion
  between factory camera/head coordinates and SteamVR HMD coordinates.
- Explicit clock mapping between optical frames, headset poses and phone ARCore
  frames, including uncertainty and rejection of badly matched times.
- A calibrated transform from ARCore's physical camera to the displayed marker
  and screen. One observation cannot solve this unknown and world alignment
  simultaneously. Use a separate multi-pose calibration or known extrinsics.
- An anchor-relative ARCore pose and generation identifier so resets or tracking
  corrections cannot silently reuse an old world alignment.

At acquisition, fit/validate alignment from a short batch of matching optical
and ARCore observations while both tracking systems report usable data. Use
quality thresholds and reject inconsistent observations. Approximately one
second is a target, not an unconditional timeout: ARCore initialization, an
occluded tag or insufficient light can require longer. The headset sends an
alignment-accepted acknowledgment before the phone hides the marker.

During normal use, compose the current anchor-relative phone pose with the
accepted world alignment, then render using the current headset pose. This
allows the phone and headset to move independently without keeping the marker
visible. ARCore drift still exists; re-observation can correct alignment later.

On stale poses, tracking loss, pocketing, session reset or headset recenter,
invalidate or revalidate the alignment and hide an untrustworthy surface.
Resume with explicit reacquisition rather than integrating accelerometers into
an indefinitely drifting position estimate. A covered rear camera or another
camera app can interrupt phone visual tracking.

## Screen streaming

Validate a maintained WebRTC implementation for Android capture/encoding and
ARM64 Linux reception/decoding before selecting package versions. Authenticate
its signaling and peer fingerprints through the established session. A local
LAN session should not require a cloud signaling service. Use existing video
congestion control, encryption and recovery rather than inventing those layers.
WebRTC already has an Android
[MediaProjection screen capturer](https://webrtc.googlesource.com/src/+/refs/heads/main/sdk/android/api/org/webrtc/ScreenCapturerAndroid.java).

Decode into a texture for the existing OpenVR quad. Associate video timestamps
with the session clock without making fresh pose delivery wait for a video
frame. Handle display rotation/resizing, capture stop and Wi-Fi interruption.
Keep pose and video status separate: video loss must not masquerade as tracking
loss, and a lost pose must not leave a convincingly misplaced screen visible.

## Implementation order and completion evidence

1. **Prove platform support.** Minimal Frame BLE advertisement/GATT exchange;
   phone companion reconnect with the activity closed; ARCore poses while Home
   and other apps are visible; full-display capture and lock/unlock behavior.
   Record actual device/OS results and latency. Stop dependent work if a required
   platform behavior fails.
2. **Ship Bluetooth pairing and secure Wi-Fi bootstrap.** Width/height setup,
   saved association, authenticated GATT access, pinned LAN reconnect, bounded
   retries and Stop/Forget. Keep the current optical tracking path working.
   Demonstrate reconnection after restarting either app and changing LAN IP.
3. **Add the BLE pose path.** Versioned binary messages, clock synchronization,
   bounded queues, freshness diagnostics and optional raw sensors. Demonstrate
   sustained traffic and measured latency under Wi-Fi load before tuning rates.
4. **Add ARCore and shared-world alignment.** Service-owned lifecycle, tracking
   state, device extrinsics, headset pose history and acknowledged brief marker
   acquisition. Demonstrate simultaneous walking/head movement, marker hiding,
   loss/reacquisition and reset rejection with recorded synchronized evidence.
5. **Stream into the tracked screen.** Hardware encode where available, encrypted
   Wi-Fi video, texture presentation and capture lifecycle. Demonstrate Home,
   app switching, rotation and recovery; measure sustained heat/battery behavior
   and motion-to-display timing with both radios active.
6. **Refine daily use.** Implement the supported unlock/session UI path based on
   the platform tests. Reduce routine interaction without claiming permissions
   or background behavior the OS does not provide.

Keep connection/session control separate from pose production and video, using
small explicit interfaces in the existing apps. Preserve the standalone camera
module. No general plugin framework, external tracker, cloud map service or
second experimental vision pipeline is needed for this direction.
