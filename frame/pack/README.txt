FramePhone single-file Linux desktop test

Build from the repository root: bash frame/build.sh
Output: frame/build/dist/FramePhone-arm64.run
Copy this executable to the Steam Frame, allow execution in file Properties,
and open it. Phone telemetry provides LAN discovery, pairing and live sensor
readings. Compare the pairing fingerprint on both devices and approve both.
Camera/legacy tracking diagnostics remain in a separate tab. No runtime commands
are needed on the headset.

Docker/Podman is a build-machine requirement only. Runtime libraries, Python/Tk
and the static camera broker are bundled. No Frametop installation is needed.
Stock Linux shell/tar/gzip, X11/XWayland and graphical pkexec authorization are
host requirements. Hardware camera access remains experimental.

Build and runtime details: frame/docs/BUILD.md and frame/docs/HEADSET_TEST.md.
