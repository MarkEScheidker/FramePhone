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

Upstream source URLs:
https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/track/calib.cpp
https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/track/main.cpp
https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/camd/fhring.h

The rigid multi-tag consensus and joint two-view pixel optimization are
FramePhone code, using OpenCV's SVD and Levenberg–Marquardt solver. Neural hand
models, articulated priors, gesture code and privileged capture code are not
included. Use upstream `ft-camd` as the separate camera supplier; its own
FrameEyeCameraFeed notice must accompany any broker you redistribute.
