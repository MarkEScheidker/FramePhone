# Companion sessions

## Current implementation

Frame advertises a custom BLE service through the host BlueZ daemon while the
app runs. Android uses the system companion-device picker, an authenticated
Bluetooth bond and presence observation. The phone is the GATT client; Frame is
the peripheral. See the [Bluetooth contract](../frame/docs/BLUETOOTH.md) for setup,
wire format, trust rules and platform limitations.

First setup collects phone width/height and the required permissions. Bluetooth
carries the application credential, public certificate pin and current LAN route.
Existing Wi-Fi pairings prove their saved verifier instead of enrolling again.
Private certificate keys stay on their originating device. Both devices must
already share a reachable LAN; no Wi-Fi passwords or hotspot provisioning are
involved.

After setup, companion presence can wake the phone connection service without
opening its setup activity. The Frame client verifies the saved certificate pin
before sending its reconnect credential over TLS. A fresh Bluetooth binding is
linked to that authenticated TLS session before poses are accepted. Disconnect
on Android disables automatic wake; Forget also removes the app association.
The OS Bluetooth bond is managed separately in system settings.

ARCore poses and bounded corrected gyro history use latest-only BLE writes.
Pinned Wi-Fi TLS retains reliable session/marker/wearer control, clock mapping,
raw sensor diagnostics and backup poses. Explicit Wi-Fi-only controls remain for
device troubleshooting. Changing the radio does not remove smoothing latency or
establish that BLE is faster; measure both paths on the actual devices.

Android can restrict camera access from a cold background process even when it
permits companion networking. Resume the existing camera service when possible;
otherwise provide a Resume tracking notification action. Force-stop and system
permission restrictions are not bypassed. See [Android background BLE guidance](https://developer.android.com/develop/connectivity/bluetooth/ble/background)
and [foreground/camera restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start).

## Tracking and coordinates

The service-owned ARCore session and automatic marker overlay are implemented.
Two accepted stereo observations spanning at least 80 ms can establish alignment,
with up to 8 cm of relative movement. The marker hides only after Frame confirms
a visible VR handoff. Screen lock, tracking resets, deliberate user dismissal and
headset wearer state govern pause and reacquisition.

ARCore and SteamVR keep independent worlds. Registration relates them using
optical observations, clock mapping and headset pose history; sharing internal
room maps is unnecessary. The renderer composes the anchored phone pose into
headset world coordinates. Metric scale, camera-to-screen extrinsics and the
factory-head-to-runtime-head transform remain provisional. Long-term drift,
recenter and pocket relocalization still need device validation. See the
[handoff contract](../frame/docs/ARCORE_HANDOFF.md).

## Next: screen streaming

Validate a maintained WebRTC stack for Android capture/hardware encoding and
ARM64 Linux reception/decoding. Authenticate signaling and peer fingerprints
through the established session; a LAN connection should not need cloud signaling.
Use the existing real-time stack's encryption, congestion control and recovery.
WebRTC provides an Android [MediaProjection screen capturer](https://webrtc.googlesource.com/src/+/refs/heads/main/sdk/android/api/org/webrtc/ScreenCapturerAndroid.java).

Full-display capture should include Home and ordinary app switching. Android
requires consent for each new MediaProjection session, and locking the screen
stops capture; do not promise permanent setup-time approval. See
[MediaProjection](https://developer.android.com/media/grow/media-projection).

Decode into a texture on the existing VR surface. Keep video timestamps tied to
the session clock without making pose delivery wait for video. Handle rotation,
resize, capture stop and Wi-Fi loss independently from tracking state.

## Device validation before expanding scope

1. Verify Frame advertising/GATT permissions and authenticated bonding on real
   hardware, then migration, application restarts and changed Wi-Fi addresses.
2. Test companion wake with the activity closed, cold process/camera recovery,
   Home, screen-off/unlock, Stop, Forget and force-stop.
3. Measure p50/p95/p99 pose age, loss, jitter, reconnect time, CPU/battery and
   motion-to-display delay against Wi-Fi before changing smoothing again.
4. Validate screen capture/encoding/decoding, user consent and both radios under
   video load before adding further interaction features.

Software wire, TLS, private D-Bus and GUI tests do not establish radio behavior,
background lifecycle reliability, physical accuracy or end-to-end latency.
