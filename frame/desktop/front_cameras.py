"""Camera discovery and explicit front-stream selection.

Physical front/side identity must be checked on the headset. Sensor names and
video numbers alone are not a verified factory-calibration mapping.
"""
import re

MAPPING_VERSION = 2  # Discard the earlier hard-coded front/side assumptions.
DEFAULT_CAMERAS = (("slam_left", "og01a1b_4-0060_video3"),
                   ("slam_right", "og01a1b_4-0036_video0"))


def default_selection(saved, available, preferred):
    """Preserve an available explicit choice; never substitute an unrelated stream."""
    return saved if saved in available else preferred if preferred in available else ""


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
