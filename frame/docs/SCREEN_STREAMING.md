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
3. The connection service attempts to open Android's screen-sharing approval
   after alignment, including from Home or another app, using the existing
   companion association/overlay permission. If Android blocks the launch, tap
   the **FramePhone** screen-sharing notification or **Share screen** in the app.
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

### Touch indicators

Use **Details → Touch indicators → Open settings** on the phone, then enable
**Show taps** in Android Developer options. Android draws the touch circles in
the full-display stream, including Home and other apps. If Developer options is
hidden, enable it by tapping **About phone → Build number** seven times (some
manufacturers put Build number under Software information). This is a global
phone setting; turn it off there when no longer wanted. FramePhone cannot toggle
this private setting with ordinary app permissions. See
[Android's input debugging options](https://developer.android.com/studio/debug/dev-options#input).

### Optional development grant for repeated approval

Normal installation still requires Android's approval for each new projection.
For an owner-controlled development phone, AOSP also recognizes a shell-granted
PROJECT_MEDIA app operation. With USB debugging enabled and the computer approved
on the phone, this is a device-specific option to test:

```bash
adb shell appops set com.example.framephone PROJECT_MEDIA allow
adb shell appops get com.example.framephone PROJECT_MEDIA
```

This gives FramePhone persistent screen-capture authorization, rather than
approval for only one session. AOSP's permission activity can then return a new
projection without a dialog, and its stop controller exempts that app operation
from lock-triggered stopping. FramePhone still pauses transmission while locked
or untracked. Phone builds may restrict this operation; persistence across OS
updates/reinstallation is not guaranteed. It has not been tested on the owner's
phone and is not a permission an ordinary APK can grant itself.

To restore normal prompting, first **Stop sharing** or **Disconnect**, then:

```bash
adb shell appops set com.example.framephone PROJECT_MEDIA default
```

Sources: [AOSP projection permission check](https://github.com/aosp-mirror/platform_frameworks_base/blob/master/services/core/java/com/android/server/media/projection/MediaProjectionManagerService.java),
[permission activity](https://github.com/aosp-mirror/platform_frameworks_base/blob/master/packages/SystemUI/src/com/android/systemui/mediaprojection/permission/MediaProjectionPermissionActivity.java),
and [stop exemptions](https://github.com/aosp-mirror/platform_frameworks_base/blob/master/services/core/java/com/android/server/media/projection/MediaProjectionStopController.java).

## Accessibility capture assessment

Research checked on 2026-11-06; no accessibility service is implemented.
An explicitly user-enabled AccessibilityService can take display screenshots
on Android 11+ without starting a MediaProjection session. The service remains
enabled independently of a projection token, so screenshot capture after unlock
could avoid another projection approval. This does not imply capture of hidden
pre-lock content or permission to capture secure windows.

The limitation is frame rate: the inspected AOSP implementation requires more
than 333 ms between screenshot requests, including per-window requests. That is
approximately 3 FPS at best, before capture/encoding/network costs. This interval
is an implementation detail, not a public performance guarantee. Screenshot
HardwareBuffers would also need a separate encoder input path; they do not provide
MediaProjection's continuous encoder Surface. This could support an optional
slow preview, but is a poor replacement for the current 30 FPS target.

Android 14+'s takeScreenshotOfWindow can capture a window beneath an accessibility
overlay without that overlay. It requires managing the current window rather
than mirroring the complete display, and still has screenshot rate limits.
An accessibility service does not grant persistent MediaProjection consent or a
general exemption from projection ending on lock. Automating the system approval
dialog is not the proposed solution. Play distribution also requires appropriate
accessibility disclosure/declaration and prohibits using the API to work around
platform privacy controls; FramePhone is not currently a disability support tool.

Android has companion app/nearby-device streaming profiles, but their request
permissions are signature/privileged in the inspected AOSP manifest. The special
app-streaming role has projection-stop exemptions; ordinary Bluetooth companion
association does not grant that role. It is not an available shortcut for the
current normally installed APK. Keep MediaProjection for normal streaming and
evaluate screenshot fallback only if a slow, approval-light preview is useful.

Sources: [AccessibilityService API](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService),
[AOSP screenshot interval](https://github.com/aosp-mirror/platform_frameworks_base/blob/master/core/java/android/accessibilityservice/AccessibilityService.java),
[rate enforcement](https://github.com/aosp-mirror/platform_frameworks_base/blob/master/services/accessibility/java/com/android/server/accessibility/AbstractAccessibilityServiceConnection.java),
[projection-stop exemptions](https://github.com/aosp-mirror/platform_frameworks_base/blob/master/services/core/java/com/android/server/media/projection/MediaProjectionStopController.java),
[profile permissions](https://github.com/aosp-mirror/platform_frameworks_base/blob/master/core/res/AndroidManifest.xml),
and [Google Play accessibility policy](https://support.google.com/googleplay/android-developer/answer/10964491).

## Pipeline and quality

Capture uses a Surface input, avoiding Android CPU pixel readback. Initial limits
are 30 FPS, 12 Mbps, a 1080-pixel short edge, and at most 2 million encoded pixels,
aligned to the hardware encoder. The pixel cap keeps this first RGBA upload path
bounded; a tall portrait phone is typically around 940 pixels wide. These are
requested settings, not measured quality/latency guarantees. Small text and
latency should be evaluated before raising frame rate or resolution.

The encoder requests no B-frames, zero additional latency (an optional codec hint),
and regular keyframes. A repeat-frame hint helps
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

Frame supplies access-unit boundaries to FFmpeg so a completed H.264 frame does
not wait for the next captured frame. Software decoding uses slice threading,
and rawvideo output uses one thread and flushes each frame. These avoid extra
frame-thread/output buffering even when hardware decoding is already active.
The Android encoded queue permits short bursts but reconnects at a new keyframe
if a queued packet is over 100 ms old. TCP send/receive buffers are requested at
64 KiB to limit additional backlog; this is not an end-to-end latency guarantee.
Frame reports decoded FPS alongside decoder mode while frames arrive. This rate
does not measure compositor FPS or capture-to-eye latency.

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
FFmpeg decoding of generated H.264. Single-frame and sequential P-frame tests
require publication before a later frame or EOF, including rotation. Decode tests run when FFmpeg is available;
native CI installs it. `framephone-screen-frames` covers the Python-compatible
header, freshness, epoch changes and nonblocking locking. Android's VideoWireTest
covers framing, exact timestamps, Annex-B conversion and malformed lengths.
CapturePromptTest covers blocked background launch recovery, duplicate prevention,
denial/manual retry and unlock behavior.
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
