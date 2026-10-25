"""The application's fixed front-camera pair and discovery validation."""
import re

# Confirmed physical front pair for the supported headset configuration.
FRONT_CAMERAS = (("slam_left", "og01a1b_4-0060_video3"),
                 ("slam_right", "og01a1b_4-0036_video0"))


def validate_front_cameras(factories, streams):
    for side, (calibration, stream) in zip(("Front left", "Front right"), FRONT_CAMERAS):
        if calibration not in factories:
            raise ValueError(f"{side} factory calibration is unavailable")
        if stream not in streams:
            raise ValueError(f"{side} stream {stream} is unavailable")
        source, factory = streams[stream], factories[calibration]
        if (source["width"], source["height"]) != (factory["width"], factory["height"]):
            raise ValueError(f"{side} stream dimensions do not match its factory calibration")


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
