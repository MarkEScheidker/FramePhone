# Third-party notices

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

Pose optionally links OpenCV (Apache 2.0 in tested version 4.5.4) and includes
nlohmann JSON headers (MIT, tested version 3.10.5). These development dependencies
live under ignored build output on this machine. Retain upstream and transitive
dependency notices when distributing runtime libraries or binaries.
The packaged Linux runtime installs Ubuntu 24.04 AprilTag/OpenCV packages;
their library and transitive dependency copyright files remain in
`/usr/share/doc` inside the self-extracted runtime. The runtime uses OpenCV 4.6, while the local
development verification described above used 4.5.4.
OpenCV license: https://github.com/opencv/opencv/blob/4.5.4/LICENSE
JSON license: https://github.com/nlohmann/json/blob/v3.10.5/LICENSE.MIT

The desktop diagnostic optionally links SDL2 (zlib license). No SDL source or
font assets are copied into the application sources; its tiny diagnostic alphabet
is defined locally. Development dependencies downloaded into ignored build output
are not a redistributable app package. Retain dependency licenses when packaging
runtime libraries for distribution. SDL license: https://github.com/libsdl-org/SDL/blob/SDL2/LICENSE.txt

The desktop executable also bundles Ubuntu Python/Tk, Tcl/Tk, glibc and their
runtime dependencies. Their copyright files and common licenses remain in the
runtime root. Makeself generates the self-extraction shell header; its GPL-2
copyright and license are retained beside AppRun. This is aggregation with the
MIT application, not a replacement of any dependency's license. The static
broker is built from the included C sources with Ubuntu's libc toolchain.

## AprilTag 3 family data

The synthetic frame generator uses tag36h11 family codewords and bit locations
from AprilRobotics/apriltag v3.4.5 (`tag36h11.c`, `apriltag.c`) to draw the same
markers as the phone app. The family-definition data is covered by the upstream
notice below. The optional detector links a system-installed AprilTag 3 library
and does not vendor that library.

Upstream source: https://github.com/AprilRobotics/apriltag/tree/v3.4.5

Copyright (C) 2013-2016, The Regents of The University of Michigan.
All rights reserved.
This software was developed in the APRIL Robotics Lab under the
direction of Edwin Olson, ebolson@umich.edu. This software may be
available under alternative licensing terms; contact the address above.
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
The views and conclusions contained in the software and documentation are those
of the authors and should not be interpreted as representing official policies,
either expressed or implied, of the Regents of The University of Michigan.

Tag36h11.kt adapts IDs 0-5, bit coordinates, and raster generation from:
https://github.com/AprilRobotics/apriltag/blob/v3.4.5/tag36h11.c
https://github.com/AprilRobotics/apriltag/blob/v3.4.5/apriltag.c

