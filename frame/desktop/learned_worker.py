#!/usr/bin/env python3
"""Persistent, offline CPU XFeat/LighterGlue inference for native photo tracking.

IPC: big-endian uint32 JSON length, JSON header, then explicitly sized Gray8 data.
Replies use the same JSON framing, without binary payloads. No socket or download.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

os.environ["CUDA_VISIBLE_DEVICES"] = ""

# The relocatable .run installs its Python wheels here. Source development can
# instead use an ordinary virtualenv/PYTHONPATH without modifying host packages.
bundled = Path(__file__).resolve().parents[1] / "python"
if bundled.is_dir():
    sys.path.insert(0, str(bundled))


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:
            raise EOFError("incomplete photo worker request")
        data.extend(part)
    return bytes(data)


def read_message(stream):
    first = stream.read(4)
    if not first:
        return None
    if len(first) != 4:
        raise ValueError("truncated photo worker header")
    size, = struct.unpack("!I", first)
    if not 0 < size <= 65536:
        raise ValueError("photo worker header exceeds limit")
    return json.loads(read_exact(stream, size))


def send_message(stream, message):
    data = json.dumps(message, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("photo worker response exceeds limit")
    stream.write(struct.pack("!I", len(data)) + data)
    stream.flush()


class Matcher:
    def __init__(self, model_root, reference):
        import torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        def no_download(*args, **kwargs):
            raise RuntimeError("Runtime model downloads are disabled; rebuild the bundled models")
        torch.hub.load_state_dict_from_url = no_download
        import cv2
        import numpy as np
        cv2.setNumThreads(2)
        manifest = json.loads((model_root / "manifest.json").read_text())
        for name, digest in manifest["weights"].items():
            if hashlib.sha256((model_root / "weights" / name).read_bytes()).hexdigest() != digest:
                raise ValueError("Bundled photo model hash mismatch: " + name)
        sys.path.insert(0, str(model_root))
        from modules.xfeat import XFeat
        from modules.lighterglue import LighterGlue
        self.torch, self.cv, self.np = torch, cv2, np
        self.extractor = XFeat(weights=str(model_root / "weights/xfeat.pt"), top_k=3072)
        self.extractor.dev = torch.device("cpu")
        self.extractor.net.to("cpu").eval()
        self.glue = LighterGlue(weights=str(model_root / "weights/xfeat-lighterglue.pt"))
        self.glue.dev = torch.device("cpu")
        self.glue.net.to("cpu").eval()
        # Kornia 0.7.2 can prune every point on an unrelated image and then fail
        # an empty reduction. Keep the bounded 768-point set; assignment confidence
        # and the native geometric gates still reject unmatched observations.
        self.glue.net.conf.width_confidence = -1
        # Upstream loads with strict=False for compatibility. Verify that this
        # pinned Kornia version actually consumed every learned parameter.
        state = torch.load(model_root / "weights/xfeat-lighterglue.pt", map_location="cpu", weights_only=True)
        for i in range(self.glue.net.conf.n_layers):
            for old, new in ((f"self_attn.{i}", f"transformers.{i}.self_attn"),
                             (f"cross_attn.{i}", f"transformers.{i}.cross_attn")):
                state = {key.replace(old, new): value for key, value in state.items()}
        state = {key.replace("matcher.", ""): value for key, value in state.items()}
        missing = set(dict(self.glue.net.named_parameters())) - set(state)
        if missing:
            raise ValueError("LighterGlue weights/runtime mismatch: " + ", ".join(sorted(missing)[:5]))
        self.aspect = reference.shape[0] / reference.shape[1]
        self.banks = []
        for edge in (240, 480):
            factor = min(1., edge / max(reference.shape))
            size = (round(reference.shape[1] * factor), round(reference.shape[0] * factor))
            if self.banks and self.banks[-1]["image_size"] == size:
                continue
            image = cv2.resize(reference, size, interpolation=cv2.INTER_AREA)
            features = self.features(image)
            if len(features["keypoints"]) >= 12:
                self.banks.append(features)
        if not self.banks:
            raise ValueError("Photo has too few learned features; choose a detailed photo")

    def features(self, image, mask=None):
        offset = (0, 0)
        # Keep a stable extraction grid when the search mask tightens. Cropping
        # changes XFeat's internal resize and can destroy previously good matches.
        valid = image if mask is None else image[mask > 0]
        if valid.size == 0 or int(valid.max()) - int(valid.min()) < 2:
            return {"keypoints": self.torch.empty(0, 2), "scores": self.torch.empty(0),
                    "descriptors": self.torch.empty(0, 64),
                    "image_size": (image.shape[1], image.shape[0]), "offset": offset}
        tensor = self.torch.from_numpy(image.copy()).float()[None, None] / 255.
        data = self.extractor.detectAndCompute(tensor, top_k=3072)[0]
        if mask is not None and len(data["keypoints"]):
            xy = data["keypoints"].round().long()
            valid_xy = (xy[:, 0] >= 0) & (xy[:, 1] >= 0) & (xy[:, 0] < image.shape[1]) & (xy[:, 1] < image.shape[0])
            keep = valid_xy & (self.torch.from_numpy(mask.copy())[
                xy[:, 1].clamp(0, image.shape[0]-1), xy[:, 0].clamp(0, image.shape[1]-1)] > 0)
            data = {key: value[keep] for key, value in data.items()}
        # Reserve spatial coverage instead of filling the matching budget with
        # the most textured part of the room. Extraction remains upstream XFeat.
        buckets = {}
        selected = []
        for index, point in enumerate(data["keypoints"].tolist()):
            cell = (min(7, int(point[0] * 8 / image.shape[1])),
                    min(7, int(point[1] * 8 / image.shape[0])))
            if buckets.get(cell, 0) < 12:
                selected.append(index)
                buckets[cell] = buckets.get(cell, 0) + 1
        chosen = set(selected)
        selected.extend(i for i in range(len(data["keypoints"])) if i not in chosen)
        selected = selected[:768]
        data = {key: value[selected] for key, value in data.items()}
        data["image_size"] = (image.shape[1], image.shape[0])
        data["offset"] = offset
        return data

    def match(self, reference, scene):
        if len(scene["keypoints"]) < 2:
            return []
        torch = self.torch
        data = {}
        for v, features in enumerate((reference, scene)):
            for key in ("keypoints", "descriptors"):
                data[key + str(v)] = features[key][None]
            data["image_size" + str(v)] = torch.tensor(features["image_size"])[None]
        with torch.inference_mode():
            result = self.glue(data, min_conf=.1)
        indices = result["matches"][0].cpu().numpy()
        confidence = result["scores"][0].cpu().numpy()
        ref = reference["keypoints"].cpu().numpy()
        points = scene["keypoints"].cpu().numpy()
        width, height = reference["image_size"]
        return [[int(i), float((ref[i, 0] + .5) / width - .5),
                 float((.5 - (ref[i, 1] + .5) / height) * self.aspect),
                 float(points[j, 0] + scene["offset"][0]),
                 float(points[j, 1] + scene["offset"][1]), float(score)]
                for (i, j), score in zip(indices, confidence)]

    def pair(self, images, masks):
        scenes = [self.features(image, mask) for image, mask in zip(images, masks)]
        return {"scene_features": [len(s["keypoints"]) for s in scenes],
                "banks": [{"reference_features": len(bank["keypoints"]),
                           "matches": [self.match(bank, scene) for scene in scenes]}
                          for bank in self.banks]}


def image(stream, width, height):
    import numpy as np
    if type(width) is not int or type(height) is not int or not 32 <= width <= 1920 or not 32 <= height <= 1920:
        raise ValueError("invalid photo worker image dimensions")
    return np.frombuffer(read_exact(stream, width * height), dtype=np.uint8).reshape(height, width)


def serve(model_root, input_stream, output_stream):
    header = read_message(input_stream)
    if not header or header.get("op") != "init":
        raise ValueError("photo worker expected init")
    reference = image(input_stream, header["width"], header["height"])
    matcher = Matcher(model_root, reference)
    send_message(output_stream, {"op": "ready", "backend": "xfeat_lighterglue",
                                "reference_features": [len(b["keypoints"]) for b in matcher.banks]})
    previous = 0
    while (header := read_message(input_stream)) is not None:
        sequence = header.get("sequence")
        if header.get("op") != "match" or type(sequence) is not int or sequence != previous + 1:
            raise ValueError("invalid photo worker sequence")
        width, height = header["width"], header["height"]
        images = [image(input_stream, width, height) for _ in range(2)]
        masks = [image(input_stream, width, height) for _ in range(2)]
        result = matcher.pair(images, masks)
        send_message(output_stream, {"op": "matches", "sequence": sequence, **result})
        previous = sequence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    output = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    # Also redirect native-library prints, not only Python's sys.stdout.
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    try:
        # Upstream's informational prints must never enter the binary IPC stream.
        with contextlib.redirect_stdout(sys.stderr):
            serve(args.models, sys.stdin.buffer, output)
    except Exception as error:
        send_message(output, {"op": "error", "error": str(error)})
        print("Photo model worker:", error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
