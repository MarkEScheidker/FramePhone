# Frame desktop app and native tools

The desktop app provides paired phone telemetry, markerless optical trials and
front-camera setup. Native C++20 code owns calibrated geometry and outline tracking;
Python OpenCV DNN runs the bundled pretrained phone detector.

| Target | Purpose |
| --- | --- |
| `FramePhone-*.run` | Single desktop executable with bundled runtime and camera broker. |
| `framephone-markerless` | Capture, labelled body-pose solve, local outline tracking, replay and geometry self-test. |
| `framephone-camera` | Discover camera-ring streams and factory calibrations. |
| `framephone-openvr-demo` | Optional simulated screen-outline renderer; does not consume tracking results. |

The estimator returns **T_HB**, mapping body-center meters into head axes
right/up/back. It does not yet provide world-space pose or fused IMU output.

Use **`bash frame/build.sh`** on Linux desktop or headset to produce the ARM64
package. See [BUILD.md](docs/BUILD.md). For development, install OpenCV
core/calib3d/imgproc and nlohmann JSON, then:

```bash
cmake -S frame -B frame/build/desktop -DCMAKE_BUILD_TYPE=Release
cmake --build frame/build/desktop --parallel 4
ctest --test-dir frame/build/desktop --output-on-failure
frame/build/desktop/framephone-markerless --self-test
```

`make -C frame test` runs the dependency-free recording/ring tests only.
`build-openvr-demo.sh` builds the optional renderer separately.

- [Markerless workflow and replay](docs/MARKERLESS_DIAGNOSTIC.md)
- [Automatic pretrained phone detection](docs/AUTO_DETECTION.md)
- [Headset testing](docs/HEADSET_TEST.md)
- [Architecture](docs/ARCHITECTURE.md) and [coordinates](docs/COORDINATE_SYSTEMS.md)
- [Ring input](docs/LIVE_CAMERA.md) and [recordings](docs/RECORDINGS.md)
- [Calibration](docs/CALIBRATION.md) and [validation](docs/TRACKING_VALIDATION.md)
- [Frametop provenance](third_party/frametop/README.md) and [notices](THIRD_PARTY_NOTICES.md)

Factory calibration is labelled `factory_imported`, not hardware verified.
A low reprojection error alone does not establish metric accuracy.
