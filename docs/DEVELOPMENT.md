# Development

The repository contains independent Android and native Linux builds. Start with
the [root README](../README.md); this page describes dependency options and tests.

## Native Linux

Requirements: C++20 compiler, CMake >=3.20, AprilTag 3, OpenCV 4 (`core`,
`calib3d`, plus `imgproc` for tests), and nlohmann JSON headers. Python 3 runs CLI
tests. SDL2 is optional for the desktop window. Dependencies are not vendored.

Ubuntu 24.04:

```bash
sudo apt-get update
sudo apt-get install build-essential cmake python3 libapriltag-dev libopencv-dev nlohmann-json3-dev libsdl2-dev
```

Fedora:

```bash
sudo dnf install gcc-c++ cmake make python3 apriltag-devel opencv-devel json-devel SDL2-devel
```

From the repository root:

```bash
cmake -S frame -B frame/build/desktop -DCMAKE_BUILD_TYPE=Release -DFRAMEPHONE_REQUIRE_TRACKER=ON
cmake --build frame/build/desktop --parallel 4
ctest --test-dir frame/build/desktop --output-on-failure
frame/build/desktop/framephone-stereo --help
```

`FRAMEPHONE_REQUIRE_TRACKER=ON` makes missing detector/pose dependencies a
configuration error. Without it, CMake can build a reduced input/preview utility;
check its configuration output rather than assuming pose support exists.

| Option | Purpose |
| --- | --- |
| `FRAMEPHONE_ENABLE_SDL2=OFF` | Build without the desktop window; use `--headless` for the diagnostic. |
| `FRAMEPHONE_ENABLE_APRILTAG=OFF` | Input/preview-only build; no fabricated detector fallback. |
| `FRAMEPHONE_ENABLE_POSE=OFF` | Detection without calibrated pose estimation. |
| `APRILTAG_ROOT`, `SDL2_ROOT`, `POSE_SDK_ROOT` | Nonstandard dependency install prefixes for the target architecture. |
| `FRAMEPHONE_BUILD_OPENVR_OVERLAY=ON` | Separate renderer demo, requiring the OpenVR SDK/runtime. |

The portable subset requires only a C++20 compiler, Make and Python 3:

```bash
make -C frame test all
```

It tests frame sources, ring input and CLI behavior; it does **not** validate
real detection or calibrated pose. Do not use it as the full tracker build.

`bash frame/run-diagnostic.sh --headless --frames 120` is a convenience launcher.
It can use ignored SDKs under `frame/build/deps` when present on x86_64, otherwise
installed libraries. It does not download dependencies. The CMake commands above
work independently of that local cache.

### Steam Frame

Use **`bash frame/build.sh`** on either Linux desktop or headset. The default
output is the single ARM64 executable `FramePhone-arm64.run`, including its runtime
libraries, Python/Tk desktop controls and static camera broker. Follow
[BUILD.md](../frame/docs/BUILD.md) for the shared build/run/update procedure,
then [HEADSET_TEST.md](../frame/docs/HEADSET_TEST.md) for live camera input.
`--arch native` builds a package for the Linux PC's own architecture. The
app starts its own bundled broker on SteamOS through graphical authorization;
no Frametop or runtime container is needed on the target.
Container/ARM64 CI does not validate camera access or tracking accuracy.

## Android

Open `phone/` in Android Studio or configure a local Android SDK. The project uses
JDK 17 to run Gradle, Gradle 8.13, AGP 8.11.2, SDK 36 and minimum Android API 31.
Java/Kotlin bytecode targets 11; this differs from the JDK needed to run Gradle.

```bash
cd phone
bash gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

Windows uses `gradlew.bat`. `phone/local.properties` may set `sdk.dir` and stays
untracked. Output APK: `phone/app/build/outputs/apk/debug/app-debug.apk`.
No release signing key is supplied. Device tests require a connected Android
12+ phone or emulator and `:app:connectedDebugAndroidTest`; CI runs host unit
tests, lint and the debug build, not device acceptance tests.

If a Windows JVM test worker fails before loading tests due to an inherited
native-library path, use a command-scoped `-Djava.library.path=.` workaround.
Do not apply it globally or to native-library tests.

## Continuous integration

GitHub Actions defines a portable build, a full x86_64 Linux build, an ARM64
headset-target build, and Android debug/unit/lint checks. Native tests use
synthetic fixtures and an independent ring producer; no camera privileges are
required. Actions are pinned to commits and run with read-only repository access.
The first hosted results are available after the repository is pushed.
The package jobs build, install and exercise the runtime on both AMD64 and
ARM64. The desktop-to-ARM64 build additionally needs host QEMU/binfmt support.
An additional package job exercises ARM64 emulation on an AMD64 Linux runner.

## Source handoffs

`python3 scripts/package-source.py` writes a public source archive under
`build/dist/`, excluding local notes, IDE settings, SDK caches, build outputs,
credentials and captures. It works before Git is initialized. Inspect the archive
before using it to start a new repository; it is not a dependency bundle.

`bash frame/package-headset.sh` creates a headset source handoff under
`frame/build/dist/`. Both include license notices. Publish source from a reviewed
Git checkout; do not commit generated archives, APKs or local SDKs.
