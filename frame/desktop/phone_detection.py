# SPDX-License-Identifier: Apache-2.0
"""Pretrained phone acquisition and 2D outline evidence; never a metric pose.

YOLOX preprocessing/grid decoding adapted from OpenCV Zoo yolox.py/demo.py,
revision 47534e27c9851bb1128ccc0102f1145e27f23f98 (Apache-2.0).
FramePhone changes: grayscale input, phone-only filtering, bounded outputs,
ROI contours, ring input and a versioned diagnostic protocol.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import signal
import sys
import time

import cv2 as cv
import numpy as np

MODEL_HASH = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"
MODEL_FILE = "object_detection_yolox_2022nov.onnx"


def decode(output, width, height, threshold=.3):
    """Decode the pinned, non-decoded 640px YOLOX graph into native-pixel boxes."""
    rows = np.asarray(output, dtype=np.float32)
    if rows.shape != (1, 8400, 85):
        raise ValueError(f"Unexpected detector output shape: {rows.shape}")
    rows = rows[0]
    scores = rows[:, 4] * rows[:, 5:85].max(axis=1)
    # A phone probability alone must not override a stronger competing class.
    keep = (scores >= threshold) & (rows[:, 5:85].argmax(axis=1) == 67)
    indices = np.flatnonzero(keep)
    grids, strides = [], []
    for stride in (8, 16, 32):
        yy, xx = np.mgrid[:640 // stride, :640 // stride]
        grids.append(np.stack((xx, yy), axis=-1).reshape(-1, 2))
        strides.extend([stride] * (len(xx) * len(xx)))
    grid, step = np.concatenate(grids)[indices], np.asarray(strides)[indices, None]
    selected = rows[indices]
    centers = (selected[:, :2] + grid) * step
    sizes = np.exp(np.clip(selected[:, 2:4], -20, 20)) * step
    ratio = min(640 / width, 640 / height)
    lower, upper = (centers - sizes / 2) / ratio, (centers + sizes / 2) / ratio
    boxes, confidence = [], []
    for lo, hi, score in zip(lower, upper, scores[indices]):
        if not np.isfinite([*lo, *hi, score]).all():
            continue
        x0, y0 = np.maximum(lo, 0)
        x1, y1 = np.minimum(hi, (width, height))
        if x1 - x0 >= 8 and y1 - y0 >= 8:
            boxes.append([float(x0), float(y0), float(x1 - x0), float(y1 - y0)])
            confidence.append(float(score))
    if not boxes:
        return []
    selected = np.asarray(cv.dnn.NMSBoxes(boxes, confidence, threshold, .45)).reshape(-1)
    results = [{"box_xywh": boxes[i], "confidence": confidence[i]} for i in selected]
    # Largest apparent phone is the acquisition policy, not paired-device identity.
    return sorted(results, key=lambda r: r["box_xywh"][2] * r["box_xywh"][3], reverse=True)[:8]


def outline(gray, box):
    """Visible quadrilateral in a detector ROI. No inferred hidden corners."""
    x, y, w, h = box
    x0, y0 = max(0, int(x - .1 * w)), max(0, int(y - .1 * h))
    x1, y1 = min(gray.shape[1], math.ceil(x + 1.1 * w)), min(gray.shape[0], math.ceil(y + 1.1 * h))
    patch = gray[y0:y1, x0:x1]
    if patch.size == 0:
        return None
    edges = cv.Canny(cv.GaussianBlur(patch, (3, 3), .7), 40, 100)
    contours, _ = cv.findContours(edges, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        area = abs(cv.contourArea(contour))
        if not .35 * w * h <= area <= 1.4 * w * h:
            continue
        quad = cv.approxPolyDP(contour, .025 * cv.arcLength(contour, True), True)
        if len(quad) != 4 or not cv.isContourConvex(quad):
            continue
        points = quad.reshape(4, 2).astype(float) + (x0, y0)
        lengths = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
        if lengths.min() < 10:
            continue
        rx, ry, rw, rh = cv.boundingRect(points.astype(np.float32))
        intersection = max(0, min(rx + rw, x + w) - max(rx, x)) * max(0, min(ry + rh, y + h) - max(ry, y))
        overlap = intersection / (rw * rh + w * h - intersection)
        if overlap < .55:
            continue
        # Longest visible edge gives only an image-plane axis, modulo 180deg.
        i = int(lengths.argmax())
        dx, dy = points[(i + 1) % 4] - points[i]
        axis = (math.degrees(math.atan2(dy, dx)) + 90) % 180 - 90
        candidates.append((overlap, {"corners_px": points.tolist(), "axis_deg_mod180": axis}))
    return max(candidates, key=lambda c: c[0])[1] if candidates else None


class PhoneDetector:
    def __init__(self, model, threshold=.3):
        model = Path(model)
        if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_HASH:
            raise ValueError("Bundled phone model missing or checksum invalid; rebuild the app.")
        self.net = cv.dnn.readNetFromONNX(str(model))
        self.net.setPreferableBackend(cv.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv.dnn.DNN_TARGET_CPU)
        self.threshold = threshold
        cv.setNumThreads(2)

    def detect(self, gray):
        if gray.ndim != 2 or gray.dtype != np.uint8 or not 0 < gray.size <= 16_777_216:
            raise ValueError("Expected a bounded Gray8 camera frame")
        height, width = gray.shape
        ratio = min(640 / width, 640 / height)
        resized = cv.resize(gray, (max(1, int(width * ratio)), max(1, int(height * ratio))))
        padded = np.full((640, 640, 3), 114, dtype=np.uint8)
        padded[:resized.shape[0], :resized.shape[1]] = resized[:, :, None]
        self.net.setInput(cv.dnn.blobFromImage(padded, scalefactor=1.0))
        results = decode(self.net.forward(), width, height, self.threshold)
        for result in results:
            result["outline"] = outline(gray, result["box_xywh"])
        return results


def write_preview(directory, index, frames):
    slot = directory / f"preview-{index % 3}"
    slot.mkdir(exist_ok=True)
    (slot / "token.json").unlink(missing_ok=True)
    for view, (_, _, pgm, _) in enumerate(frames):
        temporary = slot / f"{view}.tmp"
        temporary.write_bytes(pgm)
        temporary.replace(slot / f"{view}.pgm")
    temporary = slot / "token.tmp"
    temporary.write_text(str(index))
    temporary.replace(slot / "token.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--image", type=Path, help="Single local image for offline inference")
    parser.add_argument("--ring", type=Path)
    parser.add_argument("--left")
    parser.add_argument("--right")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    detector = PhoneDetector(args.model)
    if args.self_test:
        assert not detector.detect(np.zeros((480, 640), dtype=np.uint8))
        print("Pretrained phone detector model load/inference passed", flush=True)
        return 0
    if args.image:
        image = cv.imread(str(args.image), cv.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("Cannot read input image")
        print(json.dumps({"schema": "framephone-phone-detection-v1", "detections": detector.detect(image)}), flush=True)
        return 0
    if not args.ring or not args.left or not args.right or args.left == args.right or not args.output:
        parser.error("Provide a ring, two distinct front streams and a new output directory")
    from ring_preview import preview
    args.output.mkdir(parents=True, exist_ok=False)
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    index, previous = 0, None
    last_frame = time.monotonic()
    with (args.output / "detections.jsonl").open("w") as log:
        while not stopped:
            frames = [preview(args.ring, name, metadata=True) for name in (args.left, args.right)]
            if not all(frames):
                if time.monotonic() - last_frame > 5:
                    raise ValueError("No frames from both selected front streams for 5 seconds; enable/refresh cameras.")
                time.sleep(.05)
                continue
            identities = tuple(f[3]["sequence"] for f in frames)
            if identities == previous:
                if time.monotonic() - last_frame > 5:
                    raise ValueError("Camera frames stopped updating")
                time.sleep(.03)
                continue
            previous = identities
            last_frame = time.monotonic()
            started = time.monotonic()
            detections = []
            for width, height, pgm, metadata in frames:
                gray = np.frombuffer(pgm[-width * height:], dtype=np.uint8).reshape(height, width)
                detections.append(detector.detect(gray))
            index += 1
            message = {"schema": "framephone-phone-detection-v1", "status": "detected" if any(detections) else "searching",
                       "reason": "phone_detection_2d_only", "candidates": [], "pair": index,
                       "frames": [{"width": f[0], "height": f[1], **f[3]} for f in frames],
                       "detections": detections, "model_sha256": MODEL_HASH,
                       "processing_ms": (time.monotonic() - started) * 1000}
            log.write(json.dumps(message, allow_nan=False) + "\n")
            log.flush()
            if log.tell() > 128 * 1024 * 1024:
                raise ValueError("128 MiB detection log limit reached; start another trial")
            write_preview(args.output, index, frames)
            print(json.dumps({**message, "preview_slot": index % 3}, allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, cv.error) as error:
        print(f"Phone detection: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
