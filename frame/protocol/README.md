# Phone layout JSON v1

Legacy format produced by the earlier Android fiducial app. The current phone
app no longer exports it; native consumers and fixtures retain support for old
experiments. This is an offline marker-geometry snapshot, not the new sensor
transport. See [LAN pairing and telemetry](../docs/PAIRING_AND_IMU.md).

Required identifying fields are `schema = framephone.phone-layout`,
`layout_version = 1`, opaque `revision`, `family = tag36h11`, `units = meters`.
Consumers must reject unsupported versions/families, duplicate/unknown IDs,
nonfinite numbers, invalid dimensions, and incomplete or inconsistent corner sets.

`markers` contains stable IDs, clockwise raster orientation in current display pixels, actual window bounds
in full-display logical pixels, integer cell dimensions, quiet-zone thickness,
four detector-boundary corners in display pixels, four corresponding P-frame
corners in meters, and actual physical boundary width/height. Corner order is
TL/TR/BR/BL along current display axes; **explicitly adapt detector order**.
The raster rotation must be used to associate canonical tag corners with these
display-ordered corners. Each point has Z=0. Requested size is descriptive; use actual corners for PnP.

`display` contains physical-mode and logical resolutions, Surface rotation,
natural orientation, portrait-relative rotation, reported DPI, system/cutout
insets, usable bounds, cutout rectangles, conservative rounded-corner clearance,
physical pixel scale, and `T_PD`.
Rectangles are `[left,top,right,bottom]`; the insets field uses the same array
shape but represents four edge distances. `calibration` records manual measured
portrait dimensions, configuration key, version, epoch measurement time, and
unknown uncertainty (`null`). Physical units are always meters outside fields
explicitly suffixed `_px` or the DPI diagnostics.

`observed_at_elapsed_realtime_ns` is an Android layout measurement timestamp,
not a camera timestamp. JSON consumers should preserve this integer as 64-bit;
JavaScript should avoid precision loss if clocks ever exceed safe integer range.
It has no established relationship to OpenXR or headset capture time.

Every configuration, orientation, inset or display change requires a new snapshot.
IDs do not identify a layout revision or phone. During future live tracking,
layout updates need an explicit synchronized protocol; fixed IDs alone cannot
tell the headset that marker positions changed. Until then, freeze the phone
configuration/rotation during each recorded experiment and retain its JSON.

The native consumer now validates this export and adapts raster orientation to
AprilTag's canonical corner order. See [camera calibration v1](camera-calibration.md)
and the camera-relative JSONL pose contract in [POSE.md](../docs/POSE.md).
Clock maps, camera recordings and future IMU samples remain separate contracts.
No live networking is included and Android's game rotation vector is not assumed
to share OpenXR's world frame.

Supported `layout` values: `FOUR_CORNERS` (IDs 0–3), `TWO_DIAGONAL`
(IDs 0,2), `FOUR_EDGES` (IDs 0–3, phone-frame top/right/bottom/left), and
`SIX_PHONE_FRAME` (default, IDs 0–5, corners plus right/left centers). Existing
saved layout choices remain supported. A consumer must use the exported layout and
corners rather than assuming six detections or a fixed ID-to-position mapping.

Optional informational fields `sizing_mode` (`auto_fit` or `manual`) and
`overlay_opacity` describe rendering. In automatic mode, `requested_marker_size_m`
retains the manual-size preference; consumers must use each marker's actual
boundary size and measured corners. Cutout avoidance can shift nominal anchors.
These additions do not change the v1 geometry contract.
