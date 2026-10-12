# Camera calibration JSON v1

This is a FramePhone local calibration interchange format. It is not the format
of `/persist/xrservice.json` and does not automatically import factory data.
The operator must verify camera identity, distortion model, resolution, cropping
and coordinate convention before declaring real calibration `calibrated`.

```json
{
  "schema": "framephone.camera-calibration",
  "version": 1,
  "calibration_id": "left-camera-calibration-v1",
  "camera_id": "EXACT_RING_CAMERA_NAME",
  "status": "calibrated",
  "model": "fisheye_kb4",
  "pixel_convention": "opencv_pixel_centers",
  "image_size_px": [640, 480],
  "intrinsics": {"fx": 300.0, "fy": 300.0, "cx": 319.5, "cy": 239.5},
  "distortion": [0.0, 0.0, 0.0, 0.0]
}
```

The numbers above illustrate the schema; they are **not Frame intrinsics**.
`status` is either `calibrated` or `synthetic`; reported-DPI/guessed camera
calibration is rejected. `calibration_id`, `camera_id`, width and height must
exactly match the input frame. Intrinsics refer to that unmodified image;
there is no implicit resize, rotation, crop, skew or rectification.

Optical C axes are X right, Y down, Z forward. Pixel centers use OpenCV's
convention (top-left pixel center at 0,0). `fx/fy` are positive and principal
point lies within the image. Values must be finite. `fisheye_kb4` uses OpenCV's
Kannala–Brandt coefficients `[k1,k2,k3,k4]`. `pinhole` supports empty distortion,
`[k1,k2,p1,p2]`, `[k1,k2,p1,p2,k3]`, or
`[k1,k2,p1,p2,k3,k4,k5,k6]`. A calibrated sensor's model must match; coefficients
cannot be moved between models. Extra informational fields are permitted.
Duplicate keys, unsupported schema/model/status, and invalid values fail.

Camera-to-headset extrinsics and capture-to-XR clock maps are deliberately
separate contracts. This calibration enables T_CP only, not world-space tracking.
