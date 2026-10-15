# Development

The repository contains independent Android and native Linux builds. Start with
the [root README](../README.md); this page describes dependency options and tests.

## Native Linux

Requirements: C++20 compiler, CMake >=3.20, OpenCV 4 (`core`,
`calib3d`, `imgproc`), and nlohmann JSON headers. Python 3 runs CLI
tests. Python/Tk provides the desktop window. Automatic detection additionally
uses Python OpenCV/NumPy and the pinned pretrained model; see
[automatic detection](../frame/docs/AUTO_DETECTION.md). Native libraries are not vendored.

Ubuntu 24.04:

```bash
sudo apt-get update
sudo apt-get install build-essential cmake python3 libopencv-dev nlohmann-json3-dev python3-tk
```

Fedora:

```bash
sudo dnf install gcc-c++ cmake make python3 opencv-devel json-devel python3-tkinter
```

From the repository root:

```bash
cmake -S frame -B frame/build/desktop -DCMAKE_BUILD_TYPE=Release
cmake --build frame/build/desktop --parallel 4
ctest --test-dir frame/build/desktop --output-on-failure
frame/build/desktop/framephone-markerless --self-test
```

Missing geometry dependencies are a configuration error. `POSE_SDK_ROOT` can
specify a nonstandard OpenCV/JSON installation prefix. The optional
`FRAMEPHONE_BUILD_OPENVR_OVERLAY=ON` builds a separate rendering demo and requires
the OpenVR SDK/runtime.

The portable camera subset requires only a C++20 compiler and Make:

```bash
make -C frame test
```

It tests frame sources and ring input. Use the full CMake build for calibrated
geometry and markerless tracking tests.

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
