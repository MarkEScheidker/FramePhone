# Tracked VR rectangle

On the dashboard, start tracking and enable **Show rectangle in VR
(SteamVR)**. A translucent blue rectangle with a bright green outline follows
the latest accepted fiducial position and orientation. It is centered on the
marker at the phone's screen plane. Keep the marker visible.

The renderer uses one flat OpenVR compositor quad. Its width and height come
from the phone's fullscreen pixel dimensions and the same metric marker size
used for optical tracking. Case thickness and body dimensions do not affect it.
Missing screen geometry produces an error instead of an incorrectly sized
fallback. Absolute scale still depends on Android's reported physical DPI.

Only accepted `T_HM` poses drive the rectangle. Lost, stale, stopped, hidden-marker
or disconnected states hide it; reacquisition shows it again. Turning off camera
previews leaves tracking and the VR rectangle active. Turning off the VR checkbox
or stopping tracking destroys the overlay.

The helper loads the installed SteamVR client through the user's OpenVR registry,
with `/opt/steamvr` as a Frame fallback. No additional driver or Frametop installation
is required. FramePhone bundles only Valve's pinned interface header. Startup and
runtime errors appear in **Activity log** and `desktop.log`.

This stage uses **headset-relative placement** directly from the latest optical
pose. The factory head frame is provisionally treated as the runtime HMD frame.
There is no ARCore, IMU prediction, world anchoring or capture-time head-motion
compensation. Move slowly when comparing the rectangle to the physical phone.
The renderer independently validates rigid transforms, rejects pose publications
older than 250 ms, and hides the rectangle when headset tracking is invalid.
Publication freshness does not measure camera exposure age.

The GUI atomically publishes `vr-pose.json` in the tracking session; the helper
reads it without a LAN protocol change. The helper exits when its parent exits
and removes its overlay on shutdown.

On a build machine, `framephone-overlay --self-test` checks pose validation,
freshness, screen sizing and texture without SteamVR. To render on a headset:
`framephone-overlay --session /path/to/tag-trial`. The desktop launches this
automatically. `FRAMEPHONE_OPENVR_LIBRARY` can select an installed client library
for development. Actual compositor visibility and alignment require headset
validation; local tests cannot establish them.

See [OpenVR provenance](../third_party/openvr/README.md).
