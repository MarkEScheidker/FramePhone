"""Replay an independently rasterized distorted photo, including loss/reacquisition."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

tracker, fixture = sys.argv[1:]
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    subprocess.run([fixture,"--write-trial",str(root/"trial")],check=True)
    command=[tracker,"--session",str(root/"trial"),"--replay",str(root/"trial/motion"),"--output",str(root/"run")]
    result=subprocess.run(command,capture_output=True,text=True,timeout=45)
    assert result.returncode==0,(result.stdout,result.stderr)
    poses=[json.loads(line) for line in result.stdout.splitlines()]
    assert [p["status"] for p in poses]==["measured","lost","measured"],[(p["status"],p["reason"],p["view_inliers"]) for p in poses]
    assert all(p["scale_source"]=="factory_calibrated_stereo" and p["alignment_status"]=="not_implemented" for p in poses)
    assert "pose" not in poses[1] and poses[1]["matches"]==[]
    assert abs(poses[0]["pose"]["translation_m"][2]+.45)<.008
    assert (root/"run/poses.jsonl").stat().st_size<128*1024*1024
    assert subprocess.run(command,capture_output=True).returncode!=0
print("Photo replay CLI passed.")
