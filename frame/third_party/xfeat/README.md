# XFeat / LighterGlue static-photo experiment

Upstream: https://github.com/verlab/accelerated_features
Pinned revision: `e92685f57f8318b18725c5c8c0bd28c7fe188d9a`.

[manifest.json](manifest.json) pins the source archive, official XFeat/LighterGlue
weights and CPU PyTorch 2.8.0 wheels for CPython 3.12 on Linux AMD64/ARM64 by SHA-256.
The build-time fetcher copies only `model.py`, `interpolator.py`, `xfeat.py`,
`lighterglue.py`, the weights and upstream Apache-2.0 LICENSE. It creates an empty
`modules/__init__.py` for deterministic local imports. No model download or Torch
Hub repository load is performed on the headset.

The package retains the upstream files, manifest and LICENSE under
`share/framephone/xfeat`; this provenance note is under
`share/framephone/third_party/xfeat`. Original source/weights are unmodified.
The original FramePhone code remains MIT licensed.

FramePhone's worker uses the official extraction/matching implementations with
CPU execution, two Torch threads, cached 240/480-pixel reference scales, spatially
balanced matching budgets and native geometry validation. It disables Kornia
0.7.2 point pruning because unrelated images can prune the point set to zero and
fail an empty reduction. Assignment confidence remains enabled. It additionally
checks that the pinned checkpoint supplies every LighterGlue learned parameter.

Kornia 0.7.2, kornia_rs 0.1.9 and their pinned support packages are installed only
inside the packaged runtime. Wheel license/metadata directories are retained in
`opt/framephone/python`, including PyTorch's own third-party notices; Ubuntu
package notices remain under `usr/share/doc`. See
`frame/pack/requirements-photo.txt` in the source repository.

This is a CPU inference prototype. It increases download/extraction size and
does not establish Frame acquisition reliability, speed or physical accuracy.
