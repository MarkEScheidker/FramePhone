# FramePhone

An experimental Android companion for Valve Steam Frame. The phone pairs over
the LAN, sends motion sensors and displays a user-selected photo. Frame downloads
that photo once and matches it in its two front cameras to estimate head-relative
position, orientation and distance using calibrated fisheye stereo geometry.

**Early development:** camera previews, pairing and telemetry have been observed
on the owner's hardware. The new photo tracker passes synthetic/replay tests;
real-photo accuracy, camera mapping and sustained headset performance still need
validation. There is no screen streaming, ARCore integration or world-space overlay yet.

## Build and run

From the repository root on Linux desktop or directly on Steam Frame:

```bash
bash frame/build.sh
```

Open **`frame/build/dist/FramePhone-arm64.run`** on the headset after enabling
execution in file Properties. Libraries, the photo decoder and camera broker are
bundled. Docker/Podman is needed only to build. No Frametop install is required.
The static-photo test also bundles pretrained XFeat/LighterGlue and a CPU
inference runtime. These are fetched during the build; no runtime model download
is needed.

Build/install the updated Android app from `phone/`. Enter phone/case dimensions,
start the connection, then pair in **Phone telemetry**. Tap **Choose tracking photo**
on Android; it opens full-screen. On Frame, use **Photo tracking → Use phone photo →
Enable cameras → Refresh cameras → Start photo tracking**. No manual corners or
target-size entry.
Keep **Learned (XFeat/LighterGlue)** selected for the new experiment; **RootSIFT
baseline** is available for comparison. Hold the photo still while the calibrated
search views cycle. Camera setup also has a **Model check** independent of the
geometry self-test. The existing Android photo app needs no changes for this test.

Metric scale comes from the factory stereo baseline rather than display DPI.
Poses refer to the displayed photo center. See
[headset testing](frame/docs/HEADSET_TEST.md) and [photo tracking](frame/docs/PHOTO_TRACKING.md).
The earlier marker implementation remains in source/tests while the replacement
undergoes headset validation; the normal UI uses photo tracking.

## Development

Android Studio: open `phone/`, or use JDK 17 and Android SDK 36:

```bash
cd phone
bash gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

Windows uses `gradlew.bat`. Native Linux:

```bash
sudo apt-get install build-essential cmake python3 libapriltag-dev libopencv-dev nlohmann-json3-dev
cmake -S frame -B frame/build/desktop -DCMAKE_BUILD_TYPE=Release
cmake --build frame/build/desktop --parallel 4
ctest --test-dir frame/build/desktop --output-on-failure
frame/build/desktop/framephone-photo --self-test
```

## Documentation

- [Android companion](phone/README.md)
- [Build](frame/docs/BUILD.md) and [development](docs/DEVELOPMENT.md)
- [Marker tracking and replay](frame/docs/FIDUCIAL_TRACKING.md)
- [Photo tracking and replay](frame/docs/PHOTO_TRACKING.md)
- [Screen capture constraints](frame/docs/SCREEN_CAPTURE.md)
- [Pairing and telemetry](frame/docs/PAIRING_AND_IMU.md)
- [Architecture](frame/docs/ARCHITECTURE.md), [coordinates](frame/docs/COORDINATE_SYSTEMS.md)
- [Calibration](frame/docs/CALIBRATION.md), [validation](frame/docs/TRACKING_VALIDATION.md)
- [Roadmap](docs/ROADMAP.md) and [contributing](CONTRIBUTING.md)

## License

Original code is [MIT licensed](LICENSE). AprilTag and adapted Frametop code
retain their notices; see [third-party notices](THIRD_PARTY_NOTICES.md).
FramePhone is independent of Valve.
