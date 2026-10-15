# Third-party notices

The bundled OpenCV Zoo YOLOX-S COCO model is pinned at revision
`47534e27c9851bb1128ccc0102f1145e27f23f98`; its SHA-256, source URL and size are
recorded in [yolox.json](models/yolox.json). Retain [LICENSE.YOLOX](models/LICENSE.YOLOX)
(Apache-2.0, copyright 2021–2022 Megvii Inc.). Preprocessing/grid decoding in
`desktop/phone_detection.py` adapts that revision's `yolox.py`/`demo.py`; the file
marks its changes and retains Apache-2.0 licensing. This changes neither the
MIT license for original FramePhone code nor other dependency licenses. The
package includes the model, manifest and notice under `share/framephone/models`.
Source: https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/object_detection_yolox
Python OpenCV/NumPy and their transitive Ubuntu copyright notices remain in
the runtime's `/usr/share/doc` and `/usr/share/common-licenses`.

The optional `build-openvr-demo.sh` fetches `openvr.h` from ValveSoftware/openvr tag `v2.15.6` and
checks its SHA-256 before compiling. The OpenVR SDK is licensed under the
3-Clause BSD license; see the [upstream license](https://github.com/ValveSoftware/openvr/blob/v2.15.6/LICENSE).

The read-only ring adapter implements Frametop's FHRING01 v1 byte layout and
sequence protocol, audited at commit `24a86dc02669caaef8386ea5bfeb08fcb2819944`:
https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/camd/fhring.h
The original MIT notice is retained in `third_party/frametop/LICENSE`.
The privileged broker is now vendored and bundled, with local desktop-lifecycle
adaptations. Its additional MIT attribution is retained in
[LICENSE.FrameEyeCameraFeed](third_party/frametop/camd/LICENSE.FrameEyeCameraFeed).

Factory KB4 import/projection, head transforms and ray intersection now adapt
`hands/track/calib.cpp` at that same commit. Stereo pairing adapts the fresh-set
3 ms spread policy in `hands/track/main.cpp`. Adaptation details and source links
are in `third_party/frametop/README.md`; retain that provenance and the MIT notice.
The new rigid-phone fit uses OpenCV solvers rather than Frametop's neural models.

Pose links OpenCV (Apache 2.0 in tested version 4.5.4) and includes
nlohmann JSON headers (MIT, tested version 3.10.5). These development dependencies
live under ignored build output on this machine. Retain upstream and transitive
dependency notices when distributing runtime libraries or binaries.
The packaged Linux runtime installs Ubuntu 24.04 OpenCV packages;
their library and transitive dependency copyright files remain in
`/usr/share/doc` inside the self-extracted runtime. The runtime uses OpenCV 4.6, while the local
development verification described above used 4.5.4.
OpenCV license: https://github.com/opencv/opencv/blob/4.5.4/LICENSE
JSON license: https://github.com/nlohmann/json/blob/v3.10.5/LICENSE.MIT

The desktop executable also bundles Ubuntu Python/Tk, Tcl/Tk, glibc and their
runtime dependencies. Their copyright files and common licenses remain in the
runtime root. Makeself generates the self-extraction shell header; its GPL-2
copyright and license are retained beside AppRun. This is aggregation with the
MIT application, not a replacement of any dependency's license. The static
broker is built from the included C sources with Ubuntu's libc toolchain.

