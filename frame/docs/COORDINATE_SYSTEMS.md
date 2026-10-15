# Coordinates and units

`T_AB` maps points from B into A. Rigid transforms use right-handed frames and
meters. Native body poses contain a row-major 3×3 rotation and translation.

| Frame | Definition |
| --- | --- |
| B | Phone body/case center; X right, Y toward physical top, Z through front. |
| C | Optical camera; X image right, Y image down, Z forward. |
| H | Factory head frame; OpenVR-style X right, Y up, Z backward. |
| W | Future selected XR reference space, with explicit identity/reset history. |

The markerless estimator outputs **T_HB**. Front-face corners in B are
`(-w/2,+h/2,+d/2), (+w/2,+h/2,+d/2), (+w/2,-h/2,+d/2), (-w/2,-h/2,+d/2)`.
The user labels physical top/front; a rectangle alone cannot resolve top/bottom
symmetry. IPPE solves a local Z=0 front plane; its translation is corrected by
the rotated half-thickness to report the body center.

Pixel observations use native OpenCV pixel centers, top-left (0,0), X right and
Y down. Rectification preserves the explicit virtual intrinsics. Factory
`T_HC` includes the optical-to-head rotation; do not apply an extra axis flip.

Android IMU axes remain natural-device axes, independent of display rotation.
Sensor-to-body alignment has not been measured. Body dimensions do not supply
active-display size/offset; future screen rendering needs that separate mapping.

Future world composition is:
`T_WB(t_capture) = T_WH(t_capture) * T_HB(t_capture)`.
It requires historical, timestamp-aligned headset poses and camera-to-XR time
mapping. Camera capture, Android elapsed realtime, host monotonic receipt and
XR clocks are not interchangeable. Current clock diagnostics and stereo skew
gates do not compensate independent phone/headset motion.

See the [markerless guide](MARKERLESS_DIAGNOSTIC.md) for result states and limits.
