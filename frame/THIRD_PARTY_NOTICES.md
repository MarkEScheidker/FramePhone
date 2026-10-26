# Third-party notices

AprilTag 3 is linked for tag36h11 detection. Its BSD-2-Clause notice is retained
in [third_party/apriltag/LICENSE](third_party/apriltag/LICENSE). Android's ID 0
raster is verified against apriltag_to_image and includes the same notice in
[its asset](../phone/app/src/main/assets/APRILTAG_LICENSE.txt). The local test
library is AprilTag 3.3.0; packaged Ubuntu versions may differ. Runtime package
copyright files remain in /usr/share/doc. Source:
https://github.com/AprilRobotics/apriltag

The VR calibration renderer uses the unmodified OpenVR `v2.15.6` header under
BSD-3-Clause. The [license](third_party/openvr/LICENSE) and
[artifact provenance](third_party/openvr/README.md) ship with the application.
The installed SteamVR client is loaded at runtime and is not redistributed.

The read-only ring adapter implements Frametop's FHRING01 v1 byte layout and
sequence protocol, audited at commit `24a86dc02669caaef8386ea5bfeb08fcb2819944`:
https://github.com/Frametop/frametop/blob/24a86dc02669caaef8386ea5bfeb08fcb2819944/hands/camd/fhring.h
The original MIT notice is retained in `third_party/frametop/LICENSE`.
The privileged broker is now vendored and bundled, with local desktop-lifecycle
adaptations. Its additional MIT attribution is retained in
[LICENSE.FrameEyeCameraFeed](modules/camera/broker/LICENSE.FrameEyeCameraFeed).

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
runtime dependencies.
Their copyright files and common licenses remain in the
runtime root. Makeself generates the self-extraction shell header; its GPL-2
copyright and license are retained beside AppRun. This is aggregation with the
MIT application, not a replacement of any dependency's license. The static
broker is built from the included C sources with Ubuntu's libc toolchain.


Bluetooth integration uses Ubuntu's python3-dbus-next (MIT) to access the host
BlueZ service. Its copyright file remains in the bundled runtime's /usr/share/doc;
BlueZ itself is supplied by SteamOS and is not replaced or bundled.
