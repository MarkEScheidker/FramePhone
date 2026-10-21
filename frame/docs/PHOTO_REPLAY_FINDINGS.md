# First recorded headset photo replay

Analyzed 2026-10-20. This is one debugging trial, not an accuracy benchmark.
The private images and calibration files are excluded from the source release.

## Original recording

- 56 native stereo pairs were saved; 55 had completed diagnostic results.
- Both streams and factory calibration use 1056×1024 pixels.
- No pose was accepted. The 55 reasons were 47 insufficient descriptor matches,
  four insufficient shared stereo feature matches and four failed two-view photo
  verification checks.
- Median reported processing time on Frame was 896 ms. That measurement includes
  recording work; the photo previews update after processing each pair.
- Median gap between recorded capture times was 900 ms (range 833–1000 ms).
  This trial sampled processed pairs, not a full-rate camera stream.
- Median left/right capture timestamp skew was 42 microseconds, maximum 45.
  This does not establish clock alignment with XR poses or phone sensors.
- The head-oriented calibrated views show the photo upright in both cameras.
  The raw camera mounting roll is already handled by rectification. No additional
  quarter-turn correction or changed factory mapping was applied.

Some pairs recognize the reference in both views but choose different reference
landmark identities. For example, pair 13 had 24/19 per-view homography inliers
but only three shared reference identities. The old learned path stopped before
it could use those independently recognized points to locate stereo matches.

## Implemented correction

Use the two verified photo homographies to guide direct, bidirectional normalized
patch correlation between the current camera images. These are measured stereo
observations; the homographies only limit the search. Existing triangulation and
pose checks remain mandatory, including at least 12 surviving stereo points,
12% reference coverage, 2.5-pixel pruning and 1.8-pixel RMS limits.

An alternative joint fit from different points in each view was evaluated and
discarded from the runtime: a synthetic case produced an incorrect angle despite
low pixel error, and linearized uncertainty did not reliably catch that bias.
The shipped change retains actual triangulated correspondences and passes the
existing synthetic angular-accuracy assertions unchanged.

## Replay result and limits

Local replay accepts pairs 13–16 and 34–35. That is six accepted poses among the
same first 55 recorded pairs, compared with zero originally; the extra unfinished
recorded pair remains rejected. Two acquisitions use stereo patch refinement;
four subsequent measurements use the existing temporal patch tracker.

| Pair | Measurement path | Surviving stereo points | Native reprojection RMS |
| --- | --- | --- | --- |
| 13 | Cross-camera patch acquisition | 18 | 1.21 px |
| 14 | Temporal patches | 17 | 1.23 px |
| 15 | Temporal patches | 13 | 1.65 px |
| 16 | Temporal patches | 16 | 1.07 px |
| 34 | Cross-camera patch acquisition | 20 | 1.33 px |
| 35 | Temporal patches | 20 | 1.38 px |

Estimated photo widths are 69.5–71.1 mm. Neither those widths nor the poses have
independent physical ground truth. Local replay timing must not be presented as
headset performance. Most frames still fail acquisition or reacquisition; this
is an incremental recovery improvement, not a usable tracking success rate.
Those sparse capture gaps also limit what replay can establish about a faster
tracker: it cannot reconstruct the intervening frames a live patch tracker
would receive. A new headset trial is required.

The current reference has substantial smooth areas and small detail. Further
trials should compare references with distinctive, larger grayscale features,
and inspect camera exposure, screen footprint and search-region overlap. Keep
one-camera, unrelated-image and inconsistent-stereo negatives in regression tests.
