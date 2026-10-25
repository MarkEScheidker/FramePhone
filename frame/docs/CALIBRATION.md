# Body and camera calibration

Measure the outside phone/case width and height in millimeters and
save them in Android before pairing. These describe the rigid body, not the
active display. A case change requires updated dimensions and a new optical trial.
The tag fills the display width automatically including its quiet margin.
Its physical edge is estimated from reported display DPI; this initial scale is
unverified. The pose origin is the marker center. No marker-to-body offset or
active-display physical calibration is inferred from body dimensions.

The native pipeline imports factory KB4 intrinsics and camera-to-head transforms
from `/persist/xrservice.json` and `/persist/device_config.json`. Each trial
preserves the exact files and a combined SHA-256 identity. It verifies dimensions,
finite/invertible intrinsics, rigid transforms and stereo baseline. Factory
positions are converted to meters; source image dimensions must match exactly.

Verify the physical front-lens mapping, image orientation/crop, distortion model,
head axes and baseline on the actual headset. Equal dimensions and plausible
wireframes do not prove correct mapping or metrology-grade accuracy. Imported
data is labelled `factory_imported`; synthetic fixtures cannot substitute for it.

If factory calibration is inadequate, collect independently measured calibration
targets throughout the field of view and establish a separate rig/extrinsic
calibration workflow. Record hold-out errors and provenance before replacing
factory parameters. The current pipeline expects factory-format KB4 data;
the former single-camera interchange loader is not supported.

See [coordinates](COORDINATE_SYSTEMS.md), [headset setup](HEADSET_TEST.md) and
[tracking validation](TRACKING_VALIDATION.md).
