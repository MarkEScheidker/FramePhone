# Tracked VR rectangle

The VR rectangle starts automatically with tracking; there is no visibility or
Start/Stop switch. A translucent blue rectangle with a green outline follows the
phone's accepted pose. Updated phones first acquire a stable optical alignment,
then hide their marker and supply anchored ARCore motion. See
[the handoff test](ARCORE_HANDOFF.md) for prediction, smoothing and validity.

The renderer uses one flat OpenVR compositor quad. Its width and height come
from the phone's fullscreen pixel dimensions and the same metric marker size
used for optical tracking. Case thickness and body dimensions do not affect it.
Missing screen geometry produces an error instead of an incorrectly sized
fallback. Absolute scale still depends on Android's reported physical DPI.

Only valid current poses drive the rectangle. Stale data, tracking loss and
disconnect hide it. Hiding the phone marker after a successful ARCore handoff
keeps the rectangle visible; deliberate phone-side dismissal pauses tracking.
Turning off camera previews leaves tracking and the rectangle active. Native
worker/renderer failures retry automatically with capped backoff.

The helper loads the installed SteamVR client through the user's OpenVR registry,
with `/opt/steamvr` as a Frame fallback. No additional driver or Frametop installation
is required. FramePhone bundles only Valve's pinned interface header. Startup and
runtime errors appear in **Activity log** and `desktop.log`.

The native helper also supports continuous optical tracking from a recorded or
manually prepared session: this uses **headset-relative placement** from the latest optical
pose. The factory head frame is provisionally treated as the runtime HMD frame.
There is no ARCore, IMU prediction, world anchoring or capture-time head-motion
compensation. Move slowly when comparing the rectangle to the physical phone.
The renderer independently validates rigid transforms, rejects pose publications
older than 250 ms, and hides the rectangle when headset tracking is invalid.
Publication freshness does not measure camera exposure age.

The tracker reader atomically publishes `vr-pose.json` in the tracking session; the helper
reads it without a LAN protocol change. The helper exits when its parent exits
and removes its overlay on shutdown.

On a build machine, `framephone-overlay --self-test` checks pose validation,
freshness, screen sizing and texture without SteamVR. To render on a headset:
`framephone-overlay --session /path/to/tag-trial`. The desktop launches this
automatically. `FRAMEPHONE_OPENVR_LIBRARY` can select an installed client library
for development. Actual compositor visibility and alignment require headset
validation; local tests cannot establish them.

See [OpenVR provenance](../third_party/openvr/README.md).
