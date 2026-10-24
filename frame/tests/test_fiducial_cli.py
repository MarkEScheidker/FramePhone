"""Automatic stereo decode/pose replay: no manual points or initial frame required."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

binary, fixture = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix="framephone-tag-cli-") as folder:
    root = Path(folder)
    session = root / "trial"
    subprocess.run([fixture, "--write-trial", str(session)], check=True)
    def run(output, ok=True):
        result = subprocess.run([binary, "--session", str(session), "--replay", str(session / "motion"),
                                 "--output", str(output)], capture_output=True, text=True)
        assert (result.returncode == 0) == ok, result.stderr + result.stdout
        return [json.loads(line) for line in result.stdout.splitlines()]
    poses = run(root / "output")
    assert [p["status"] for p in poses] == ["measured", "measured", "lost", "measured", "measured"], poses
    assert all(p["schema"] == "framephone-fiducial-pose-v1" and p["transform"] == "T_HM" for p in poses)
    assert all(type(p["processed_host_monotonic_ns"]) is int and p["processed_host_monotonic_ns"] > 0 for p in poses)
    assert not poses[2]["candidates"] and poses[2]["detections"] == [[], []]
    assert all(len(p["detections"][0]) == 1 for p in (poses[0], poses[-1]))
    assert abs(poses[0]["candidates"][0]["translation_m"][2] + .6) < .012
    axes = poses[0]["candidates"][0]["axes"]
    assert len(axes) == 2 and all(len(view) == 3 and all(len(line) == 9 for line in view) for view in axes)
    assert all(view[0][0] == view[1][0] == view[2][0] for view in axes), "pose axes do not share their projected origin"
    assert len(list((root / "output").glob("preview-*"))) == 3
    assert not (session / "corners.json").exists()
    run(root / "output", ok=False)
    config = json.loads((session / "session.json").read_text())
    config["fiducial"]["black_edge_m"] = 0
    (session / "session.json").write_text(json.dumps(config))
    run(root / "invalid", ok=False)
    # A missing installed SteamVR client is a visible helper failure, not a
    # dependency of optical tracking or a silent renderer fallback.
    overlay = Path(binary).with_name("framephone-overlay")
    config["fiducial"]["black_edge_m"] = .06
    (session / "session.json").write_text(json.dumps(config))
    failed = subprocess.run([str(overlay), "--session", str(session)], capture_output=True, text=True,
                            env=dict(os.environ, FRAMEPHONE_OPENVR_LIBRARY=str(root / "missing-client.so")), timeout=10)
    assert failed.returncode != 0 and "Cannot load SteamVR client" in failed.stderr, failed.stderr
print("Automatic single-tag CLI pose, blank loss, reacquisition, bounded previews and scale validation passed")
