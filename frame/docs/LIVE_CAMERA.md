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

The broker first uses discovered `VIDIOC_QUERYBUF` buffer identities when they
fully and uniquely match the attached buffers. Otherwise it learns by observing
DMA-synchronized pixel changes. If the initial candidate set cannot converge,
the broker expands to already attached, compatible same-model runs; buffers
positively identified as belonging to another camera are excluded. A fragmented
or shuffled queue can resolve per index only with strong, unique votes. Ties
remain rejected. Small fragments with known QUERYBUF ownership are retained.
The broker also completes verified runs from the camera's queried descriptors:
an unrelated allocation between image planes can otherwise hide one buffer and
leave a 16-buffer queue stuck with 15 candidates. This fix is backported from
[Frametop experimental](https://github.com/Frametop/frametop/commit/723ad4a6b9ac2ecd245a4a392893bceb5174efd4).
The Camera setup log reports candidate expansion; a healthy queue keeps its
original candidate set.

The optional diagnostic tail of each 160-byte
camera descriptor uses offsets 136 (u64 capture events), 144 (u32 candidates),
148 (u32 mapping ready), 152 (u32 current learning events) and 156 (u32 diagnostic
version, currently 1). Older writers leave this region zero; readers ignore
unknown diagnostic versions. Image/sequence offsets and ring version are unchanged.

`framephone-camera --list-ring FILE` lists available stream names, sensor names,
video nodes and actual dimensions.
`framephone-camera --list-cameras --calibration-id ID [--factory-root ROOT]`
lists factory KB4 cameras.

Select only the two physical front streams and their matching calibrations.
The pairer requires increasing timestamps, one shared clock domain, compatible
metadata and capture spread no greater than 3 ms. Capture-clock identity and
factory mapping still require hardware verification.

The fiducial CLI consumes the ring path and camera mapping from its session
file. Its live no-pair timeout is five seconds; each pose comes from the current
synchronized pair and tag decode. See [headset setup](HEADSET_TEST.md) and
[fiducial sessions](FIDUCIAL_TRACKING.md).
