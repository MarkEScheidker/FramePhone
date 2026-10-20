# Coordinates and units

`T_AB` maps B into A. Rigid transforms are right-handed and metric.

| Frame | Definition |
| --- | --- |
| P | Displayed photo center; X photo right, Y photo up, Z out of its front. |
| M | Black marker-square center on the screen; X right, Y decoded top, Z out of its front. |
| C | Optical camera; X image right, Y image down, Z forward. |
| H | Factory head frame; X right, Y up, Z backward. |
| B | Future calibrated phone-body frame; no measured T_MB is currently supplied. |
| W | Future selected XR reference space, with identity/reset history. |

The photo estimator publishes **T_HP**, not T_HB. Its reference coordinates use
photo width as one unit, centered with Y up; stereo estimates width in meters.
Black letterbox bars are outside that target. It does not use display DPI or
body/case dimensions for scale. Photo-to-body/camera offsets remain uncalibrated.

The legacy marker estimator publishes **T_HM**, not T_HB. Marker corners are
`(-s/2,+s/2,0), (+s/2,+s/2,0), (+s/2,-s/2,0), (-s/2,-s/2,0)`.
AprilTag's decoded orientation labels these corners, including tilted/rotated
views. Physical edge s excludes the white quiet zone. Android's reported
display DPI supplies its initial, explicitly unverified scale.

Raw observations use native pixel centers, origin top-left, X right/Y down.
Factory KB4 projection and T_HC handle distortion and camera-to-head axes.
Do not add another axis flip or substitute pinhole intrinsics.

Android IMU remains in natural-device coordinates. Sensor-to-marker alignment
and lever arm have not been measured. A case/body size is not an active-screen
calibration or a marker-to-body offset.

Future photo world composition is
`T_WP(t_capture) = T_WH(t_capture) * T_HP(t_capture)`.
The corresponding legacy marker composition is
`T_WM(t_capture) = T_WH(t_capture) * T_HM(t_capture)`.
It needs historical headset poses and camera-to-XR time mapping. Camera,
Android elapsed realtime, host monotonic receipt and XR clocks are not
interchangeable. Current output has no inertial fusion or motion compensation.
