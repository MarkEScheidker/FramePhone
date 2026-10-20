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
    assert poses[1]["reason"]=="too_few_camera_features"
    assert poses[1]["scene_features"]==[0,0] and poses[1]["view_points"]==[[],[]]
    for pose in (poses[0],poses[2]):
        assert pose["stereo_candidates"] >= pose["triangulated"] >= pose["pose_inliers"] >= 12
        assert all(len(points)>=12 for points in pose["view_points"])
        assert all(len(points)>=4 for points in pose["search_outline"])
    assert abs(poses[0]["pose"]["translation_m"][2]+.45)<.008
    assert (root/"run/poses.jsonl").stat().st_size<128*1024*1024
    assert subprocess.run(command,capture_output=True).returncode!=0
print("Photo replay CLI passed.")
