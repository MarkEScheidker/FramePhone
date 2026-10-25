# Coordinate systems

T_AB maps coordinates in frame B into frame A. Distances are meters and rotations
are right-handed.

| Frame | Meaning |
| --- | --- |
| C | Camera optical frame: X right, Y down, Z forward. |
| H | Imported factory head frame: X right, Y up, Z backward. |
| M | Marker black-square center: X decoded right, Y decoded top, Z out of screen. |
| B | Phone/case body: currently no calibrated transform to M. |
| W | SteamVR standing space; used by the experimental ARCore handoff. |

The optical tracker publishes **T_HM**. Decoded corners define the orientation;
Android's reported physical display DPI supplies the marker black edge. That
metric scale is not independently verified. Fullscreen raster dimensions do not
prove physical display or case dimensions.

The VR calibration surface uses T_HM as an HMD-relative transform, provisionally
assuming factory H matches the runtime HMD frame. It does not claim an established
T_WH, world anchor, exposure-time alignment or calibrated phone-body origin.
See [VR display](VR_DISPLAY.md).

For later ARCore alignment, let A be an ARCore anchor and Q the physical phone
camera. With verified synchronized measurements and known camera-to-marker
transform T_QM:

`T_WA = T_WH * T_HM * inverse(T_AQ * T_QM)`

Compute T_AQ from same-frame anchor/camera poses. This calibrated registration
is not implemented. The camera-to-screen transform and inter-world alignment
cannot both be solved from one arbitrary pose. The
[ARCore handoff prototype](ARCORE_HANDOFF.md) uses the natural-device sensor pose
`T_AD` and provisionally assumes sensor and marker origins coincide; its
stationary registration is not a calibrated implementation of the formula above.
See [roadmap](../../docs/ROADMAP.md).
