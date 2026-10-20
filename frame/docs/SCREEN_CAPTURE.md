# Screen recording and an on-screen marker

Requirement: capture the phone across app switches and the launcher/home screen,
while retaining a large visible fiducial for headset tracking.

This requires whole-display capture. Android 14 single-app sharing captures
only the selected app and does not meet the launcher/app-switching requirement.
Ordinary full-display MediaProjection also includes an ordinary on-screen tag
overlay. There is no supported public MediaProjection parameter to exclude one
overlay while capturing the clean screen content underneath it. FLAG_SECURE is
capture prevention/redaction, not a promise to reveal the covered pixels.

The current marker is a standalone Activity, not a system overlay or screen
recorder. Showing it replaces the foreground content. The app implements no
recording, streaming, hidden screenshot filtering or privileged display control.
Camera trial recording is unrelated to phone screen capture.

A reliable unprivileged design for clean whole-display recording is a **physical
marker** attached to the phone/case. It stays out of the screen's compositor, so
full-display capture can follow app changes and Home normally, subject to
Android's protected-content rules. Its physical size and rigid mounting offset
would need configuration.

Keeping a giant on-screen tag while capturing a clean full display would need
a separately validated architecture, potentially OEM/system-level support.
Do not promise this behavior from single-app capture, a secure overlay, or a
second virtual display alone. No such capability has been tested here.

Platform references:
- [MediaProjection: device display versus selected app](https://developer.android.com/media/grow/media-projection)
- [Secure-window capture prevention](https://developer.android.com/security/fraud-prevention/activities)

The on-screen single tag remains useful for validating camera calibration and
head-relative pose while that product decision is unresolved.
