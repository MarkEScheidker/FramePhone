# Tracked VR calibration surface

Enable **Show tracked screen in VR (SteamVR)** in Marker tracking after starting
the optical tracker. The helper discovers SteamVR through the user's OpenVR path
registry, with `/opt/steamvr` as a Frame fallback. The app bundles only Valve's
pinned interface header, not SteamVR. No additional driver or Frametop install
is required. Source builds include `framephone-overlay` by default.

The object is a thin screen-shaped slab made from six compositor overlay quads.
Its front reproduces the marker and has a green outline; sides/back are blue.
The current fullscreen pixel dimensions and marker black-edge size determine the
screen proportions. Reported case thickness sets only the slab depth. It is not
an independently calibrated phone-body mesh, streamed display, virtual controller
or input device. With an older marker profile the display falls back to the
square marker raster instead of inventing screen proportions.

Only accepted `T_HM` poses drive it. The GUI atomically publishes a minimal local
`vr-pose.json`; lost/stale/stopped/hidden/disconnected states publish no pose.
The renderer checks finite rigid transforms and processing timestamps itself,
hides updates older than 250 ms, checks HMD tracking and destroys its overlays
on shutdown. It exits if the parent desktop dies. Nothing is installed into the
SteamVR runtime. Logs go to Diagnostics and `desktop.log`.

This first renderer deliberately uses **head-relative** transforms. The imported
factory head frame is provisionally treated as the runtime HMD frame. It does
not compensate camera exposure delay or query historical HMD poses, and does not
provide world anchoring. A recent publication is not proof of a recent exposure.
Move slowly when comparing the real marker and virtual surface. Physical origin
and axis alignment, stereo camera identity, display DPI scale and timing must be
validated before using it to calibrate an ARCore world alignment.

The next stage is headset pose history/clock mapping and verified optical-head
alignment, followed by ARCore and camera-to-screen calibration. A registered
SteamVR accessory with a native render model can follow later if needed. This
calibration surface must be checked alongside the dashboard on the real headset;
unit tests cannot prove its visibility/compositing on Frame.

Terminal checks on a build machine:

```bash
framephone-overlay --self-test
framephone-overlay --session /path/to/tag-trial
```

The self-test needs no SteamVR. The second command needs a live pose publication
from that running desktop session. `FRAMEPHONE_OPENVR_LIBRARY` can select an
explicit installed client library for development; normal use needs no override.
See [OpenVR provenance](../third_party/openvr/README.md).
