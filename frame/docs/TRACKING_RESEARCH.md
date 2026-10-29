# Tracking improvements: evidence and decisions

Research date: 2026-10-25. Hardware reports establish working ARCore tracking,
but not the cause of its remaining jitter. The changes below target identifiable
problems in FramePhone; their physical tuning still needs headset recordings.

## Keep the existing visual–inertial estimator

[ARCore already combines visual features and IMU measurements](https://developers.google.com/ar/develop/fundamentals).
Its output is not an independent camera-only measurement that can simply be
weighted against the same accelerometer. A second naive fusion layer would
reuse correlated evidence without knowing ARCore's uncertainty.

[VINS-Mono](https://github.com/HKUST-Aerial-Robotics/VINS-Mono) illustrates what a
replacement actually entails: bias estimation, preintegration, initialization,
spatial/time calibration, rolling-shutter handling and failure recovery.
[Kalibr's IMU model](https://github.com/ethz-asl/kalibr/wiki/IMU-Noise-Model)
distinguishes rapid noise from changing bias; reliable gravity removal is also
necessary before translating acceleration into position. Replacing ARCore or
increasing raw acceleration's weight is therefore not the next step. Keep raw
sensor recording and verified gyro prediction; calibrate before adding a separate
translational inertial estimator.

## Reduce presentation jitter first

The previous two-pose velocity difference could amplify small position changes.
The previous visual filter also reduced smoothing in response to the magnitude
of its own error, allowing jitter to increase the filter gain. These are code-level
findings; they do not establish that every observed wobble has this cause.

The [1 Euro filter](https://gery.casiez.net/1euro/) provides a suitable pattern:
filter the derivative, then adapt the signal cutoff to speed. FramePhone now uses
that principle for translation and SO(3) rotation, with signed derivative filtering
at 2 Hz. Position cutoff starts at 4 Hz; rotation at 3.5 Hz. Motion raises either
to at most 10 Hz. These settings correspond to roughly 16–45 ms of filter time
constant, not a guaranteed end-to-end delay.

Velocity now fits up to six measured poses within 100 ms, requiring three samples
and at least 20 ms span. Large fit residuals disable translation prediction.
Extrapolation stops at 40 ms/2 cm. None of these values feed registration.

## Acquire during normal movement

Two distinct accepted stereo observations spanning at least 80 ms replace the
500 ms batch. Relative position may vary by 8 cm, provided candidate world
registrations agree within 5 cm/0.12 rad. Stereo skew, calibrated geometry,
reprojection/ambiguity checks, timestamp matching and pose freshness remain.
These thresholds are FramePhone choices, not values claimed by the cited systems.
Faster acquisition accepts more initial alignment uncertainty; it is not a claim
of equivalent accuracy. The interval starts with the first usable observation,
so ARCore startup and camera processing can add time.

## Separate damaged data from missing geometry

[AprilTag's API](https://github.com/AprilRobotics/apriltag/blob/master/apriltag.h)
provides bounded error correction. FramePhone had explicitly disabled it and
rejected every corrected code. It now permits up to two corrected data cells,
with a higher decode-margin requirement for corrected tags. Both cameras must
still agree geometrically. Tests corrupt complete cells in independent rasters.

This does **not** reconstruct an occluded border or corner. A thumb can hide much
more than one image pixel, and a quad detector may fail before decoding begins.
Inventing the missing corner would undermine stereo pose validity.

For the next occlusion step, evaluate a short temporal bridge using existing
[OpenCV pyramidal Lucas–Kanade tracking](https://docs.opencv.org/4.x/dc/d6b/group__video__track.html):
track interior features after a real decode, reject failed forward/backward tracks,
fit a robust transform in factory-undistorted ray coordinates, and stop after a
short gap or insufficient spatial support. Recovered geometry must be labeled
separately and must not count as a new independently decoded observation.
This is a proposal, not an implemented capability or measured success.

Cold acquisition with a permanently covered border needs a different target or
extra visible geometry. [OpenCV marker boards](https://docs.opencv.org/4.x/db/da9/tutorial_aruco_board_detection.html)
explicitly support pose from the visible subset of a known layout. One large
primary plus smaller backup tags is a candidate if the single-tag requirement
changes; it is not enabled here. No neural model or new CV dependency is added.

## Validate on recordings

Compare raw and rendered stationary position/angle spread, movement lag, marker
appearance-to-handoff time, corrected-bit counts and false acquisitions. Test
both data-cell and border/corner covers, several viewing distances, room light,
and walking. Keep startup, detection, registration, filtering and display timing
separate. Faster/smoother display cannot correct long-term disagreement between
two independent maps; that requires optical re-registration and better calibration.
