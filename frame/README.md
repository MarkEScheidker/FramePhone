# Native tracker

C++20/Linux tools for detecting the phone's AprilTag markers and estimating its
pose. The Android companion is a separate project under [phone/](../phone/).
Software tests exercise synthetic and recorded inputs; Steam Frame camera
compatibility and tracking accuracy remain unverified on hardware.

## Executables

| Target | Purpose | Entry point |
| --- | --- | --- |
| `framephone-stereo` | Two-camera head-relative pose, Frametop factory calibration, logs and paired recording/replay | `src/stereo_main.cpp` |
| `framephone-diagnostic` | Single-camera detection/pose and optional SDL desktop preview; also works headlessly | `src/diagnostic_main.cpp` |
| `framephone-frame` | Small synthetic recording/replay utility; optional real detection | `src/tracker_main.cpp` |
| `framephone-openvr-demo` | Optional simulated phone-outline overlay; does not consume tracking results | `src/main.cpp` |

The stereo target is the headset tracking experiment. It emits T_HP, mapping
phone meters into head axes right/up/back. It does not supply a world pose or
render the tracked phone in VR.

## Build and run

Install the dependencies in [DEVELOPMENT.md](../docs/DEVELOPMENT.md), then run
from the repository root:

```bash
cmake -S frame -B frame/build/desktop -DCMAKE_BUILD_TYPE=Release -DFRAMEPHONE_REQUIRE_TRACKER=ON
cmake --build frame/build/desktop --parallel 4
ctest --test-dir frame/build/desktop --output-on-failure
frame/build/desktop/framephone-diagnostic --headless --frames 120 --blank-every 30
frame/build/desktop/framephone-stereo --help
```

The full tracker needs AprilTag 3, OpenCV 4 and nlohmann JSON. Tests also use
OpenCV imgproc and Python 3. SDL2 enables the diagnostic window; omit it with
`-DFRAMEPHONE_ENABLE_SDL2=OFF`. No dependencies are bundled with the source.

A portable frame/replay subset can be built with `make -C frame test all`.
It does not include real detection or pose estimation. The convenience launcher
`bash frame/run-diagnostic.sh --headless --frames 120` builds and runs the
diagnostic using installed libraries or optional ignored local SDK caches.

For a real headset trial, use [HEADSET_TEST.md](docs/HEADSET_TEST.md).
`bash frame/build-headset.sh` builds in an ARM64 Linux container; the camera
broker runs separately on the host. `bash frame/package-headset.sh` creates a
native source handoff. `build.sh` is only for the optional OpenVR renderer demo.

## Pipeline and contracts

- [Architecture](docs/ARCHITECTURE.md) and [coordinates](docs/COORDINATE_SYSTEMS.md)
- [Phone layout](protocol/README.md) and [camera calibration](protocol/camera-calibration.md)
- [Desktop diagnostic](docs/DIAGNOSTIC.md), [ring input](docs/LIVE_CAMERA.md) and [recordings](docs/RECORDINGS.md)
- [Single-camera pose](docs/POSE.md) and [stereo estimation](docs/STEREO.md)
- [Calibration](docs/CALIBRATION.md) and [validation](docs/TRACKING_VALIDATION.md)
- [Frametop integration](docs/STEAM_FRAME_INTEGRATION.md) and [third-party notices](THIRD_PARTY_NOTICES.md)

Fresh frame pairs, explicit camera mappings and matching calibration/layout
revisions are required. Factory import is labelled `factory_imported`, not
hardware verified. A low reprojection error does not guarantee metric accuracy.
See the project [roadmap](../docs/ROADMAP.md) for world tracking, headset motion
compensation, filtering and visualization work.
