"""Native session solve/replay, provenance validation and actual image tracking."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

binary, fixture_tool = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix="framephone-body-cli-") as temporary:
    root = Path(temporary)
    session = root / "trial"
    subprocess.run([fixture_tool, "--write-trial", str(session)], check=True)
    def run(*args, ok=True):
        result = subprocess.run([binary, "--session", str(session), *map(str, args)], capture_output=True, text=True)
        assert (result.returncode == 0) == ok, result.stderr + result.stdout
        return [json.loads(line) for line in result.stdout.splitlines()]
    result, = run("--solve")
    assert result["status"] == "measured" and result["transform"] == "T_HB"
    assert abs(result["candidates"][0]["translation_m"][2] + .6) < 1e-6
    assert result["frames"][0]["capture_timestamp_ns"] == 1_000_000_000
    poses = run("--replay", session / "motion", "--output", root / "output")
    assert [p["status"] for p in poses] == ["measured"] * 4 + ["lost"], poses
    assert not poses[-1]["candidates"]
    assert len(list((root / "output").glob("preview-*"))) == 3
    saved = [json.loads(line) for line in (root / "output/poses.jsonl").read_text().splitlines()]
    assert len(saved) == len(poses) and "preview_slot" not in saved[0]
    run("--replay", session / "motion", "--output", root / "output", ok=False)
    corners = json.loads((session / "corners.json").read_text())
    corners["frames"][0]["capture_timestamp_ns"] += 1
    (session / "corners.json").write_text(json.dumps(corners))
    run("--solve", ok=False)
print("Markerless CLI solve, replay, loss, bounded previews and provenance passed")
