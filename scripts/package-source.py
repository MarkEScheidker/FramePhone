#!/usr/bin/env python3
"""Export reviewable source without local notes, build artifacts or device data."""
import argparse
import fnmatch
import hashlib
import os
from pathlib import Path
import re
import tarfile
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md",
    ".gitignore", ".gitattributes", ".editorconfig", ".clang-format",
)
SOURCE_DIRS = ("phone", "frame", "docs", "scripts", ".github")
LOCAL_DIRS = {
    "build", ".git", ".idea", ".vscode", ".gradle", ".kotlin", ".cxx",
    ".externalNativeBuild", "__pycache__", ".agents", ".codex", ".aws",
    "captures", "recordings", "calibration",
}
LOCAL_FILES = (
    "local.properties", "workspace.txt", "instructions.txt", "HANDOFF.md",
    ".env", ".env.*", "*.iml", "*.jks", "*.keystore", "*.pem", "*.key",
    "*.apk", "*.aab", "*.pyc", "*.log", "*.csv", "*.jsonl", ".DS_Store",
)


def source_files():
    files = [ROOT / name for name in ROOT_FILES]
    for name in SOURCE_DIRS:
        for directory, subdirs, filenames in os.walk(ROOT / name, followlinks=False):
            parent = Path(directory)
            subdirs[:] = sorted(d for d in subdirs
                                if d not in LOCAL_DIRS and not (parent / d).is_symlink())
            for filename in sorted(filenames):
                path = parent / filename
                if path.is_symlink() or any(fnmatch.fnmatchcase(filename, p) for p in LOCAL_FILES):
                    continue
                # Only explicitly synthetic test data may ship factory JSON or images.
                fixture = path.is_relative_to(ROOT / "frame/tests/fixtures")
                if not fixture and (filename in {"xrservice.json", "device_config.json", "phone-layout.json"}
                                    or path.suffix.lower() in {".pgm", ".bmp", ".mp4"}):
                    continue
                files.append(path)
    for path in files:
        if not path.is_file():
            raise ValueError(f"missing source file: {path.relative_to(ROOT)}")
    return sorted(files)


def check_document_links(files):
    """Check relative file links against the actual exported tree, not local notes."""
    included = {p.resolve() for p in files}
    for path in files:
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", path.read_text(encoding="utf-8")):
            target = unquote(target.strip("<>").split("#", 1)[0])
            if not target or ":" in target:
                continue  # Anchors and external links are outside this check.
            linked = (path.parent / target).resolve()
            directory = any(linked in p.parents for p in included)
            if linked not in included and not directory:
                raise ValueError(f"unexported documentation link: {path.relative_to(ROOT)} -> {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "build/dist/framephone-source.tar.gz")
    output = parser.parse_args().output.resolve()
    # Avoid overwriting source/configuration or including the archive in itself.
    if not output.is_relative_to(ROOT / "build") and not output.is_relative_to(ROOT / "frame/build"):
        parser.error("output must be inside build/ or frame/build/")
    files = source_files()
    check_document_links(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for path in files:
            info = archive.gettarinfo(str(path), arcname=str(path.relative_to(ROOT)))
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o755 if path.suffix == ".sh" or path.name == "gradlew" else 0o644
            with path.open("rb") as source:
                archive.addfile(info, source)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name + ".sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"Exported {len(files)} source files: {output}")
    print("Relative documentation links checked; dependencies and local working files excluded.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(f"source export: {error}")
