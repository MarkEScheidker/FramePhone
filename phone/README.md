# Android companion

Enter the phone's width and height, then tap **Pair headset**. After the headset
connects and is worn, a screen-width AprilTag appears over the current app. Frame accepts a
stable pose, confirms that its VR rectangle is visible, and dismisses the marker.
ARCore then supplies anchored motion over pinned Wi-Fi TLS. Bluetooth handles
pairing and automatic connection setup.

Tracking recovery shows the overlay again automatically; screen-off recreates
the paused anchor on resume without requiring a network reconnect. The setup activity can
stay closed. This is a prototype: sleep recovery, metric calibration
and motion timing still need validation on the actual devices.

## Build

Use Android Studio with JDK 17 and Android SDK 36, or run:

```bash
cd phone
bash gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

Windows uses `gradlew.bat`. Install `app/build/outputs/apk/debug/app-debug.apk`.
Android 12+; application ID `com.example.framephone`. See
[development notes](../docs/DEVELOPMENT.md).

## Bluetooth connection

Run FramePhone on Frame, then tap Pair headset on Android and select Steam Frame.
Bluetooth uses no-code Just Works bonding; Android may still ask for Pair consent.
After bonding, compare the hash displayed in both apps and tap **Hashes match on
both devices**. The application credential and Wi-Fi route are exchanged through
TLS 1.3 over Bluetooth. Future connections use saved trust automatically.

Forget headset is visible outside Details, including after incomplete setup.
Forgetting either app requires a new hash exchange; the OS Bluetooth bond can
remain. Disconnect stops automatic wake; Connect starts a fresh attempt. The
headset accepts a different phone only after Forget phone.

Companion presence can wake the service, but Android may require Resume tracking
for a cold background camera start. Force-stop and camera permissions are not
bypassed. Both devices must already share a reachable Wi-Fi network; no manual IP
or transport selection is needed. Rebuild both apps together for the new protocol.
See [Bluetooth setup and protocol](../frame/docs/BLUETOOTH.md).

## Tracking

Briefly present the marker to both front cameras. Two accepted stereo observations
spanning at least 80 ms can align, allowing up to 8 cm of relative movement.
Startup and processing can add time. The overlay disappears only after a visible
VR handoff. Headset camera interception and detection then sleep until another
marker acquisition is needed.

**Back**, **Home**, opening recent apps or tapping the marker dismisses it and
pauses tracking until the phone screen is turned off and unlocked again. Retry,
reconnecting or an ARCore restart does not override that dismissal. Taking off
the headset hides the marker and pauses ARCore; putting it on permits a new
alignment. Proximity is preferred; if that input is unavailable, Frame uses
SteamVR's active/idle state. This fallback can remain active with movement and
may take time to register removal. Unknown or stale wearer signals keep the
marker hidden.

Keep the rear camera uncovered while tracking. **Disconnect** stops networking,
tracking and the overlay. The notification provides **Retry** and **Disconnect**;
**Details** contains network diagnostics and pairing management. If alignment
cannot complete within 20 seconds, the overlay closes and **Retry tracking** is
available. A timeout does not accept a pose.

Width/height preferences and existing pairing survive this update; obsolete
saved thickness is discarded when dimensions are saved. Rebuild both apps:
older headset versions do not send the wearer heartbeat required by this phone app.

Gyro/accelerometer and magnetometer diagnostics remain available. Screen capture,
remote input and video streaming are not implemented. See
[handoff behavior and limits](../frame/docs/ARCORE_HANDOFF.md) and
[the LAN protocol](../frame/docs/PAIRING_AND_IMU.md).

The camera session requests 60 FPS where supported. Verified Camera2 exposure
metadata lets the headset use recent gyro data between ARCore frames; unknown
camera clocks disable gyro prediction. Actual rates depend on hardware/lighting.
