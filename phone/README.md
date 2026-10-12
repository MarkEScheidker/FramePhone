# Android companion

The FramePhone companion displays tag36h11 fiducials and exports their measured
phone-frame geometry for the native tracker. It requires Android 12+ and uses
application ID `com.example.framephone`. It has no network, screen streaming,
remote input or live IMU integration.

## Build

Open this directory in Android Studio with JDK 17 and Android SDK 36, or run:

```bash
cd phone
bash gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

From a Windows terminal inside `phone/`, use `gradlew.bat` instead. The debug APK
is `app/build/outputs/apk/debug/app-debug.apk`. SDK paths belong in the ignored
`local.properties`; no developer-specific path is required by the source.
See [development notes](../docs/DEVELOPMENT.md) for platform troubleshooting.

## Calibrate and display tags

1. Measure the active display's portrait width and height with a physical ruler,
   excluding the bezel, and save both dimensions in the app.
2. With markers disabled, open the high-contrast calibration ruler. Check both
   50 mm axes against the physical ruler and correct the entered dimensions.
3. Grant **Display over other apps**, return to FramePhone and enable markers.
   Stop using the app control or the foreground notification.
4. Confirm complete quiet zones and clearance from rounded corners/cutouts.
   Export JSON once diagnostics report measured marker windows.
5. Keep the phone configuration fixed during a tracking trial. Export again
   after changing rotation, layout, size or placement.

The default four-corner layout uses IDs 0–3. Other choices are two diagonal
corners (0, 2), four edge centers (0–3), and six markers (0–5). The marker size
excludes the white quiet zone; the complete footprint is 25% larger. Quantized,
measured exported corners are authoritative. Layouts that clip or overlap are
rejected with diagnostics rather than silently resized.

Markers remain anchored in the canonical phone frame during display rotation.
During rotation the service temporarily hides/repositions them and shows a
200 ms white interval before restoring tag patterns. Export readiness waits for
measured drawing. This behavior still needs broader device testing.

## Limits

Marker regions can block touches; the rest of the display has no overlay window.
Protected apps may hide overlays. The foreground service stops on explicit
Disable, lock/display-off, or process death; it does not restart at boot.
Calibration is based on manual measurements, not reported Android DPI.

The [phone-layout protocol](../frame/protocol/README.md) defines exported units,
frames and corner order. The [calibration guide](../frame/docs/CALIBRATION.md)
and [validation guide](../frame/docs/TRACKING_VALIDATION.md) cover hardware checks.
AprilTag family attribution is retained in [APRILTAG_LICENSE.txt](app/src/main/assets/APRILTAG_LICENSE.txt).
