# Frame desktop and native tools

The current experiment is [fixed-photo stereo tracking](docs/PHOTO_TRACKING.md).
The next product stage is ARCore motion tracking with incremental registration
from phone-screen content. See the
[component research and implementation plan](docs/SCREEN_CONTENT_TRACKING_PLAN.md).
ARCore/world alignment is not implemented yet; the single-marker path remains a legacy diagnostic.

The desktop provides paired phone telemetry, automatic photo tracking
and two-front-camera setup.

| Target | Purpose |
| --- | --- |
| FramePhone-*.run | One desktop executable with runtime, AprilTag and camera broker. |
| framephone-fiducial | Automatic stereo ID 0 pose, replay and synthetic self-test. |
| framephone-photo | Fixed-photo feature matching, metric stereo pose/scale and replay. |
| framephone-camera | Camera-ring and factory calibration discovery. |
| framephone-openvr-demo | Optional simulated renderer, separate from tracking. |

Use **`bash frame/build.sh`** on Linux desktop or headset. For native development,
install AprilTag 3, OpenCV core/calib3d/imgproc/features2d and nlohmann JSON; then use CMake
and CTest as described in [development](../docs/DEVELOPMENT.md).
The dependency-free subset is `make -C frame test`.

Photo output is **T_HP**, relative to the factory head frame in meters, with
stereo-derived scale. Factory mapping and accuracy need hardware verification.
No screen recording, world-space
pose, IMU fusion or neural phone detector is included.

- [Build](docs/BUILD.md), [headset test](docs/HEADSET_TEST.md)
- [Single-marker tracking and replay](docs/FIDUCIAL_TRACKING.md)
- [Photo tracking and replay](docs/PHOTO_TRACKING.md)
- [Screen capture constraints](docs/SCREEN_CAPTURE.md)
- [Screen-content tracking plan](docs/SCREEN_CONTENT_TRACKING_PLAN.md)
- [Architecture](docs/ARCHITECTURE.md), [coordinates](docs/COORDINATE_SYSTEMS.md)
- [Calibration](docs/CALIBRATION.md), [validation](docs/TRACKING_VALIDATION.md)
- [Camera input](docs/LIVE_CAMERA.md), [recording format](docs/RECORDINGS.md)
- [Frametop provenance](third_party/frametop/README.md), [notices](THIRD_PARTY_NOTICES.md)
