# Tracked VR phone

The virtual phone starts automatically with tracking. Its opaque pure-black
screen occupies the same calibrated width and height as the physical display.
A dark-grey shell rounds all twelve edges and all eight corners to a 2 mm
radius, with 10 mm of depth behind the screen. A 2.5 mm margin on each side
leaves room for the curves and a narrow flat bezel. These are visual defaults,
not additional phone measurements. The screen remains at the tracked screen-center
plane; the shell never rescales or moves that plane. Screen streaming is not implemented yet.

The back displays tracking state, pose rate, pose age, prediction duration,
gyro activity, opacity and screen dimensions. Its texture refreshes at up to
4 Hz while facing the viewer. Uploads use a hidden second buffer; only a completed
image replaces the visible back. Swaps wait until full opacity to avoid overlapping
translucent surfaces during fades. Phone transforms follow the headset render rate.

Updated phones first acquire a stable optical alignment, then hide their marker
and supply anchored ARCore motion. See [the handoff test](ARCORE_HANDOFF.md)
for prediction, smoothing and validity. New tracking fades in over 250 ms. On
tracking loss the virtual phone fades linearly over 500 ms from its last rendered
pose and current opacity. Fresh bias-corrected gyro samples can continue rotating
it during the fade, provided the phone connection,
ARCore generation and verified clock remain valid. A new marker acquisition alone
does not change the IMU body axes. Missing/stale/gapped samples freeze orientation.
Position holds at the last rendered value; raw accelerometer integration is not
used. Predictions never restore an alignment or acknowledge a hidden marker.
Reacquisition fades back to full opacity over 250 ms without an opacity jump.
An invalid headset pose or tracking origin reset clears presentation immediately
because its reference frame is lost. Normal renderer termination also allows
the fade before exiting.

The renderer builds a convex rounded box from small OpenVR compositor faces:
flat panels, quarter-cylinder edges, and spherical corner patches. Short facets
approximate the 2 mm curves; corner triangles use alpha masks. The renderer
culls faces pointing away from the viewer so the back text and screen cannot
show through the body during the fade. The screen is its own opaque overlay,
ready for a future texture source. No graphics context, font service, additional
driver or Frametop installation is required.

Screen width and height come from the phone's fullscreen pixel dimensions and
the same metric marker size used for optical tracking. Missing geometry produces
an error instead of an incorrectly sized fallback. Absolute scale still depends
on Android's reported physical DPI.

The helper loads the installed SteamVR client through the user's OpenVR registry,
with `/opt/steamvr` as a Frame fallback. FramePhone bundles only Valve's pinned
interface header. Startup and runtime errors appear in **Activity log** and
`desktop.log`. Turning off camera previews leaves tracking and rendering active.
Native worker/renderer failures retry automatically with capped backoff.

The helper also supports continuous optical tracking from a recorded or manually
prepared session, using **headset-relative placement** from the latest optical
pose. The factory head frame is provisionally treated as the runtime HMD frame.
This path has no ARCore, IMU prediction, world anchoring or capture-time head-motion
compensation. Move slowly when comparing the object to the physical phone.
The renderer independently validates rigid transforms and rejects pose publications
older than 250 ms; a lost pose then starts the same fade. Publication freshness
does not measure camera exposure age.

The tracker reader atomically publishes `vr-pose.json` in the tracking session;
the helper reads it without a LAN protocol change. The helper exits when its
parent exits and removes its overlays on shutdown.

On a build machine, `framephone-overlay --self-test` checks pose validation,
freshness, screen sizing and the shell without SteamVR. The CTest
`framephone-phone-presentation` also covers shell dimensions/normals, diagnostic
textures, fade timing, gyro continuation, gaps and recovery. To render on a
headset: `framephone-overlay --session /path/to/tag-trial`. The desktop launches
this automatically. `FRAMEPHONE_OPENVR_LIBRARY` can select an installed client
library for development. Actual compositor visibility and alignment require
headset validation; local tests cannot establish them.

See [OpenVR provenance](../third_party/openvr/README.md).
