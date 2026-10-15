# Front-camera ring input

The desktop's **Enable cameras** starts the bundled Frametop-derived broker via
graphical authorization. It publishes `/run/user/UID/framephone-camera/cam-ring`.
No Frametop installation is needed.

The native reader implements FHRING01 version 1 from the pinned upstream source;
see [provenance](../third_party/frametop/README.md). It uses bounded read-only
copies, sequence checks, dimensions/slot validation and a heartbeat timeout.
Incomplete or overwritten copies are discarded. Replaced/resized rings and
changed descriptors require a new reader. Capture time is not replaced by host
dequeue/publication time.

`framephone-camera --list-ring FILE` lists available stream names, sensor names,
video nodes and actual dimensions.
`framephone-camera --list-cameras --calibration-id ID [--factory-root ROOT]`
lists factory KB4 cameras.

Select only the two physical front streams and their matching calibrations.
The pairer requires increasing timestamps, one shared clock domain, compatible
metadata and capture spread no greater than 3 ms. Capture-clock identity and
factory mapping still require hardware verification.

The markerless CLI consumes the ring path and camera mapping from its session
file. Its live no-pair timeout is five seconds; tracking also rejects excessive
gaps between processed pairs. See [headset setup](HEADSET_TEST.md) and
[markerless sessions](MARKERLESS_DIAGNOSTIC.md).
