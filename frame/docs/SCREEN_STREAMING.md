# Encrypted screen streaming

The first streaming prototype is implemented. Android uses public MediaProjection
capture and a hardware MediaCodec H.264 encoder. Frame receives a separate pinned
TLS video connection, decodes through FFmpeg, and displays the latest completed
image on the tracked phone's screen. Headset performance and Android's actual
capture/lock behavior still need device testing.

## Try it

1. Rebuild/install both Android and Frame apps. FFmpeg and its runtime libraries
   are included in the normal Frame executable; no headset package installation
   is required. Existing Bluetooth pairing can be kept.
2. Connect as usual and align the phone until its marker disappears.
3. With FramePhone open on Android, the system screen-sharing approval opens
   automatically after alignment. If another app is open, tap the **FramePhone**
   screen-sharing notification, or return to the app and tap **Share screen**.
4. Approve full-display sharing. Home and other apps should appear on the virtual
   screen. Test scrolling, small text and phone/display rotation.
5. Turn the screen off and unlock again. If Android kept capture authorized,
   streaming resumes after tracking reacquires. If Android ended projection,
   approve a new session when prompted or through the notification.

**Stop sharing** in the app/notification stops capture without stopping tracking.
Disconnect/Forget stops both. System revocation is respected. Declining capture
leaves tracking working and the virtual screen black, without repeated prompts
in the same unlock session. New capture approval always comes from Android.

Android 15 QPR1+ normally stops projection on lock. The app does not deliberately
end projection merely because the display turns off; this test lets the platform
determine what survives. Encoding is suspended while tracking is unavailable,
the marker is visible, the phone is locked or the headset is not worn. Secure
windows can appear blank. See [MediaProjection](https://developer.android.com/media/grow/media-projection)
and [Android lock behavior](https://developer.android.com/about/versions/15/behavior-changes-all#media-projection-status-bar-chip).

## Pipeline and quality

Capture uses a Surface input, avoiding Android CPU pixel readback. Initial limits
are 30 FPS, 12 Mbps, a 1080-pixel short edge, and at most 2 million encoded pixels,
aligned to the hardware encoder. The pixel cap keeps this first RGBA upload path
bounded; a tall portrait phone is typically around 940 pixels wide. These are
requested settings, not measured quality/latency guarantees. Small text and
latency should be evaluated before raising frame rate or resolution.

The encoder requests no B-frames and regular keyframes. A repeat-frame hint helps
start static screens. Resuming or reconnecting requests a new keyframe. Rotation
reconfigures the encoder and resizes the existing virtual display, without
reusing consent to create another projection. Frame rotates decoded pixels back
into the phone's natural screen axes; the tracked surface's physical size stays
unchanged. Encoder/OS behavior must be checked on the actual phone.

Frame first tries the host FFmpeg's `h264_v4l2m2m` decoder on ARM64. If that path
fails it reconnects with software decoding. When host FFmpeg is absent, the
bundled FFmpeg provides software decoding. **A software fallback can increase
CPU load and reduce frame rate.** Frame's phone area reports decoder mode,
resolution, capture wait and connection errors. `FRAMEPHONE_FFMPEG` is an optional
development override. Host decoding runs without the bundle's library variables.

Decoded RGBA lives in a private, mode-0600 file in a mode-0700 `/dev/shm` directory.
This is RAM-backed live IPC, not a screenshot recording. The native renderer
copies a coherent latest frame under a nonblocking shared lock, then submits it
through two hidden/visible OpenVR upload buffers. A new image replaces the old
one only after ImageLoaded, at full opacity. A permanent black fallback clears
stale/revoked video without uploading a replacement black image. Raw sensor
recordings never include video or its authorization token.

This first renderer uses RGBA copies and buffered SetOverlayRaw. It is not a
GPU zero-copy pipeline. Video and pose rendering are independent; a 30 FPS
stream does not lower the headset-rate pose renderer. Source PTS is carried but
is not assumed to share ARCore's verified capture epoch. End-to-end video latency
has not yet been measured. GPU texture interop and decoder tuning are subsequent
work after this device test.

## Security and binary protocol

Bluetooth establishes app trust and the Wi-Fi route. The existing control TLS
profile negotiates `screen_video_v1` only when requested by an updated Frame.
Its descriptor is `{version:1, port:47644, token:<random 256-bit hex>}`. The token
is valid only for that authenticated control session, rotates on control reconnect,
and is removed when control ends. It permits video-only reconnects within that
session. No video token is persisted or written to diagnostic recordings.

Frame checks the saved full phone certificate SHA-256 pin on the video TLS 1.3
connection **before sending the token**. It sends the usual bounded JSON framing:
`{type:screen_video, version:1, session:<control session>, token:<video token>}`.
Android validates the session and token before returning any capture data.
Capture availability replies with `video_wait`, or `video_ready` including codec
`h264`, capture generation, width, height and display rotation (0–3 quarter turns).
There is no plaintext fallback, cloud media relay, ADB requirement or new pairing.

After `video_ready`, each packet is a 16-byte big-endian header followed by bytes:

| Field | Type | Meaning |
| --- | --- | --- |
| length | u32 | Payload bytes, at most 2 MiB |
| flags | u32 | 0 interframe, 1 codec config, 2 keyframe, 4 heartbeat |
| pts | u64 | Encoder presentation timestamp in microseconds; heartbeat uses 1 for active capture, 0 for paused |

H.264 uses Annex-B NAL units. Configuration precedes frames; a receiver joins at
a new keyframe. Heartbeats have no payload. Active-capture heartbeats keep a
static decoded image valid without claiming a new decoded frame. Paused capture
does not renew validity. RAM publication epochs invalidate pending images when
a decoder/capture session ends. Encoded queue overflow closes only video and
resynchronizes at a new keyframe instead of dropping arbitrary reference frames.

Video owns its socket, queues, decoder and watchdog. Invalid optional video
capabilities and video failures do not terminate telemetry. Both channels still
share Wi-Fi airtime, so congestion can affect tracking; bitrate adaptation remains
future work. The current implementation carries video only, without audio or
remote touch injection.

## Validation and references

`test_screen_video.py` covers bounds, private RAM cleanup, static-image validity,
recording redaction, real TLS pin rejection, capture-wait behavior and actual
FFmpeg decoding of generated H.264. The decode case runs when FFmpeg is available;
native CI installs it. `framephone-screen-frames` covers the Python-compatible
header, freshness, epoch changes and nonblocking locking. Android's VideoWireTest
covers framing, exact timestamps, Annex-B conversion and malformed lengths.
These do not establish on-device MediaProjection or compositor performance.

Implementation references:

- [Android MediaCodec](https://developer.android.com/reference/android/media/MediaCodec)
  and [encoder settings](https://developer.android.com/reference/android/media/MediaFormat).
- [Scrcpy architecture](https://github.com/Genymobile/scrcpy/blob/master/doc/develop.md):
  dedicated video/control paths and repeat-frame capture behavior.
- [Frame Control's device tests](https://github.com/saphid/frame-control/blob/main/docs/vr-video.md):
  evidence for the stock Frame FFmpeg/V4L2 and raw-overlay route on its tested OS.
  Those results are not FramePhone performance measurements. No code was copied.
- [WebRTC transport](https://www.rfc-editor.org/rfc/rfc8834.html) and
  [security](https://www.rfc-editor.org/rfc/rfc8827.html) remain options if TCP
  stalls dominate measured latency; capture and rendering are separate components.
