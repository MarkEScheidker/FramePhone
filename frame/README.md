# Frame application

The supported experiment is [single fullscreen AprilTag tracking](docs/FIDUCIAL_TRACKING.md).
Build with `bash frame/build.sh` from the repository root and open
`frame/build/dist/FramePhone-arm64.run` on the headset. The same command works
on a Linux desktop; `--arch native` produces a package for that build machine.

| Program | Responsibility |
| --- | --- |
| framephone-camera | Factory camera and ring discovery. |
| framephone-fiducial | Single-tag stereo detection, pose estimation and replay. |
| framephone-overlay | Head-relative tracked screen slab in SteamVR; standalone geometry self-test. |
| framephone-camd | Privileged setup, then unprivileged camera-ring publishing. |
| desktop/app.py | Pairing, telemetry, camera controls, marker diagnostics and optional VR display. |

Poses are **T_HM**, marker center to imported factory head frame, in meters.
Android DPI supplies an unverified marker size. The VR display assumes the
factory head and runtime HMD frames coincide; timing/origin calibration remains
experimental. ARCore, world anchoring, a registered virtual controller and live
screen streaming are not implemented.

See [build](docs/BUILD.md), [headset testing](docs/HEADSET_TEST.md),
[VR display](docs/VR_DISPLAY.md), [architecture](docs/ARCHITECTURE.md),
[pairing protocol](docs/PAIRING_AND_IMU.md), and [notices](THIRD_PARTY_NOTICES.md).
