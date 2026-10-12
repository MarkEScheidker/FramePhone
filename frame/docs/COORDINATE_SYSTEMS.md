# Coordinates and units

`T_AB` maps points from B into A. Rigid transforms use right-handed frames,
meters. Layout quaternions use `[x,y,z,w]`; native pose outputs instead use a
row-major 3x3 rotation matrix. Never use Android dp for
physical geometry.

| Frame | Definition |
| --- | --- |
| P | Phone body; origin active display center, +X right and +Y up in canonical portrait, +Z out toward viewer. |
| D | Current display; origin active display center, +X current screen right, +Y current screen up, +Z out. |
| C | OpenCV optical camera; +X image right, +Y image down, +Z forward. |
| H | Head frame used by the factory importer: OpenVR-style +X right, +Y up, +Z backward. |
| W | Selected OpenXR reference space; space identity/recenter history must accompany poses. |

Android pixels are a separate 2D convention: top-left origin, X right, Y down.
Exported coordinates denote **pixel edges**: right edge of a W-pixel screen is W,
not W-1. They are not camera image-center coordinates.

Given manually measured current display dimensions `w_m, h_m` and full logical
dimensions `W_px, H_px`:

```text
x_D = (u - W_px/2) * w_m/W_px
y_D = (H_px/2 - v) * h_m/H_px
z_D = 0
```

System bar insets are exported for diagnostics but do not constrain marker
placement: their screen-relative edges change when Android rotates its UI. Marker
anchors use the full active panel with rounded-corner clearance, so they remain
fixed in phone frame P. Cutouts are checked separately. Use actual
`getLocationOnScreen()` positions and measured view sizes, including any
WindowManager translation, rather than requested layout positions.

## Rotation direction

[Android Display.getRotation](https://developer.android.com/reference/android/view/Display#getRotation())
reports the rotation of drawn graphics, opposite physical device rotation.
For a portrait-natural phone let `q = Surface.rotation` (0,1,2,3), not degrees.
`T_PD` rotates D clockwise by `q*90°` when viewed from in front of the display:

| q | `(x_P, y_P)` from `(x_D, y_D)` |
| --- | --- |
| 0 | `(x_D, y_D)` |
| 1 | `(y_D, -x_D)` |
| 2 | `(-x_D, -y_D)` |
| 3 | `(-y_D, x_D)` |

For landscape-natural devices, canonical portrait is explicitly defined as
Surface.ROTATION_90, with `q = (rotation - 1 + 4) % 4`. This convention must also
be used by any future phone IMU alignment. The export includes both rotations.
`T_PD` has zero translation and quaternion `(0,0,sin(-q*pi/4),cos(-q*pi/4))`.
This discrete display mapping says nothing about physical world orientation.

## Marker corners

Marker positions are defined in the canonical portrait phone frame P, so IDs stay
attached to the same physical panel locations as Android rotates the display. ID
0 is phone-frame top-left, 1 top-right, 2 bottom-right, and 3 bottom-left for the
corner layout (the default). The six-tag layout adds IDs 4/5 at right/left
side centers. Edge-center layout uses phone-frame top/right/bottom/left; the
diagonal layout retains IDs 0 and 2. The raster rotates in display pixels to keep
each tag's orientation fixed on the physical phone. Changing layout or rotation
still requires a new export because pixel positions and raster orientation change.
These IDs alone cannot identify which of several phones is in view.

Corners are exported TL, TR, BR, BL along the **current display axes**, at the outer edge
of tag36h11's black 8x8 boundary. The 10x10 rendered window includes the one-cell
white ring. `image_rotation_clockwise_deg` records the raster rotation. Preserve
the exported order; it is not automatically the detector's `p[0..3]` order or
OpenCV's IPPE_SQUARE object-point convention. The native adapter must explicitly
map each library's corner order and test it with rotated images.

Each axis has its own integer cell size to support non-square logical pixels.
Quantization can make the physical result slightly rectangular. Joint PnP should
use the exported four corners. IPPE_SQUARE is only valid after verifying its
square constraint and specified point order; it cannot blindly use requested mm.

## Future world transform

```text
T_WP(t_capture) = T_WH(t_capture) * T_HC * T_CP(t_capture)
```

Both OpenCV and OpenXR are right-handed. For co-located, aligned camera/XR-view
frames, the axis-conversion rotation is `diag(1,-1,-1)`, a 180° rotation about X,
not a reflection. Real `T_HC` also includes measured camera mounting translation
and orientation. Do not apply the conversion twice if extrinsics already contain it.

Interpolate timestamp-aligned headset translation and quaternion orientation;
never substitute the latest headset pose. Headset translation alone is
insufficient during head rotation. Export timestamps use Android
`elapsedRealtimeNanos`, and are layout observation times, not camera captures.
They are not interchangeable with OpenXR time or a headset hardware clock.
Clock offset, drift, uncertainty, and reset behavior require a future explicit
contract. No world tracking or timestamp synchronization is implemented yet.

The stereo estimator directly returns `T_HP`; future world composition is then
`T_WP(t_capture) = T_WH(t_capture) * T_HP(t_capture)`. Capture-skew gating
matches frames within a declared shared clock; it does not establish an XR clock
map or compensate motion between the two exposure times.
