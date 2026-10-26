# Android companion

Enter the phone's width and height, then tap **Connect**. After the headset
connects, a screen-width AprilTag appears over the current app. Frame accepts a
stable pose, confirms that its VR rectangle is visible, and dismisses the marker.
ARCore then supplies anchored motion over the existing secure LAN connection.

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

## Connect

1. Put the phone and headset on the same LAN. Enter outside phone/case width and
   height in millimeters and tap **Connect**.
2. Grant camera, notification and **display over other apps** access. Install or
   update Google Play Services for AR when prompted. These are setup steps;
   normal connections do not need a separate ARCore or marker button.
3. Launch FramePhone on the headset. Saved pairing reconnects automatically.
   For a new pairing, use **Connection → Pair new phone** on Frame and confirm
   matching codes on both devices.
4. Keep the phone's position relative to the headset within 2 cm for 500 ms,
   with the marker visible in both front cameras. Moving both devices together
   is allowed. The overlay disappears only after a successful visible VR handoff.

Keep the rear camera uncovered while tracking. **Disconnect** stops networking,
tracking and the overlay. The notification provides **Retry** and **Disconnect**;
**Details** contains network diagnostics and pairing management. If alignment
cannot complete within 20 seconds, the overlay closes and **Retry tracking** is
available. A timeout does not accept a pose.

Width/height preferences and existing pairing survive this update; obsolete
saved thickness is discarded when dimensions are saved. Rebuild both apps:
older headset versions do not support automatic marker sessions.

Gyro/accelerometer and magnetometer diagnostics remain available. Screen capture,
Bluetooth transport and remote input are not implemented. See
[handoff behavior and limits](../frame/docs/ARCORE_HANDOFF.md) and
[the LAN protocol](../frame/docs/PAIRING_AND_IMU.md).

The camera session requests 60 FPS where supported. Verified Camera2 exposure
metadata lets the headset use recent gyro data between ARCore frames; unknown
camera clocks disable gyro prediction. Actual rates depend on hardware/lighting.
