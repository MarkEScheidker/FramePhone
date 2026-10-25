# Camera module licenses and provenance

FramePhone's C++ frame types, recording reader, ring reader, example and build
files use the [MIT license](LICENSE).

The Linux broker in broker/ derives from Frametop/frametop commit
24a86dc02669caaef8386ea5bfeb08fcb2819944 under the
[Frametop MIT license](broker/LICENSE.Frametop). Its discovery code also retains
the [FrameEyeCameraFeed MIT license](broker/LICENSE.FrameEyeCameraFeed).
Keep all three notices when copying or redistributing this module.

Upstream broker source:
https://github.com/Frametop/frametop/tree/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/camd

The buffer-completion fix is backported from
[Frametop commit 723ad4a6](https://github.com/Frametop/frametop/commit/723ad4a6b9ac2ecd245a4a392893bceb5174efd4).
It restores buffers lost when an unrelated allocation interrupts image-plane
pairing. Local adaptations add authenticated desktop caller handling, a private
FramePhone ring directory and writer lock, parent-owned process lifetime,
complete QUERYBUF index mapping, DMA cache synchronization during learning,
and rejection of allocation blocks with attachment holes.

The read-only C++ consumer implements FHRING01 version 1 from the pinned
fhring.h ABI. It is independent of Frametop's hand tracker. Neither models,
SteamVR, Android code nor OpenCV/AprilTag dependencies are included here.
