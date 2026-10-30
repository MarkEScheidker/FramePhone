# FramePhone

An experimental Android companion for Valve Steam Frame. The phone shows one
screen-width AprilTag overlay when alignment is needed and sends motion telemetry
over pinned Wi-Fi TLS. Bluetooth handles pairing and automatic connection setup.
Frame's two front cameras estimate the marker's position and rotation using
factory fisheye calibration. An automatic SteamVR display follows the tracked
screen as a flat rectangle.

**Early development:** pairing and live stereo pose tracking work on the owner's
devices, with stable distance and orientation readings. Both optical and ARCore-driven VR rectangles have
been demonstrated on the headset. Distance scale uses Android's reported
display DPI; metric accuracy and motion timing still need independent validation.
The automatic brief-marker ARCore handoff now includes bounded motion prediction;
its origin calibration and exposure timing are provisional. Bluetooth companion
wake and trust/LAN bootstrap are implemented for device
testing. Screen streaming is the next milestone.

## Build and run

From the repository root on Linux desktop or directly on Steam Frame:

```bash
bash frame/build.sh
```

Open **`frame/build/dist/FramePhone-arm64.run`** on Frame after enabling execution
in file Properties. Runtime libraries, desktop controls and the camera broker are
bundled. Docker/Podman is required only for building; Frametop is not required.
The app uses the headset's installed SteamVR for its automatic VR display.

1. Enable Bluetooth and Wi-Fi on both devices; launch FramePhone on Frame first.
   Bluetooth advertising starts automatically; camera processing waits for the
   phone marker. Approve desktop camera authorization if prompted.
2. On Android enter width and height and tap **Pair headset**. Grant Bluetooth,
   notification, camera and overlay access. Select **Steam Frame** in Android's
   companion picker and accept Android's Pair prompt if shown. Bluetooth bonding
   uses no verification code. After bonding, compare the hash shown in both apps
   and select **Hashes match on both devices**. App keys and the Wi-Fi route then
   travel through TLS over Bluetooth; Frame connects automatically. Use **Forget**
   in either app to require a fresh hash exchange, keeping the OS bond if desired.
3. Briefly show the automatic marker to the front cameras. After alignment the
   marker hides and ARCore drives the VR rectangle. Live poses, IMU telemetry,
   clock synchronization and tracking commands use Wi-Fi.
4. Subsequent headset advertisements can wake Android's connection service
   without opening setup. If Android requires user action to restart its camera,
   tap **Resume tracking** in the notification. **Disconnect** disables automatic
   phone reconnection until Connect is used again.

See [Bluetooth setup and limits](frame/docs/BLUETOOTH.md), including migration
of existing Wi-Fi pairings. Bluetooth is the only pairing path; Wi-Fi connects
and retries automatically, including on phone screen-on/unlock if disconnected.
Actual radio latency and cold background behavior require device testing;
smoothing delay is separate.

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
sudo apt-get install build-essential cmake python3 python3-dbus-next libapriltag-dev libopencv-dev nlohmann-json3-dev
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
- [Tracking research and decisions](frame/docs/TRACKING_RESEARCH.md)
- [Bluetooth companion and poses](frame/docs/BLUETOOTH.md)
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
