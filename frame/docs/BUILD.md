# Build the single-file Linux app

Run **`bash frame/build.sh`** from the repository root on a Linux PC or directly
on Steam Frame. Both use the same recipe and default to ARM64. The output is:

```text
frame/build/dist/FramePhone-arm64.run
```

Copy that **one executable** to the headset. No installer, runtime container,
Frametop installation, Python installation or separate library download is
needed there. It opens a desktop window with camera controls and a self-test.
See [HEADSET_TEST.md](HEADSET_TEST.md) for the mouse-only test procedure.

## Build-machine setup

The machine doing the build needs Linux, Python 3 and Podman or Docker. Ubuntu
24.04 (including WSL2) can use:

```bash
sudo apt-get update
sudo apt-get install -y podman python3 qemu-user-static binfmt-support
sudo update-binfmts --enable qemu-aarch64
bash frame/build.sh
```

QEMU/binfmt is needed only when building ARM64 on an x86_64 PC. Docker Desktop
already includes emulation; Linux Docker Engine needs binfmt configured too.
Set `FRAMEPHONE_CONTAINER_ENGINE=docker` to choose Docker explicitly. Prefer
building on a PC when you want to leave the headset's operating system alone.
Building on the headset itself requires those build tools there; running a
PC-built app does not.

For an executable that runs on your Linux PC, use:

```bash
bash frame/build.sh --arch native
```

On x86_64 this produces `FramePhone-amd64.run`. Build jobs default to two;
`FRAMEPHONE_BUILD_JOBS=4 bash frame/build.sh` changes that. The first build
fetches Ubuntu 24.04 and its compiler/library packages; later builds reuse
cached layers. Emulated ARM64 builds take longer than native builds.

## What gets bundled

The build compiles/tests the tracker and statically compiles the pinned camera
broker. It bundles an Ubuntu runtime with AprilTag, OpenCV, Python/Tk, Tcl/Tk,
libc and their dependencies. The app starts binaries through its own ELF loader,
so it does not require the headset's libc to match Ubuntu's version. The
self-extracting `.run` uses Makeself, avoiding a FUSE/AppImage installation.

At launch the app checks/unpacks its payload to a temporary directory, opens
the GUI and removes the extracted runtime on exit. Allow free disk space for
that runtime. The target supplies ordinary Linux shell/tar/gzip tools, a desktop
with X11/XWayland, and `pkexec` with a graphical polkit agent for camera setup.
The factory files and XRService must be provided by the headset firmware.
These stock-headset assumptions still need hardware confirmation.

**Enable cameras** authorizes only the bundled broker. The tracker and GUI run
as your normal user. No system service, persistent capability, root filesystem
change or Frametop installation is made. The broker drops privileges after
opening XRService's read-only buffers and tracepoints. It exits with the app.

Dependency copyright files are retained in the payload's `rootfs/usr/share/doc`
and `rootfs/usr/share/common-licenses`; FramePhone/Frametop notices are under
`rootfs/opt/framephone/share/framephone`. Makeself's GPL notice is beside AppRun.
The original application remains MIT licensed. Apt versions receive updates;
this is a fixed recipe, not a promise of byte-identical builds. The payload also
records exact installed versions in `share/framephone/runtime-packages.txt`.

## Updates and verification

Build again and replace the `.run` file while the app is closed. Settings and
results live in your user profile, outside the executable. An adjacent `.sha256`
file is also generated for transfer verification; it is not needed to launch.

GitHub Actions uses this recipe on native AMD64 and ARM64, plus an emulated
ARM64 build. Native jobs execute the resulting `.run` outside Docker, run the
real detector/CSV checks, and open/close the GUI under a virtual display.
Artifacts are kept for 14 days. Download an **ARM64** artifact for the headset.
Hosted results exist only after the repository is pushed and the workflow runs.

Optional terminal diagnostics on a build/test PC:

```bash
./frame/build/dist/FramePhone-amd64.run -- --self-test
./frame/build/dist/FramePhone-amd64.run -- --stereo --help
./frame/build/dist/FramePhone-amd64.run -- --diagnostic --headless --frames 3
```

The first `--` passes arguments through the self-extractor to the app.
`build-headset.sh` forwards to the same build. `build-openvr-demo.sh` builds only
the separate simulated renderer. Direct CMake development builds are described
in [DEVELOPMENT.md](../../docs/DEVELOPMENT.md).
