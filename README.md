# FramePhone

An experimental phone tracker for Valve Steam Frame. An Android companion
displays AprilTag fiducials; a native C++ application estimates the phone's
position and rotation from calibrated headset camera images.

**Early development:** the phone companion and native software tests work.
The owner has run the desktop app and observed up to six fiducials updating
live on a Steam Frame. Front-camera mapping, detection range and tracking
accuracy still need hardware validation.
There is no tracked VR display or screen streaming yet.

## What is here

| Component | Current capability |
| --- | --- |
| [Android companion](phone/) | Configurable tag36h11 overlays, measured display calibration and phone geometry export. Android 12+. |
| [Native tracker](frame/) | AprilTag detection, calibrated single-camera and stereo phone poses, desktop diagnostics, recording and replay. Linux, C++20. |
| [Steam Frame integration](frame/docs/HEADSET_TEST.md) | Front-camera previews and live marker counts, factory KB4 calibration and a shared Linux desktop/headset build procedure. Experimental; tracking accuracy unverified. |

The desktop app reports **head-relative** poses and bundles its own camera
broker, adapted from Frametop. No Frametop installation is needed. Camera access
uses internal headset interfaces and a desktop authorization prompt. The Android
app does not transmit data.

## Start here

### Android companion

Open `phone/` in Android Studio. Use JDK 17 and Android SDK 36, then build:

```bash
cd phone
bash gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

On Windows, use `gradlew.bat`. See the [phone guide](phone/README.md) for
calibration, overlay permissions and exporting the measured marker layout.

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
headset, allow execution in file Properties, and open it. The window provides
self-test, a toggle for the two front camera views, live marker counts and IDs,
phone layout selection and tracking controls. Marker detection needs no layout;
stereo pose tracking requires the measured phone layout.
The tracking visualizer plots raw marker outlines and a calibrated, head-relative
3D phone view. Front-camera defaults use the owner's video3/video0 pair with
`slam_left`/`slam_right`; the factory pairing remains provisional and editable.
Runtime libraries and the camera broker are bundled; the headset does not need
Docker or Frametop. See the [build guide](frame/docs/BUILD.md) for build-machine setup.

## Documentation

- [Development and build options](docs/DEVELOPMENT.md)
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
