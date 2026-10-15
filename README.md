# FramePhone

An experimental phone companion for Valve Steam Frame. The Android app pairs
over the LAN and sends measured phone dimensions and live motion sensors to the
Frame desktop app. The optical diagnostic estimates a phone-body pose from
labelled stereo corners, then tracks its visible front outline.

**Early development:** pairing and live telemetry have been confirmed on the
owner's phone and Steam Frame. Markerless accuracy, front-camera calibration
mapping, tracking range and sustained performance still need hardware validation.
There is no tracked VR display, screen streaming or inertial pose fusion yet.

## Build and run

From the repository root on Linux desktop or directly on the headset:

```bash
bash frame/build.sh
```

This produces **`frame/build/dist/FramePhone-arm64.run`**. Copy that single file
to the headset, allow execution in file Properties, and open it. Runtime
libraries and the camera broker are bundled. Docker/Podman is only needed on the
build machine; no Frametop installation is required.

On the Android app, enter the outside phone/case width, height and thickness,
then start pairing. In **Phone telemetry**, choose **Find phones → Pair new phone**,
compare the fingerprint and approve on both devices. Later use **Connect saved phone**.

For optical testing: **Markerless tracking → Enable cameras → Capture pair →
label four physical front corners in each view → Estimate pose → Track outline**.
This manually initialized baseline needs a clear front outline in both cameras
and stops on loss. **Camera setup** provides the two front previews, native-size
views, a geometry self-test and the integrated log.

See the [headset guide](frame/docs/HEADSET_TEST.md) and
[markerless diagnostic guide](frame/docs/MARKERLESS_DIAGNOSTIC.md).

## Development

Open `phone/` in Android Studio with JDK 17 and Android SDK 36, or run:

```bash
cd phone
bash gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

Use `gradlew.bat` on Windows. For a native Linux development build:

```bash
sudo apt-get install build-essential cmake python3 libopencv-dev nlohmann-json3-dev
cmake -S frame -B frame/build/desktop -DCMAKE_BUILD_TYPE=Release
cmake --build frame/build/desktop --parallel 4
ctest --test-dir frame/build/desktop --output-on-failure
frame/build/desktop/framephone-markerless --self-test
```

OpenCV core/calib3d/imgproc and nlohmann JSON are required. Python/Tk powers the
desktop interface. Synthetic tests exercise software, not real-world accuracy.

## Documentation

- [Android companion](phone/README.md)
- [Build setup](frame/docs/BUILD.md) and [development](docs/DEVELOPMENT.md)
- [Markerless usage and replay](frame/docs/MARKERLESS_DIAGNOSTIC.md)
- [Markerless research and next stages](frame/docs/MARKERLESS_TRACKING.md)
- [Pairing and sensor protocol](frame/docs/PAIRING_AND_IMU.md)
- [Architecture](frame/docs/ARCHITECTURE.md) and [coordinates](frame/docs/COORDINATE_SYSTEMS.md)
- [Calibration](frame/docs/CALIBRATION.md) and [validation](frame/docs/TRACKING_VALIDATION.md)
- [Roadmap](docs/ROADMAP.md) and [contributing](CONTRIBUTING.md)

## License and acknowledgments

Original code is [MIT licensed](LICENSE). Adapted Frametop camera/calibration code
retains its notices; see [third-party notices](THIRD_PARTY_NOTICES.md).
FramePhone is an independent project and is not affiliated with Valve.
