"""Exercise the actual Containerfile archive command with long runtime symlinks.

Requires makeself and GNU tar, as installed in the package/native CI jobs.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
recipe = (root / "frame/pack/Containerfile").read_text()
line, = [line for line in recipe.splitlines() if "&& makeself " in line]
command = shlex.split(line.split("&& ", 1)[1])
assert command[-4:] == ["/payload", "/out/FramePhone.run", "FramePhone", "./AppRun"]

with tempfile.TemporaryDirectory(prefix="framephone-archive-") as directory:
    folder = Path(directory)
    payload = folder / "payload with spaces"
    certificates = payload / "rootfs/usr/share/ca-certificates/mozilla"
    certificates.mkdir(parents=True)
    name = "Autoridad_de_Certificacion_Firmaprofesional_CIF_A62634068.crt"
    (certificates / name).write_text("synthetic certificate\n")
    link = payload / "rootfs/etc/ssl/certs/test.pem"
    link.parent.mkdir(parents=True)
    target = "../../../usr/share/ca-certificates/mozilla/" + name
    assert len(target.encode()) > 100  # exceeds the default ustar link field
    link.symlink_to(target)
    (payload / "AppRun").write_text("#!/bin/sh\nexit 0\n")
    (payload / "AppRun").chmod(0o755)
    archive = folder / "FramePhone.run"
    result = subprocess.run(command[:-4] + [str(payload), str(archive), *command[-2:]],
                            capture_output=True, text=True)
    assert result.returncode == 0, (result.stdout, result.stderr)
    subprocess.run(["sh", str(archive), "--check"], check=True, capture_output=True)
    extracted = folder / "extracted"
    subprocess.run(["sh", str(archive), "--noexec", "--target", str(extracted)],
                   check=True, capture_output=True)
    restored = extracted / link.relative_to(payload)
    assert os.readlink(restored) == target
    assert restored.read_text() == "synthetic certificate\n"

print("Packaged archive preserves and extracts long runtime symlinks.")
