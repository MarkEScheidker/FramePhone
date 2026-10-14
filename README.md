# FramePhone

An experimental phone companion for Valve Steam Frame. The Android app pairs
over the LAN and sends measured phone dimensions and live motion sensors to the
Frame desktop app. Camera diagnostics and the earlier native fiducial tracker
remain available while markerless tracking is developed.

**Early development:** pairing and telemetry have software tests; the new
phone-to-headset connection still needs hardware validation.
The owner has run the desktop app and observed up to six fiducials updating
live on a Steam Frame. Front-camera mapping, detection range and tracking
accuracy still need hardware validation.
There is no tracked VR display or screen streaming yet.

## What is here

| Component | Current capability |
| --- | --- |
| [Android companion](phone/) | Manual phone-body dimensions, TLS pairing and gyro/accelerometer/magnetometer streaming. Android 12+. |
| [Native tracker](frame/) | AprilTag detection, calibrated single-camera and stereo phone poses, desktop diagnostics, recording and replay. Linux, C++20. |
| [Steam Frame integration](frame/docs/HEADSET_TEST.md) | Phone pairing and live telemetry, plus separate camera/legacy tracking diagnostics. Shared Linux desktop/headset build procedure. |

The desktop app reports **head-relative** poses and bundles its own camera
broker, adapted from Frametop. No Frametop installation is needed. Camera access
uses internal headset interfaces and a desktop authorization prompt. The Android
app transmits sensor observations only after pairing. The current Android app
has no fiducial overlay or layout export; old exports and native synthetic
fixtures remain usable with the legacy diagnostics. No fused pose is produced
from the new telemetry yet.

## Start here

### Android companion

Open `phone/` in Android Studio. Use JDK 17 and Android SDK 36, then build:

```bash
cd phone
bash gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

On Windows, use `gradlew.bat`. See the [phone guide](phone/README.md) for
dimension entry, pairing and live sensor streaming.

### Native desktop diagnostic

On Ubuntu 24.04, install the development dependencies and build from the
repository root:

```bash
sudo apt-get install build-essential cmake python3 libapriltag-dev libopencv-dev nlohmann-json3-dev libsdl2-dev
cmake -S frame -B frame/build/desktop -DCMAKE_BUILD_TYPE=Release -DFRAMEPHONE_REQUIRE_TRACKER=ON
cmake --build frame/build/desktop --parallel 4
ctest --test-dir frame/build/desktop --output-on-failure
frame/build/desktop/framephone-diagnostic --headless --frames 120 --blank-every 30
```

Remove `--headless` to open the preview. Synthetic input exercises the pipeline;
it does not establish real-world tracking accuracy. Dependencies are installed
separately and are not bundled with the source.

For the Steam Frame, follow the [headset build and test guide](frame/docs/HEADSET_TEST.md).
**`bash frame/build.sh`** produces **`frame/build/dist/FramePhone-arm64.run`**
on a Linux PC or directly on the headset. Copy this single executable to the
headset, allow execution in file Properties, and open it. On the default
**Phone telemetry** tab, choose **Find phones → Pair new phone**, compare the
fingerprint on both devices and approve both. No cameras or JSON files are
needed for telemetry. Later use **Connect saved phone**.

The **Camera / legacy tracking diagnostics** tab retains self-test, front views,
marker counts and tracking controls. Legacy stereo pose tracking requires an
old measured marker layout and matching physical markers.
The tracking visualizer plots raw marker outlines and a calibrated, head-relative
3D phone view. Front-camera defaults use the owner's video3/video0 pair with
`slam_left`/`slam_right`; the factory pairing remains provisional and editable.
Runtime libraries and the camera broker are bundled; the headset does not need
Docker or Frametop. See the [build guide](frame/docs/BUILD.md) for build-machine setup.

## Documentation

- [Development and build options](docs/DEVELOPMENT.md)
- [Pairing and sensor protocol](frame/docs/PAIRING_AND_IMU.md)
- [Architecture](frame/docs/ARCHITECTURE.md) and [coordinate conventions](frame/docs/COORDINATE_SYSTEMS.md)
- [Phone layout protocol](frame/protocol/README.md), [calibration](frame/docs/CALIBRATION.md) and [stereo estimation](frame/docs/STEREO.md)
- [Tests and hardware validation](frame/docs/TRACKING_VALIDATION.md)
- [Roadmap](docs/ROADMAP.md) and [contributing](CONTRIBUTING.md)

## License and acknowledgments

Original FramePhone code is available under the [MIT license](LICENSE).
AprilTag family data and adapted Frametop code retain their own notices;
see [third-party notices](THIRD_PARTY_NOTICES.md). Thanks to the AprilRobotics
and Frametop projects for the detection and camera/calibration foundations.

FramePhone is an independent project and is not affiliated with Valve.
