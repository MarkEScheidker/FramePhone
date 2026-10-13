"""Camera discovery and display of native detector progress.

Physical front/side identity must be checked on the headset. Sensor names and
video numbers alone are not a verified factory-calibration mapping.
"""
import math
import re

MAPPING_VERSION = 2  # Discard the earlier hard-coded front/side assumptions.
DEFAULT_CAMERAS = (("slam_left", "og01a1b_4-0060_video3"),
                   ("slam_right", "og01a1b_4-0036_video0"))


def default_selection(saved, available, preferred):
    """Preserve an available explicit choice; never substitute an unrelated stream."""
    return saved if saved in available else preferred if preferred in available else ""


def numbers(text, count):
    values = [float(value) for value in text.split(",")]
    if len(values) != count or not all(math.isfinite(value) and abs(value) < 1e6 for value in values):
        raise ValueError("invalid visualizer geometry")
    return values


def corners(text, count):
    if text == "-":
        if count:
            raise ValueError("missing corners")
        return []
    values = [numbers(tag, 8) for tag in text.split(";")]
    if len(values) != count:
        raise ValueError("corner count mismatch")
    return [[[tag[i], tag[i + 1]] for i in range(0, 8, 2)] for tag in values]


def mono_streams(text):
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r"(\S+) sensor=(.+) video(\d+) (\d+)x(\d+) flags=0", line.strip())
        if match:
            name, sensor, node, width, height = match.groups()
            if 0 < int(width) <= 16384 and 0 < int(height) <= 16384:
                result[name] = dict(sensor=sensor, node=int(node), width=int(width), height=int(height))
    return result


def factory_cameras(text):
    result = {}
    for line in text.splitlines():
        match = re.match(r"^(\S+)\s+(\d+)x(\d+)\s+KB4\b", line)
        if match:
            name, width, height = match.groups()
            result[name] = dict(width=int(width), height=int(height))
    return result


def ids(text):
    result = [] if text == "-" else [int(value) for value in text.split(",")]
    if any(value < 0 or value > 5 for value in result):
        raise ValueError("unexpected phone marker ID")
    return result


def view(count, markers, width, height, evaluated=True):
    count, width, height = int(count), int(width), int(height)
    markers = ids(markers)
    if count != len(markers) or not 0 < width <= 16384 or not 0 < height <= 16384:
        raise ValueError("invalid detector progress")
    return dict(count=count, ids=markers, width=width, height=height, evaluated=evaluated)


def parse_progress(line):
    """Return validated, bounded numeric fields, or None for ordinary CLI logs."""
    try:
        if line.startswith("detection "):
            fields = dict(token.split("=", 1) for token in line.split()[1:])
            if fields["evaluated"] not in ("0", "1"):
                return None
            snapshot = view(fields["tags"], fields["ids"], fields["width"],
                            fields["height"], fields["evaluated"] == "1")
            if "corners" in fields:
                snapshot["corners"] = corners(fields["corners"], snapshot["count"])
            return {"views": [snapshot]}
        if line.startswith("pair="):
            fields = dict(token.split("=", 1) for token in line.split())
            counts = fields["tags"].split("/")
            views = [view(count, fields[f"{side}_ids"], *fields[f"{side}_size"].split("x"))
                     for count, side in zip(counts, ("left", "right"))]
            if len(counts) != 2 or len(views) != 2:
                return None
            result = {"views": views, "status": fields["status"]}
            for side, snapshot in zip(("left", "right"), views):
                if f"{side}_corners" in fields:
                    snapshot["corners"] = corners(fields[f"{side}_corners"], snapshot["count"])
            if fields["status"] == "accepted":
                distance = float(fields["distance_m"])
                if not math.isfinite(distance) or distance <= 0:
                    return None
                result["distance"] = distance
                if "xyz_H_m" in fields and "rotation_H" in fields:
                    result["translation"] = numbers(fields["xyz_H_m"], 3)
                    result["rotation"] = numbers(fields["rotation_H"], 9)
            return result
    except (KeyError, ValueError):
        return None
    return None


def marker_text(snapshot):
    if snapshot is None:
        return "Waiting for live detection"
    if not snapshot["evaluated"]:
        return "Detection is off"
    if not snapshot["count"]:
        return "0 markers — no tags detected"
    return f"{snapshot['count']} markers — IDs " + ", ".join(map(str, sorted(set(snapshot["ids"]))))


def pose_text(progress):
    if not progress:
        return "No live phone pose"
    status = progress["status"]
    if status == "accepted":
        return f"Phone tracked — distance {progress['distance']:.3f} m"
    if status == "insufficient_tags":
        return "No phone pose — need at least two shared phone markers"
    if status == "ambiguous":
        return "Markers detected — phone pose is ambiguous"
    return "No accepted phone pose — " + status.replace("_", " ")
