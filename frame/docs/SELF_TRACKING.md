# Phone self-tracking as an alternative architecture

Assessment date: 2026-10-15. Proposed experiment only; not implemented.

Update 2026-10-16: the [fixed-photo stereo precursor](PHOTO_TRACKING.md) is now
implemented for headset trials. ARCore, continuous capture and world alignment
remain proposed work.

See [the detailed component research and implementation plan](SCREEN_CONTENT_TRACKING_PLAN.md)
for the preferred screen-content registration architecture and milestones.

ARCore already estimates its physical camera's 6DoF pose using camera features
and inertial measurements. A phone facing the user can use its rear camera to
observe the room, rather than requiring the headset to recognize a phone in
monochrome images. An XR component on Frame can obtain the headset pose from
its runtime. Neither ARCore nor a headset-pose publisher is wired into this app.

## Independent maps need registration

Sending two position vectors does not establish their physical relationship.
Each tracking session starts with its own origin and orientation. Observing the
same room does not automatically make the maps or anchors interchangeable.

Let W be a chosen headset world reference, H the headset, A a persistent phone
anchor reference and P the phone's calibrated screen/body frame. After solving
the alignment T_WA, relative pose is:

`T_HP(t) = inverse(T_WH(t)) * T_WA * T_AP(t)`

Both poses must refer to the same physical time. ARCore reports the physical
camera pose, so its rigid camera-to-screen/body offset and axis convention must
be incorporated into T_AP. Do not treat camera center as screen/body center.

Possible registration methods include a brief on-screen tag during calibration,
a common external target or a known physical docking pose. A permanent marker
is not required for continued self-tracking after registration. A single shared
position alone does not determine the orientation alignment.

## Preferred registration: match the phone's actual screen content

Owner requirement: pull an ordinary phone from a pocket and use it, without
external trackers, attached markers or a permanent on-screen fiducial. The
proposed direction is ARCore motion tracking plus opportunistic registration
using the actual streamed display as the known planar visual target. This is
technically plausible but has not been implemented or measured on Frame.

The phone would send timestamped display captures and anchored ARCore poses.
Frame would keep a short display-reference history, match features from those
references to its two front camera images and reject inconsistent matches with
RANSAC. ORB and SIFT are existing CPU feature-extraction candidates to benchmark;
no phone-category detector or per-phone NN training is required for this trial.
Preprocess references for the camera's effective grayscale resolution and
contrast. A homography is valid in undistorted image coordinates, not across an
uncorrected wide-angle image. Match processing must respect the existing KB4
calibration and camera-to-headset extrinsics.

Use matched display pixels as known planar points, not just a guessed bounding
box. Mapping them into metric coordinates requires the active display's actual
width/height, capture crop, scaling and orientation; phone body dimensions alone
are insufficient. Calibrated stereo can potentially estimate active display size
automatically from matched points; reported DPI is only an unverified prior.
Fit calibrated planar PnP hypotheses, verify against the other
front camera and refine jointly. Reject weak spatial coverage, high reprojection
error, inconsistent depth or ambiguous orientation. Phone camera-to-screen
extrinsics are also needed to compare this screen pose with ARCore camera pose.

For an accepted observation at time t, the alignment is:

`T_WA = T_WH(t) * T_HP_visual(t) * inverse(T_AP(t))`

Fuse several consistent observations rather than trusting a single noisy planar
solution. ARCore supplies motion between accepted visual observations; later
screen matches provide alignment checks/corrections. Lack of a screen match
alone does not invalidate healthy ARCore tracking. ARCore tracking loss or a
new session requires recovery/re-registration, not indefinite IMU extrapolation.

Timing requires clock-offset estimation, headset pose history at camera exposure
time and ARCore pose interpolation. A capture timestamp is not necessarily the
physical display presentation time. Display-reference history accommodates
transport delay and UI changes but does not by itself solve display/scanout
timing; start acquisition with slow or stationary motion and measure the error.

First optical benchmark: show ordinary static launcher/settings/photo content,
save the exact reference image and a synchronized front-camera pair, then attempt
automatic matching and calibrated pose estimation offline. Measure acquisition
rate, false matches, reprojection consistency and CPU cost at realistic distance
and angles. Test brightness, glare, repeated icons/text, partial hand occlusion
and display scan bands. Blank/protected captures offer no dependable reference;
continue valid ARCore prediction until useful content becomes visible again.
Do not claim infrared-camera compatibility or real-time speed before this test.

This optical benchmark and the background ARCore experiment below are separate
gates before implementing a complete fusion/rendering pipeline. MediaProjection
consent and foreground-service setup still apply; pocket extraction is the
intended behavior after session setup, not a promise of silent camera/capture
startup without Android permissions or user consent.

ARCore can revise world coordinates as mapping improves. Compute phone pose
relative to a persistent anchor using camera/anchor poses from the same frame,
instead of assuming raw ARCore world coordinates remain fixed forever. Track
session/anchor IDs, runtime recenter events, relocalization, validity and drift.
Recalibrate or apply verified corrections when alignment becomes invalid.

## LAN architecture

The phone would send timestamped anchored pose, tracking state and session
identity over the existing authenticated link. Frame can keep its own headset
poses locally, estimate clock relationships and compose the relative transform.
Sending the headset pose back to the phone is optional; both directions do not
need to run a separate pose filter. Existing raw IMU diagnostics can remain.
This replaces heavy headset phone detection for continuous motion, not the
need for coordinate registration or tracking-loss handling.

## First experiment: app switching

The owner requires other apps and the launcher/home screen to stay usable and
recordable. Validate that requirement before building alignment/rendering:

1. On the actual ARCore-supported phone, start a user-visible camera foreground
   service while the app is in the foreground, with the required camera permission.
2. Keep the ARCore update/render pipeline active without occupying the screen.
   Confirm pose updates continue across Home and several non-camera apps.
3. Test camera contention, feature/light loss, phone sleep, thermal load and
   recovery. Another app using the camera can pause ARCore tracking.
4. Validate whole-display MediaProjection alongside that service. This has no
   marker overlay to remove, but capture consent/lifecycle is still separate.
5. Only after this passes, implement a calibration transform and compare the
   relative screen pose to independent measurements while moving both devices.

Android permits continuing camera access through a correctly started camera
foreground service, but that is not proof that a particular ARCore integration
and OEM device will sustain background tracking. A standard Activity sample's
onPause lifecycle is insufficient. Shared Camera means sharing with the same
app's Camera2 pipeline; it does not promise simultaneous access by arbitrary apps.

This approach avoids custom NN training and permanent on-screen fiducials.
It does not guarantee unlimited tracking, permanent registration or low-latency
world alignment. It needs ARCore device support, visible environment features,
time alignment and recovery behavior.

Primary references:
- [ARCore visual-inertial motion tracking](https://developers.google.com/ar/develop/fundamentals)
- [Physical camera pose](https://developers.google.com/ar/reference/java/com/google/ar/core/Camera)
- [World-coordinate adjustments](https://developers.google.com/ar/reference/java/com/google/ar/core/Pose)
- [OpenXR reference spaces](https://registry.khronos.org/OpenXR/specs/1.0/man/html/XrReferenceSpaceType.html)
- [Android camera foreground-service rules](https://developer.android.com/develop/background-work/services/fgs/service-types)
- [ARCore tracking failure reasons](https://developers.google.com/ar/reference/java/com/google/ar/core/TrackingFailureReason)
- [ARCore Shared Camera scope](https://developers.google.com/ar/develop/java/camera-sharing)
- [OpenCV known-image feature matching and homography](https://docs.opencv.org/4.x/d1/de0/tutorial_py_feature_homography.html)
- [OpenCV calibrated planar pose estimation](https://docs.opencv.org/4.x/d5/d1f/calib3d_solvePnP.html)
- [OpenCV fisheye projection and undistortion](https://docs.opencv.org/4.x/db/d58/group__calib3d__fisheye.html)
- [Android display capture and consent](https://developer.android.com/media/grow/media-projection)
