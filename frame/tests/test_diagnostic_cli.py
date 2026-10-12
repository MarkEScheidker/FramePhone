"""End-to-end checks of real CLI output, recordings and optional real decoding."""
import csv
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import time


diagnostic = pathlib.Path(sys.argv[1]).resolve()
tracker = pathlib.Path(sys.argv[2]).resolve()


def run(*args, ok=True):
    result = subprocess.run([str(diagnostic), *map(str, args)], capture_output=True, text=True)
    assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
    return result


def rows(path):
    with path.open(newline="") as stream:
        result = list(csv.DictReader(stream))
    assert all(None not in row and all(value is not None for value in row.values()) for row in result)
    return result


with tempfile.TemporaryDirectory(prefix="framephone-cli-") as folder:
    root = pathlib.Path(folder)
    capabilities = run("--capabilities").stdout
    preview = root / "preview.csv"
    run("--headless", "--no-detect", "--frames", 3, "--csv", preview)
    data = rows(preview)
    assert len(data) == 3
    assert all(row["status"] == "preview_only" and row["detection_us"] == "" and row["id"] == "" for row in data)
    original = preview.read_bytes()
    run("--headless", "--no-detect", "--csv", preview, ok=False)
    assert preview.read_bytes() == original, "existing CSV was overwritten"
    for args in [("--frames", "0"), ("--frames", "-1"), ("--frames", "4294967296"),
                 ("--frames", "12x"), ("--frames", "1000001"), ("--fps", "241"),
                 ("--marker-px", "7"), ("--replay",), ("--invalid",),
                 ("--replay", "missing", "--motion"), ("--synthetic", "--replay", "missing"),
                 ("--snapshot", root / "test.bmp"), ("--frametop-ring", "missing"),
                 ("--camera", "left"), ("--phone-layout", "missing"),
                 ("--pose-jsonl", "missing"), ("--frametop-ring", "missing", "--motion")]:
        run("--headless", "--no-detect", *args, ok=False)

    recording = root / "recording"
    subprocess.run([str(tracker), "--synthetic", "3", str(recording)], check=True, capture_output=True)
    # Independent cameras, large integer timestamps and CSV-sensitive camera names.
    manifest = recording / "manifest.tsv"
    lines = manifest.read_text().splitlines()
    expected = []
    for index in range(1, len(lines)):
        fields = lines[index].split("\t")
        fields[0] = 'cam,"one"' if index != 2 else "second"
        fields[1] = str(18446744073709551000 + index)
        fields[2] = "independent-clock" if index == 2 else "first-clock"
        expected.append((fields[0], fields[1], fields[2]))
        lines[index] = "\t".join(fields)
    manifest.write_text("\n".join(lines) + "\n")
    replay_csv = root / "replay.csv"
    run("--headless", "--no-detect", "--replay", recording, "--csv", replay_csv)
    assert [(r["camera_id"], r["capture_timestamp_ns"], r["clock_domain"]) for r in rows(replay_csv)] == expected

    if "AprilTag3=available" in capabilities:
        detected = root / "detected.csv"
        result = run("--headless", "--motion", "--frames", 12, "--blank-every", 4, "--csv", detected)
        assert "9 frames with at least one tag" in result.stdout, result.stdout
        data = rows(detected)
        assert len(data) == 39, len(data)  # Nine four-tag frames, three misses.
        for index in range(1, 13):
            frame = [r for r in data if int(r["frame"]) == index]
            if index % 4 == 0:
                assert len(frame) == 1 and frame[0]["status"] == "no_tags" and frame[0]["id"] == ""
            else:
                assert {r["id"] for r in frame} == {"0", "1", "2", "3"}
                assert all(r["hamming"] == "0" and float(r["decision_margin"]) > 0 for r in frame)
                assert all(0 <= float(r[f"x{c}"]) < 640 and 0 <= float(r[f"y{c}"]) < 480 for r in frame for c in range(4))
        replay_detected = root / "replay-detected.csv"
        run("--headless", "--replay", recording, "--csv", replay_detected)
        assert len(rows(replay_detected)) == 12
    else:
        result = run("--headless", "--frames", 1, ok=False)
        assert "AprilTag 3 is unavailable" in result.stderr

    fixtures = pathlib.Path(__file__).parent / "fixtures"
    pose_args = ["--phone-layout", str(fixtures / "synthetic-phone-layout.json"),
                 "--camera-calibration", str(fixtures / "synthetic-camera.json")]
    has_pose = "pose_6dof=camera_relative" in capabilities and "AprilTag3=available" in capabilities
    if has_pose:
        pose_path = root / "pose.jsonl"
        run("--headless", "--frames", 4, "--blank-every", 2, *pose_args, "--pose-jsonl", pose_path)
        poses = [json.loads(line) for line in pose_path.read_text().splitlines()]
        assert [p["status"] for p in poses] == ["accepted", "insufficient_tags", "accepted", "insufficient_tags"]
        assert all(p["transform"] == "T_CP" and p["calibration_status"] == "synthetic" for p in poses)
        original_pose = pose_path.read_bytes()
        run("--headless", *pose_args, "--pose-jsonl", pose_path, ok=False)
        assert pose_path.read_bytes() == original_pose

    # Independent binary ABI producer: write while the real diagnostic reads.
    # This tests source selection/polling/export, without a headset or broker.
    image = (recording / "frame-0.pgm").read_bytes().split(b"\n", 3)[3]
    assert len(image) == 640 * 480
    slot_bytes = 64 + len(image)
    ring_path = root / "cam-ring"
    ring_bytes = bytearray(1344 + 4 * slot_bytes)
    ring_bytes[:8] = b"FHRING01"
    struct.pack_into("<IIIIQqQ", ring_bytes, 8, 1, 1344, 1, 0, len(ring_bytes), os.getpid(), time.monotonic_ns())
    ring_bytes[96:96+20] = b"synthetic-front-left"
    struct.pack_into("<iIIIIIQQ", ring_bytes, 128, 0, 0, 640, 480, 640, 4, 1344, slot_bytes)
    ring_path.write_bytes(ring_bytes)
    live_csv = root / "live.csv"
    live_pose = root / "live.jsonl"
    live_args = [str(diagnostic), "--headless", "--frametop-ring", str(ring_path), "--frames", "3",
                 "--camera", "synthetic-front-left", "--calibration-id", "synthetic-not-calibrated",
                 "--capture-clock", "independent-live-clock", "--csv", str(live_csv)]
    if has_pose:
        live_args += pose_args + ["--pose-jsonl", str(live_pose)]
    else:
        live_args += ["--no-detect"]
    process = subprocess.Popen(live_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with ring_path.open("r+b", buffering=0) as ring_file:
            n = 0
            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                n += 1
                offset = 1344 + (n % 4) * slot_bytes
                fd = ring_file.fileno()
                os.pwrite(fd, struct.pack("<Q", 2*n+1), offset)
                stamp = 9007199254740993 + n
                os.pwrite(fd, struct.pack("<QQQQIf", n, stamp, 1000+n, 2000+n, n, 100.0), offset+8)
                os.pwrite(fd, image, offset+64)
                os.pwrite(fd, struct.pack("<Q", 2*n+2), offset)
                os.pwrite(fd, struct.pack("<Q", n), 64+104)
                os.pwrite(fd, struct.pack("<Q", time.monotonic_ns()), 40)
                time.sleep(0.04)
        stdout, stderr = process.communicate(timeout=3)
        assert process.returncode == 0, (stdout, stderr)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    live_rows = rows(live_csv)
    assert len({r["frame"] for r in live_rows}) == 3
    assert all(r["clock_domain"] == "independent-live-clock" for r in live_rows)
    for row in live_rows:
        n = int(row["ring_frame"])
        assert int(row["capture_timestamp_ns"]) == 9007199254740993 + n
        assert int(row["dequeue_monotonic_ns"]) == 1000+n and int(row["publish_monotonic_ns"]) == 2000+n
    if has_pose:
        live_poses = [json.loads(line) for line in live_pose.read_text().splitlines()]
        assert len(live_poses) == 3 and all(p["status"] == "accepted" for p in live_poses)
        assert all("ring_transport" in p for p in live_poses)
    # Fresh, valid producer heartbeat but no new frames is a timeout, never EOF.
    struct.pack_into("<Q", ring_bytes, 40, time.monotonic_ns())
    ring_path.write_bytes(ring_bytes)
    result = run("--headless", "--no-detect", "--frametop-ring", ring_path, "--camera", "synthetic-front-left",
                 "--calibration-id", "synthetic-not-calibrated", "--capture-clock", "fixture", "--idle-timeout-ms", 30, ok=False)
    assert "idle timeout" in result.stderr

    (recording / "frame-0.pgm").write_bytes(b"P5\n2 2\n255\n\x00")
    run("--headless", "--no-detect", "--replay", recording, ok=False)

print("Diagnostic CLI checks passed; real detector tested:", "AprilTag3=available" in capabilities)
