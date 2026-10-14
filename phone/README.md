# Android companion

FramePhone sends live gyroscope, accelerometer and magnetometer observations to
the Frame desktop app over an authenticated TLS connection. Android 12+;
application ID `com.example.framephone`. The old fiducial overlay, display
calibration and layout-export UI have been removed.

## Build

Open this directory in Android Studio with JDK 17 and Android SDK 36, or run:

```bash
cd phone
bash gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

On Windows use `gradlew.bat`. Install `app/build/outputs/apk/debug/app-debug.apk`.
SDK paths belong in ignored `local.properties`. See [development notes](../docs/DEVELOPMENT.md).

## Pair and stream

1. Put phone and headset on the same LAN.
2. Measure the phone's **outside width, height and thickness**, including its
   case, in portrait. Enter millimeters; these are not active-display dimensions.
3. Tap **Save dimensions and start pairing**. Allow notifications so the Stop
   control is visible while using other apps. Keep this screen open for pairing.
4. On Frame, open **Phone telemetry → Find phones**, select this phone and click
   **Pair new phone**. If discovery fails, type the IP shown on the phone.
5. Compare **all four fingerprint groups** on the two physical screens. Only
   choose **Fingerprints match** on both if they agree. Pairing closes after
   90 seconds; use **Pair new headset** to reopen it.
6. Telemetry starts immediately. The Frame displays dimensions, sensor values,
   received rates, gaps and approximate sample age. Missing sensors are shown
   explicitly; a missing magnetometer does not block the connection.

For subsequent sessions, start the phone connection and choose **Connect saved
phone** on Frame. Find/select it again if its IP changed. Reconnect checks the
full saved certificate fingerprint before transmitting the reconnect credential.
This version remembers one headset; a newly approved pairing replaces it.

The phone checks a real local TLS handshake before opening discovery. If startup
fails, its status shows **Cannot start at TLS self-check** with diagnostic details.
The corrected identity key permits TLS's pre-hashed signing operation. Updating
from the original restricted key replaces that identity and clears the phone's
old pairing once; choose **Pair new phone** on Frame to establish trust again.

**Stop connection** (or the notification's Stop) closes listeners and streams.
**Forget headset and stop** also revokes the saved credential. Stop before editing
dimensions. There is no automatic boot startup or background reconnect loop.
The enabled connection uses a connected-device foreground service, not an overlay.

## Current limits

Pairing uses manual fingerprint comparison, not QR scanning. Discovery is IPv4
UDP broadcast; telemetry uses TLS 1.3/TCP on port 47643. Guest Wi-Fi/client
isolation, firewall rules or future Android local-network permission changes may
block access. Manual IP entry bypasses blocked discovery, not blocked TCP access.

Gyro/accelerometer request 200 Hz; magnetometer requests 50 Hz. Actual rates and
sensor availability depend on the phone. Uncalibrated channels are preferred,
with vendor bias estimates separate; calibrated channels are explicit fallbacks.
Original integer nanosecond timestamps and fixed natural-device axes are retained.
Sampling during lock/sleep and power management still need device validation.

No optical association, pose fusion, QR scanning, screen capture or remote input
is included. See the [implemented LAN protocol](../frame/docs/PAIRING_AND_IMU.md).
