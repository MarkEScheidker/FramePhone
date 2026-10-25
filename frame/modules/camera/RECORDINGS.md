# Grayscale frame recordings

`RecordedFrameSource` reads a local directory containing a UTF-8 `manifest.tsv`
and one binary PGM (P5) image per row. The first line is exactly
`framephone-recording-v1`. Remaining non-comment lines have six tab-separated
fields:

```text
camera_id  capture_timestamp_ns  clock_domain  calibration_id  exposure_us  image_filename
```

`-` means exposure is unavailable. Timestamps are preserved verbatim; rows must
be ordered within each `(camera_id, clock_domain)` pair. Separate cameras can use
independent clocks. Each image must have an 8-bit grayscale P5 raster, max value
255, and dimensions no greater than 16384 by 16384 (128 MiB per frame). Paths
must be `.pgm` files directly inside the recording directory. Recording data
stays local; this reader does not capture or transmit frames.

Example:

```text
framephone-recording-v1
front-left	1000000000	xrservice-camera-ns	calib-left-v1	8000	frame-000.pgm
```

The values above are illustrative. Do not infer timestamp origins, exposure
units, calibration quality, or headset pose from a filename. Record the source's
clock and calibration identifiers in the manifest from trusted metadata.
