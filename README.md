# FramePhone

An experimental Android companion for Valve Steam Frame. The phone shows one
screen-width AprilTag overlay when alignment is needed and sends motion telemetry
over a paired LAN connection.
Frame's two front cameras estimate the marker's position and rotation using
factory fisheye calibration. An optional SteamVR display follows the tracked
screen as a flat rectangle.

**Early development:** pairing and live stereo pose tracking work on the owner's
devices, with stable distance and orientation readings. Both optical and ARCore-driven VR rectangles have
been demonstrated on the headset. Distance scale uses Android's reported
display DPI; metric accuracy and motion timing still need independent validation.
The automatic brief-marker ARCore handoff now includes bounded motion prediction;
its origin calibration and exposure timing are provisional. Bluetooth and screen
streaming are future work.

## Build and run

From the repository root on Linux desktop or directly on Steam Frame:

```bash
bash frame/build.sh
```

Open **`frame/build/dist/FramePhone-arm64.run`** on Frame after enabling execution
in file Properties. Runtime libraries, desktop controls and the camera broker are
bundled. Docker/Podman is required only for building; Frametop is not required.
The app uses the headset's installed SteamVR for its automatic VR display.

1. Enter width and height on Android and tap **Connect**. Grant camera and
   **display over other apps** access; install ARCore if requested.
2. Launch FramePhone on the headset. Cameras start automatically (approve
   desktop authorization if prompted), and the saved phone reconnects. For first
   pairing, expand **Connection**, select the phone and choose **Pair new phone**.
   Compare and approve matching codes on both devices.
3. The marker overlay and headset tracking start automatically. Keep the phone
   within 2 cm of its headset-relative position for 500 ms. When the VR rectangle
   is visible and alignment is accepted, the marker disappears and ARCore takes
   over. Recovery displays the overlay again. **Disconnect** stops the session.

No photo selection, manual corners or marker-size adjustment is required. The
white quiet border is part of the width-filling marker; the black square itself
occupies roughly 80% of screen width. Output refers to that square's center,
not an independently calibrated phone-body origin. See
[headset testing](frame/docs/HEADSET_TEST.md) and
[single-marker tracking](frame/docs/FIDUCIAL_TRACKING.md).

## Development

Open `phone/` in Android Studio, or use JDK 17 and Android SDK 36:

```bash
cd phone
bash gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

Windows uses `gradlew.bat`. For a native Linux development build:

```bash
sudo apt-get install build-essential cmake python3 libapriltag-dev libopencv-dev nlohmann-json3-dev
cmake -S frame -B frame/build/desktop -DCMAKE_BUILD_TYPE=Release
cmake --build frame/build/desktop --parallel 4
ctest --test-dir frame/build/desktop --output-on-failure
```

The obsolete photo/rectangle/neural tracking experiments and their model downloads
have been removed. The supported build and UI use the same single-marker path.

## Documentation

- [Android companion](phone/README.md)
- [Build](frame/docs/BUILD.md) and [development](docs/DEVELOPMENT.md)
- [Tracking and replay](frame/docs/FIDUCIAL_TRACKING.md)
- [VR test display](frame/docs/VR_DISPLAY.md)
- [Brief-marker ARCore test](frame/docs/ARCORE_HANDOFF.md)
- [Pairing and telemetry](frame/docs/PAIRING_AND_IMU.md)
- [Architecture](frame/docs/ARCHITECTURE.md), [coordinates](frame/docs/COORDINATE_SYSTEMS.md)
- [Calibration](frame/docs/CALIBRATION.md), [validation](frame/docs/TRACKING_VALIDATION.md)
- [Roadmap](docs/ROADMAP.md) and [contributing](CONTRIBUTING.md)

## License

Original code is [MIT licensed](LICENSE). Third-party code retains its notices;
see [third-party notices](THIRD_PARTY_NOTICES.md). FramePhone is independent of Valve.


## Reuse and contribute

The [component guide](docs/REUSING.md) maps the repository and its dependency
boundaries. The [camera module](frame/modules/camera/) can be copied into another
Linux CMake project without the rest of FramePhone, including its tests,
example, broker and license notices. Tracking, pairing and rendering are separate
layers; only the camera component is packaged independently today.

See [contributing](CONTRIBUTING.md) for local tests and review expectations.
