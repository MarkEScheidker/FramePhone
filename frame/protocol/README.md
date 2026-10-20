# Protocols and local evidence

The new [fixed-photo session and one-time transfer](../docs/PHOTO_TRACKING.md)
uses framephone-photo-session-v1/framephone-photo-pose-v1, publishing T_HP with
stereo-derived scale. ARCore/world alignment is explicitly not active yet.
The marker formats below remain for the legacy diagnostic.

- [Authenticated LAN pairing, marker profile and sensors](../docs/PAIRING_AND_IMU.md)
- [Single-marker sessions, pose results and replay](../docs/FIDUCIAL_TRACKING.md)
- [Grayscale frame manifests](../docs/RECORDINGS.md)
- [Factory calibration](../docs/CALIBRATION.md)
- [Transform conventions](../docs/COORDINATE_SYSTEMS.md)

TLS profile v1 now optionally includes fiducial family tag36h11, ID 0,
black_edge_m, size_source android_display_dpi, origin black_square_center and
axes right_up_front. The Android app derives size automatically; reported DPI
is unverified. Older phones can still send telemetry but cannot start this
tracker without a fiducial profile. New optical sessions use
framephone-fiducial-session-v1; results use framephone-fiducial-pose-v1 and T_HM.
No multi-tag layout export or markerless corner file is used.
