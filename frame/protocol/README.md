# FramePhone data contracts

The current app uses these versioned contracts:

- [Authenticated phone pairing and IMU telemetry](../docs/PAIRING_AND_IMU.md)
- [Markerless sessions, labelled corners and body-pose results](../docs/MARKERLESS_DIAGNOSTIC.md)
- [Coordinate frames and units](../docs/COORDINATE_SYSTEMS.md)
- [Raw grayscale recording manifests](../docs/RECORDINGS.md)
- [Factory camera calibration](../docs/CALIBRATION.md)

Body dimensions come from the paired phone; camera calibration is captured from
the headset factory files. Legacy display-marker layout exports are no longer
loaded by the app.
