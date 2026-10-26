# Android companion

Enter the phone's width and height, then tap **Connect**. After the headset
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

Run FramePhone on Frame with Bluetooth enabled before tapping Connect on Android.
After the initial permissions, select FramePhone in the system companion picker
and approve the Bluetooth bond on both devices. Trust and the Wi-Fi endpoint
travel over authenticated BLE. Existing Wi-Fi pairings migrate using their verifier;
a new pair no longer needs a separate LAN fingerprint enrollment.

The associated Frame can wake the connection service with setup closed. Android
may still require the Resume tracking notification action for a cold camera
start. Disconnect disables automatic wake until Connect is used again; Forget
also removes the companion association. Force-stop is not bypassed.

Details → Connect using Wi-Fi preserves the previous diagnostic connection path.
[Bluetooth protocol and validation](../frame/docs/BLUETOOTH.md) explains fallback,
permissions and testing. Rebuild both applications for this milestone.

## Wi-Fi-only fallback

1. Put the phone and headset on the same LAN. Enter outside phone/case width and
   height in millimeters, then use **Details → Connect using Wi-Fi**.
2. Grant camera, notification and **display over other apps** access. Install or
   update Google Play Services for AR when prompted. These are setup steps;
   normal connections do not need a separate ARCore or marker button.
3. Launch FramePhone on the headset. Saved pairing reconnects automatically.
   For a new pairing, use **Connection → Pair new phone** on Frame and confirm
   matching codes on both devices.
4. Briefly present the marker to both front cameras. Two accepted stereo
   observations spanning at least 80 ms can align, allowing up to 8 cm of
   relative movement. Startup and processing may add time. The overlay disappears only after a successful visible VR handoff.

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
