# Protocols and local evidence

The supported test uses these marker, telemetry and recording formats.

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

The updated peers negotiate `marker_state_v1` in hello/profile. The phone sends
`marker_state` with session ID, displayed boolean and validated fiducial profile
approximately every 250 ms. Actual fullscreen geometry includes screen_width_px,
screen_height_px and black_edge_px. A false/stale state or changed profile clears
the optical trial and VR display. Without this extension, older marker profiles
can still support optical tracking, with loss determined from camera detections.

Pose results include `processed_host_monotonic_ns` for bounded local publication
freshness. It does not convert camera exposure timestamps to the host clock.
The VR helper consumes only a current accepted pose, atomically published as
`vr-pose.json` inside the trial. It is local process communication, not a LAN API.

The local `fiducial --preview-ring FILE --camera NAME` worker uses a separate
pipe format: one `framephone-camera-preview-v1` JSON line followed by exactly
`image_bytes` bytes of annotated Gray8 PGM. Zero bytes denotes a waiting/stale
camera status. Frame identity, source timestamps and detections accompany each
image. The desktop retains one newest packet per camera. These previews do not
depend on stereo pairing and are not accepted 3D measurements.

Pose candidates may include `axes`: two views, each with three projected
polylines for marker X/Y/Z. They are diagnostic unless status is `measured` and
are drawn only on that pose's exact camera pair.
