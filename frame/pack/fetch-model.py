"""Build-time model acquisition. No model download occurs on the headset."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request


def fetch(destination):
    source = Path(__file__).resolve().parents[1] / "models"
    manifest = json.loads((source / "yolox.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / manifest["filename"]
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == manifest["sha256"]:
        return target
    temporary = target.with_suffix(".download")
    digest, length = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(manifest["url"], timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                length += len(chunk)
                if length > manifest["bytes"]:
                    raise ValueError("detector model exceeds its pinned size")
                digest.update(chunk)
                output.write(chunk)
        if length != manifest["bytes"] or digest.hexdigest() != manifest["sha256"]:
            raise ValueError("detector model checksum/size mismatch")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(fetch(parser.parse_args().destination))
