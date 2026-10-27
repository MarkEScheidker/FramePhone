# Android companion

Enter the phone's width and height, then tap **Pair headset**. After the headset
connects and is worn, a screen-width AprilTag appears over the current app. Frame accepts a
stable pose, confirms that its VR rectangle is visible, and dismisses the marker.
ARCore then supplies anchored motion over BLE, with pinned Wi-Fi control and fallback.

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

Run FramePhone on Frame with Bluetooth enabled before tapping Pair headset on Android.
After the initial permissions, select FramePhone in the system companion picker
and approve the Bluetooth bond on both devices. Trust and the Wi-Fi endpoint
travel over authenticated BLE. Existing Wi-Fi pairings migrate using their verifier;
a new pair no longer needs a separate LAN fingerprint enrollment.

The associated Frame can wake the connection service with setup closed. Android
may still require the Resume tracking notification action for a cold camera
start. Disconnect disables automatic wake until Connect is used again; Forget
also removes the companion association. Force-stop is not bypassed.

Bluetooth is the only pairing method. Wi-Fi connects and retries automatically;
screen-on/unlock requests another attempt while disconnected. Both devices must
already share a reachable Wi-Fi network. No manual IP or transport selection is
needed. [Bluetooth setup and validation](../frame/docs/BLUETOOTH.md) covers the
protocol, permissions and platform limitations. Rebuild both apps.

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
