#!/usr/bin/env python3
"""Build-time-only, hash-checked upstream source/weights and optional CPU wheel."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import tarfile
from urllib.parse import unquote, urlparse
from urllib.request import urlopen


def fetch(url, digest, limit):
    with urlopen(url, timeout=120) as response:
        data = response.read(limit + 1)
    if len(data) > limit or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Upstream size/hash mismatch: " + url)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--torch-wheel", type=Path, help="Also fetch the CPU CPython 3.12 wheel into this directory")
    args = parser.parse_args()
    manifest_path = Path(__file__).resolve().parents[1] / "third_party/xfeat/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    archive = fetch(manifest["source"]["url"], manifest["source"]["sha256"], 64 * 1024 * 1024)
    prefix = "accelerated_features-" + manifest["revision"] + "/"
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        for name in ("LICENSE", "modules/model.py", "modules/interpolator.py", "modules/xfeat.py", "modules/lighterglue.py"):
            entry = source.getmember(prefix + name)
            if not entry.isfile() or entry.size > 1024 * 1024:
                raise ValueError("Invalid upstream source member: " + name)
            path = args.output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source.extractfile(entry).read())
    (args.output / "modules/__init__.py").write_text("")
    weights = args.output / "weights"
    weights.mkdir(exist_ok=True)
    for name, digest in manifest["weights"].items():
        url = f"https://raw.githubusercontent.com/verlab/accelerated_features/{manifest['revision']}/weights/{name}"
        (weights / name).write_bytes(fetch(url, digest, 32 * 1024 * 1024))
    (args.output / "manifest.json").write_bytes(manifest_path.read_bytes())
    if args.torch_wheel:
        wheel = manifest["torch_cp312"][platform.machine()]
        args.torch_wheel.mkdir(parents=True, exist_ok=True)
        name = unquote(Path(urlparse(wheel["url"]).path).name)
        (args.torch_wheel / name).write_bytes(fetch(wheel["url"], wheel["sha256"], 512 * 1024 * 1024))
    print("Prepared pinned XFeat/LighterGlue models:", args.output)


if __name__ == "__main__":
    main()
