"""Automatic stereo decode/pose replay: no manual points or initial frame required."""
import json
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
    assert not poses[2]["candidates"] and poses[2]["detections"] == [[], []]
    assert all(len(p["detections"][0]) == 1 for p in (poses[0], poses[-1]))
    assert abs(poses[0]["candidates"][0]["translation_m"][2] + .6) < .012
    assert len(list((root / "output").glob("preview-*"))) == 3
    assert not (session / "corners.json").exists()
    run(root / "output", ok=False)
    config = json.loads((session / "session.json").read_text())
    config["fiducial"]["black_edge_m"] = 0
    (session / "session.json").write_text(json.dumps(config))
    run(root / "invalid", ok=False)
print("Automatic single-tag CLI pose, blank loss, reacquisition, bounded previews and scale validation passed")
