# Automatic phone detection

Build with `bash frame/build.sh` and open the new `FramePhone-arm64.run`.
The executable includes OpenCV Zoo YOLOX-S pretrained on COCO, including cell
phones. No training or runtime download is required. The container build fetches
the model, verifies its SHA-256 and runs real inference before packaging.

## Headset test

1. Open **Markerless tracking → Enable cameras**, approve access and refresh.
2. Choose the two front streams. Cover each front lens to verify its view.
3. Click **Start phone detection**. No pairing or corner selection is needed for
   this visual test. Pairing remains necessary for telemetry and manual metric pose.
4. Green boxes show phone detections and confidence. The status reports left/right
   counts and processing time. Move or remove the phone to check updates/clearing.
5. Amber quadrilaterals appear where OpenCV finds a visible four-sided contour.
   The displayed angle is a visible edge's image-plane axis, modulo 180 degrees.
6. **Stop** ends detection. **Open results** opens local sessions; `detection-*`
   contains `detections.jsonl` and three rotating preview slots.

All qualifying phone boxes are displayed, largest apparent area first. This
detects a category, not the paired phone's identity. It reacquires on subsequent
images. Persistent identity and cross-camera matching are future work.

## Evidence and limitations

OpenCV DNN runs on CPU using two threads. Input is upper-left letterboxed to
640×640, padded with 114, unnormalized grayscale replicated into three channels.
YOLOX grid decoding maps boxes back to native pixels. Phone must be the strongest
class and combined confidence at least 0.30. Phone-only NMS suppresses duplicates;
at most eight detections are returned per view. OpenCV Canny/contours/polygon
approximation provides optional visible outlines inside detector regions.

Views are processed independently; this is not a synchronized stereo measurement.
Boxes, outlines and angles use distorted native camera pixels. They supply no
metric distance, physical top/front labels or 3D rotation. Hidden corners and
detector-box corners are never passed off as physical body observations.
The next integration must validate automatic corner associations against
stereo/body geometry and resolve the rectangle's top/bottom symmetry.
RAPID is a possible later silhouette tracker; it needs an initial pose.

The model was trained on ordinary COCO photographs. Monochrome tracking cameras,
small phones, hands, reflections and unfamiliar angles can cause misses or false
positives. Frame accuracy and performance remain unmeasured; no GPU/NPU integration
is assumed. About 36 MB of weights plus Python OpenCV/NumPy are bundled.

Logs use `framephone-phone-detection-v1`, native `box_xywh`, confidence, optional
`corners_px`/`axis_deg_mod180`, per-view capture timestamps, model hash and processing
time. There is no metric transform. Preview tokens bind boxes to their exact
images. GUI evidence expires after one second without updates; camera failures
stop detection. Logs stop at 128 MiB; preview images remain bounded. Detection
does not record phone telemetry. Manual trial recording is a separate control.
The capture-clock label is an unverified headset clock assumption, not a mapping
to phone or XR timestamps.

## Development

```bash
sudo apt-get install python3-opencv
python3 frame/pack/fetch-model.py frame/build/detector
python3 frame/desktop/phone_detection.py --model frame/build/detector/object_detection_yolox_2022nov.onnx --self-test
python3 frame/tests/test_phone_detection.py
```

`--image /path/to/photo.jpg` performs offline grayscale inference. The packaged
app forwards `-- --detect --self-test` and `-- --detect --image /path/to/photo.jpg`.
There is no training framework, cloud inference or first-run download.

Pinned metadata: [yolox.json](../models/yolox.json). The upstream model and adapted
preprocessing/decoding are Apache-2.0; retain [LICENSE.YOLOX](../models/LICENSE.YOLOX).
Weights remain in ignored build output and the generated executable rather than Git.
