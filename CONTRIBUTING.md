# Contributing

FramePhone is a small experimental project. Focused bug reports, recorded test
cases, documentation corrections and small pull requests are welcome. Open an
issue before a large feature or architecture change so the scope can be agreed.
There is no stable API or release schedule yet.

## Getting started

Start with the [component guide](docs/REUSING.md) to find the layer you want to
change. Follow [DEVELOPMENT.md](docs/DEVELOPMENT.md). The Android and native projects
build independently; a headset is not needed for the software tests.

For native changes, run the full CMake/CTest build when the dependencies are
available. Camera-only changes can use the standalone CMake checks in
[Development](docs/DEVELOPMENT.md#camera-module-only). For Android changes, run `assembleDebug`, `testDebugUnitTest` and `lintDebug` from
`phone/`. State which checks you ran and whether hardware was involved.

## Changes and review

- Keep pull requests focused. Explain the problem, resulting behavior and
  relevant validation; include limitations where a device was unavailable.
- Preserve explicit camera identities, clock domains, transform directions and
  meters. An accepted geometric fit is not proof of hardware accuracy.
- Add regression coverage for behavioral fixes. Prefer independent geometry or
  image fixtures over tests that repeat the implementation's calculation.
- Use the repository's formatting settings. C++ uses four-space indentation;
  Kotlin follows its existing style. Avoid unrelated dependency upgrades.
- Keep reusable modules independent of application configuration, UI and protocol
  code. Camera changes must pass the copied-module build and standalone tests;
  update the module example and API documentation when its contract changes.
- Keep copied code attribution and licenses. Contributions to original code are
  provided under this repository's MIT license; no CLA is required.

## Reporting tracking problems

Include the platform and dependency versions, build command, exact reproduction
command, relevant logs, phone marker configuration and whether the result used
synthetic, recorded or live images. For hardware results, include measured
distance/tilt, lighting, camera resolution and capture skew where available.

Share only the camera samples needed to reproduce the problem. Keep credentials,
private keys, local SDK paths, real device calibration and unrelated camera
recordings out of commits. Synthetic fixtures belong under `frame/tests/fixtures/`;
local captures can live in the ignored `captures/` directory.
