FramePhone single-file Linux desktop app

Build from the repository root: bash frame/build.sh
Output: frame/build/dist/FramePhone-arm64.run
Open it on Steam Frame after allowing execution in file Properties.
Cameras start automatically; approve desktop authorization if prompted.
The app discovers and reconnects the saved phone. Use Connection for first
pairing, and compare fingerprints on both devices.
Show the fullscreen marker on Android, then click Start tracking on the dashboard.
Show rectangle in VR enables the fiducial-driven SteamVR rectangle.

Docker/Podman is needed only for building. Runtime libraries, Python/Tk and the
camera broker are bundled. No neural models or runtime downloads are used.
The VR display uses the installed SteamVR client; no Frametop install is needed.
Distance scale, VR head alignment and timing need independent validation.
ARCore and screen streaming come later. See frame/docs/HEADSET_TEST.md.
