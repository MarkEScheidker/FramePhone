# Build the single-file Linux app

Run **`bash frame/build.sh`** from the repository root on a Linux PC or directly
on Steam Frame. Both use the same recipe and default to ARM64. The output is:

```text
frame/build/dist/FramePhone-arm64.run
```

Copy that **one executable** to the headset. No installer, runtime container,
Frametop installation, Python installation or separate library download is
needed there. It opens a desktop window with phone pairing, live telemetry,
single-marker stereo tracking and front-camera previews/self-test.
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

Building ARM64 directly on Steam Frame needs no QEMU. The script prints the
host and target architectures and saves container output to a new
`frame/build/build-arm64.*.log` file for each attempt. On failure, it repeats the
last 25 lines and prints the log path. Look for the engine's `Error:` or failed
build step there; `Container build failed` is only the script's summary. The
QEMU hint is shown only when host and target architectures differ; it does not
diagnose the underlying failure.

### Podman systemd/cgroup errors

The build script invokes Podman with `--cgroup-manager=cgroupfs` and
`--events-backend=file` for building and exporting the executable. This avoids
requiring systemd's user service for container cgroup management or event logs;
it does not edit your container configuration. Docker uses its normal defaults.
Rootless cgroupfs does not enforce container resource limits; this build does
not request any. See the [Podman options](https://docs.podman.io/en/latest/markdown/podman.1.html).

Podman build steps also use `--isolation=chroot`, Buildah's internal runner, to
bypass `crun` startup failures such as `error running container ... /usr/bin/crun
creating container` at the first `RUN apt-get update ...` step. Packages are
installed into the build image's filesystem; the script installs no host
packages. The [Podman build options](https://docs.podman.io/en/latest/markdown/podman-build.1.html#isolation-type)
describe chroot mode. It uses fewer isolation features than an OCI runtime.
Run the build as your normal user. This workaround still needs headset testing;
the abbreviated error report does not establish the exact startup failure.

If an older checkout fails with `org.freedesktop.systemd1` errors, update the
checkout and retry `bash frame/build.sh` as your normal desktop user. Podman can
still print `Failed to add pause process to systemd sandbox cgroup` while
initializing its rootless namespace; that warning alone does not mean the build
failed. Let it continue if build steps are progressing. If it stops, retain the
last build step and accompanying `Error:`/runtime messages for diagnosis. The
same warning appears in this [upstream Buildah report](https://github.com/podman-container-tools/buildah/issues/4293).

## What gets bundled

The build compiles/tests the tracker and statically compiles the pinned camera
broker. It bundles an Ubuntu runtime with AprilTag, OpenCV, Python/Tk, Tcl/Tk,
libc and their dependencies. The app starts binaries through its own ELF loader,
so it does not require the headset's libc to match Ubuntu's version. The
self-extracting `.run` uses Makeself, avoiding a FUSE/AppImage installation.
Its POSIX/PAX tar format preserves long runtime symlink targets, including the
certificate links; the default ustar format cannot represent all of them.

The fullscreen tracking test uses AprilTag and OpenCV. Python/Tk supplies the
desktop UI; Pillow resizes the camera previews to fit their panes. There are no
neural model, PyTorch, Kornia, Python OpenCV or NumPy downloads in this build. The VR surface helper loads the installed SteamVR
client on the headset; only its pinned BSD-licensed interface header ships with
FramePhone. See [VR display](VR_DISPLAY.md) and [OpenVR provenance](../third_party/openvr/README.md).

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

GitHub Actions uses this recipe with Docker on native AMD64 and ARM64, plus an
emulated ARM64 build. A native ARM64 job also exercises the rootless Podman
chroot build. Native jobs execute the resulting `.run` outside a container, run the
geometry self-test and CLI startup checks, and open/close the GUI under a virtual display.
Artifacts are kept for 14 days. Download an **ARM64** artifact for the headset.
Hosted results exist only after the repository is pushed and the workflow runs.

Optional terminal diagnostics on a build/test PC:

```bash
./frame/build/dist/FramePhone-amd64.run -- --self-test
./frame/build/dist/FramePhone-amd64.run -- --camera --help
./frame/build/dist/FramePhone-amd64.run -- --fiducial --help
./frame/build/dist/FramePhone-amd64.run -- --overlay --self-test
```

The first `--` passes arguments through the self-extractor to the app.
`build-headset.sh` forwards to the same build. The VR surface helper is included
in the standard build and uses no SteamVR library at compile time. Direct CMake development builds are described
in [DEVELOPMENT.md](../../docs/DEVELOPMENT.md).
