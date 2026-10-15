# Frametop adaptations

Pinned source: Frametop/frametop
`24a86dc02669caaef8386ea5bfeb08fcb2819944`, MIT, copyright 2026 DeeJanuz.
Retain [LICENSE](LICENSE) with redistributed source and binaries.

- `src/frametop_calibration.cpp` adapts `hands/track/calib.cpp`: KB4
  projection/unprojection, axis-column poses, CAD/head/camera composition,
  millimeters-to-meters conversion, and the least-squares ray-intersection
  system. JSONCpp/vector types were replaced with existing nlohmann JSON and
  OpenCV types. Added strict validation, forward-model inversion checks,
  positive ray distances, minimum angle, SVD conditioning and residual limits.
- `StereoFramePairer` in `src/stereo.cpp` adapts the new-frame/3 ms capture
  spread policy in `hands/track/main.cpp`, for two explicitly named cameras.
  Bounded per-camera queues replace its four-camera latest-set scheduler;
  clocks must match and no clock-domain inference is copied.
- `src/frametop_ring.cpp` implements the ABI/sequence protocol from
  `hands/camd/fhring.h` with bounded read-only `pread` copies.
- `desktop/front_cameras.py` parses reported ring and factory camera identities.
  The initial front/side naming inference from `hands/README.md` contradicted the
  owner's physical observations. No sensor model or factory pair is forced;
  physical front/left/right and factory-to-stream identity must be verified.

Upstream source URLs:
https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/track/calib.cpp
https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/track/main.cpp
https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/camd/fhring.h
https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/README.md

The markerless body model and joint two-view pixel optimization are
FramePhone code, using OpenCV's SVD and Levenberg–Marquardt solver. Neural hand
models, articulated priors and gesture code are not included.

## Bundled camera broker

`camd/` vendors `hands/camd/{camd.c,tp.c,tp.h,xrcams.c,xrcams.h,fhring.h}`
from the same pinned commit, plus its [FrameEyeCameraFeed MIT notice](camd/LICENSE.FrameEyeCameraFeed).
Upstream archive SHA-256:
`7b366ba7d022a79ca98a12839098808fc5d8b82bec270e3e6b0d36937d89c522`.
The broker is compiled statically and runs on the headset host. Local adaptations:

- Accept authenticated `PKEXEC_UID` (with sudo UID fallback), validate it strictly,
  and resolve the caller's primary group from the host passwd file before dropping
  privileges. Static passwd-file parsing avoids loading host NSS modules.
- Use `framephone-camera/cam-ring` and an exclusive writer lock, independent of
  Frametop's ring directory; byte layout and sequence protocol remain version 1.
- Arm a parent-death signal before camera setup and again after dropping privileges
  so the GUI owns the broker lifetime; adjust help/errors for desktop authorization.
- Expose all mono streams for discovery, with the GUI processing only its selected
  pair. The earlier OG0VE10-only default hid the other pair on the owner's headset;
  `--sensor` remains available for manual diagnostics. XRService's camera modes
  and buffers are not modified.

Retain both MIT notices in source and binary distributions. The Python preview
reader also implements this ABI and sequence protocol using bounded read-only
copies. No hand models or upstream desktop/SteamVR integration are bundled.
