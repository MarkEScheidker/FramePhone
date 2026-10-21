"""Real pretrained model + native fisheye/stereo integration; opt-in model test.

Requires fetched model assets (FRAMEPHONE_PHOTO_MODELS), CPU torch/Kornia,
Python OpenCV/NumPy and the native CMake build directory. No network at runtime.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np


binary = Path(sys.argv[1]).resolve()


def run(session, output, backend="xfeat", env=None):
    process = subprocess.run([str(binary/"framephone-photo"), "--backend", backend,
                              "--session", str(session), "--replay", str(session/"motion"),
                              "--output", str(output)], capture_output=True, text=True, timeout=180,env=env)
    poses = [json.loads(line) for line in process.stdout.splitlines()]
    assert process.returncode == 0, ([(p["status"],p["reason"],p["view_inliers"],p["search_view"]) for p in poses], process.stderr[-4000:])
    return poses


def raster(reference, rotation, translation, view, intrinsics):
    """Independent OpenCV inverse-ray image raster, not the tracker projector."""
    width, height, focal = intrinsics
    k = np.array([[focal, 0, (width-1)/2], [0, focal, (height-1)/2], [0, 0, 1.]])
    d = np.array([.02, -.003, .0004, -.00005])
    y, x = np.indices((height, width), dtype=np.float64)
    native = np.stack([x, y], axis=-1).reshape(-1, 1, 2)
    uv = cv2.fisheye.undistortPoints(native, k, d).reshape(-1, 2)
    rays = np.column_stack([uv, np.ones(len(uv))]) @ np.diag([1., -1., -1.]) @ rotation
    origin = (np.array([.032 if view else -.032, 0, 0]) - translation) @ rotation
    with np.errstate(divide="ignore", invalid="ignore"):
        distance = -origin[2] / rays[:, 2]
        p = origin + rays * distance[:, None]
        mapx = (p[:, 0]/.072 + .5) * reference.shape[1] - .5
        mapy = (.5 - p[:, 1]/(.072*reference.shape[0]/reference.shape[1])) * reference.shape[0] - .5
    valid = (distance > 0) & np.isfinite(mapx) & np.isfinite(mapy)
    mapx = np.where(valid, mapx, -100).reshape(height, width).astype(np.float32)
    mapy = np.where(valid, mapy, -100).reshape(height, width).astype(np.float32)
    output = cv2.remap(reference, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=100)
    return cv2.GaussianBlur(output, (3, 3), .45)


with tempfile.TemporaryDirectory(prefix="framephone-learned-test-") as directory:
    root = Path(directory)
    fixture = root / "basic"
    subprocess.run([str(binary/"framephone-photo-tests"), "--write-trial", str(fixture)], check=True)
    basic = run(fixture, root/"basic-results")
    assert [p["status"] for p in basic] == ["measured", "lost", "measured"], [(p["reason"],p["view_inliers"]) for p in basic]
    assert basic[0]["backend"] == "xfeat_lighterglue"
    assert abs(basic[0]["pose"]["translation_m"][2] + .45) < .012
    assert "pose" not in basic[1] and not basic[1]["matches"]
    assert basic[1]["scene_features"] == [0, 0]

    # Keep real model locations, but make reference identities disjoint between
    # views. Acquisition must recover actual image-to-image observations instead
    # of relying on shared IDs or inferred photo corners.
    worker = root/"partition_worker.py"
    desktop = Path(__file__).resolve().parents[1]/"desktop"
    worker.write_text("import sys\nsys.path.insert(0,"+repr(str(desktop))+")\n"
        "import learned_worker as w\noriginal=w.Matcher.pair\n"
        "def pair(self,images,masks):\n"
        "    result=original(self,images,masks)\n"
        "    for bank in result['banks']:\n"
        "        for v in range(2):\n"
        "            bank['matches'][v]=[m for m in bank['matches'][v] if m[0]%2==v]\n"
        "    return result\nw.Matcher.pair=pair\nsys.exit(w.main())\n")
    partition_env=dict(os.environ,FRAMEPHONE_PHOTO_WORKER=str(worker))
    partitioned=run(fixture,root/"partition-results",env=partition_env)
    assert [p["status"] for p in partitioned]==["measured","lost","measured"],[(p['reason'],p['view_inliers']) for p in partitioned]
    assert partitioned[0]["pose_method"]=="stereo_patch_refinement"
    assert partitioned[0]["pose_inliers"]>=12
    assert abs(partitioned[0]["pose"]["translation_m"][2]+.45)<.012
    inconsistent=root/"inconsistent"
    shutil.copytree(fixture,inconsistent)
    for index in (1,3):
        path=inconsistent/f"motion/pair-{index}-1.pgm"
        image=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
        image=cv2.warpAffine(image,np.float32([[1,0,0],[0,1,40]]),(image.shape[1],image.shape[0]),borderValue=100)
        cv2.imwrite(str(path),image)
    rejected=run(inconsistent,root/"inconsistent-results",env=partition_env)
    assert all(p['status']=='lost' and 'pose' not in p for p in rejected),"accepted inconsistent stereo images"

    # Wider factory cameras; target is beyond the old central perspective view.
    wide = root/"wide"
    shutil.copytree(fixture, wide, ignore=shutil.ignore_patterns("motion"))
    factory = wide/"factory/persist/xrservice.json"
    config = json.loads(factory.read_text())
    for camera in config["cameras"]:
        camera.update(width=1280, height=1024)
        camera["intrinsics"][0].update(fx=430, fy=430, cx=639.5, cy=511.5)
    factory.write_text(json.dumps(config))
    reference = cv2.imread(str(wide/"reference/photo.pgm"), cv2.IMREAD_GRAYSCALE)
    translation = np.array([.42, 0., -.22])
    rotation, _ = cv2.Rodrigues(np.array([0., -np.arctan2(.42, .22), 0.]))
    partial = reference.copy()
    partial[:, :int(partial.shape[1]*.35)] = 100
    unrelated = np.full_like(reference, 180)
    rng = np.random.default_rng(109)
    for _ in range(100):
        p = tuple(map(int, rng.integers([0, 0], [reference.shape[1], reference.shape[0]])))
        cv2.rectangle(unrelated, p, (p[0]+18, p[1]+12), int(rng.integers(0, 255)), -1)
    images = {}
    for name, photo in (("peripheral", reference), ("partial", partial), ("unrelated", unrelated)):
        images[name] = [raster(photo, rotation, translation, view, (1280, 1024, 430)) for view in range(2)]
    for view in range(2):
        noise = rng.normal(0, 3., images["partial"][view].shape)
        images["partial"][view] = np.clip(images["partial"][view]*.6 + 40 + noise, 0, 255).astype(np.uint8)
    images["blank"] = [np.full((1024,1280),100,np.uint8)]*2
    cases = ["peripheral"]*9 + ["partial"]*9 + ["unrelated"]*4 + ["blank"]*3 + ["peripheral"]*12
    motion = wide/"motion"; motion.mkdir()
    lines = ["framephone-recording-v1"]
    for index, case in enumerate(cases):
        for view, name in enumerate(("slam_left", "slam_right")):
            path = f"pair-{index}-{view}.pgm"
            cv2.imwrite(str(motion/path), images[case][view])
            lines.append(f"{name}\t{1_000_000_000+index*33_333_333+view*100000}\tsynthetic\tsynthetic-factory-v1\t-\t{path}")
    (motion/"manifest.tsv").write_text("\n".join(lines)+"\n")
    poses = run(wide, root/"wide-results")
    for name in ("peripheral", "partial"):
        measured = [p for p,case in zip(poses,cases) if case == name and p["status"] == "measured"]
        assert measured, (name, [(p["reason"],p["view_inliers"],p["stereo_candidates"],p["search_view"]) for p,case in zip(poses,cases) if case == name])
        for p in measured:
            assert p["search_view"] > 0
            assert np.linalg.norm(np.array(p["pose"]["translation_m"])-translation) < .025
            assert abs(p["pose"]["width_m"]-.072) < .012
            estimated = np.array(p["pose"]["rotation"]).reshape(3,3)
            angle = np.arccos(np.clip((np.trace(estimated.T@rotation)-1)/2,-1,1))
            assert angle < .3, angle
    for p,case in zip(poses,cases):
        if case in ("blank", "unrelated"):
            assert p["status"] == "lost" and "pose" not in p, (case,p)
    assert any(p["status"] == "measured" and p["tracking_method"] == "normalized_patches"
               for p,case in zip(poses,cases) if case == "partial"), "partial view never used local tracking"
    assert poses[-1]["status"] == "measured", "did not reacquire peripheral image"
    # Missing assets fail explicitly, without a SIFT fallback or runtime download.
    bad_env = dict(os.environ, FRAMEPHONE_PHOTO_MODELS=str(root/"missing-models"))
    failed = subprocess.run([str(binary/"framephone-photo"),"--model-self-test"], env=bad_env,
                            capture_output=True,text=True,timeout=30)
    assert failed.returncode != 0 and "learned photo worker" in failed.stderr, failed.stderr
print("Learned static-photo integration passed: real weights, disjoint reference IDs, inconsistent-stereo rejection, pose, peripheral search, partial/noisy view, negatives, loss/recovery and missing assets.")
