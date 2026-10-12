"""Make the runtime image relocatable before archiving it (build time only)."""
import os
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
for directory, subdirs, filenames in os.walk(root, followlinks=False):
    for name in subdirs + filenames:
        path = Path(directory) / name
        if path.is_symlink():
            target = os.readlink(path)
            if target.startswith("/"):
                local = root / target.lstrip("/")
                path.unlink()
                path.symlink_to(os.path.relpath(local, path.parent))
loaders = list((root / "usr/lib").glob("*-linux-gnu/ld-linux-*.so.*"))
if len(loaders) != 1:
    raise SystemExit(f"expected one bundled ELF loader, found {loaders}")
(root.parent / "loader.txt").write_text(loaders[0].name + "\n")
# Keep /usr/share/doc copyright files and /usr/share/common-licenses in rootfs.
# Their symlinks are now relative too. No compiler or development SDK is copied.
