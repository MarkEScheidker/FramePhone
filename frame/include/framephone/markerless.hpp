#pragma once

#include "framephone/stereo.hpp"

namespace framephone {

// Body B is centered in the measured body/case, X right, Y toward the physical
// top, Z through the front. Body dimensions are distinct from active-display dimensions.
struct PhoneBodyModel {
    double width_m{}, height_m{}, thickness_m{};
    void validate() const;
    // Physical front face: top-left, top-right, bottom-right, bottom-left.
    std::array<Point3, 4> front() const;
};
using BodyCorners = std::array<ImagePoint, 4>;
struct BodyObservation {
    // Native distorted pixels, with explicitly labelled physical top and front.
    std::array<BodyCorners, 2> corners;
};
struct BodyPose {
    // T_HB, body meters -> head right/up/back. Never a world-space transform.
    std::array<double, 9> rotation{};
    std::array<double, 3> translation_m{};
    double rms_px{}, max_error_px{};
};
struct BodyPoseResult {
    std::string status{"lost"}, reason;
    // Candidates are diagnostic unless status == measured. No stale pose reuse.
    std::vector<BodyPose> candidates;
    std::array<std::array<double, 4>, 2> edge_coverage{};
};

class MarkerlessPoseEstimator {
  public:
    MarkerlessPoseEstimator(PhoneBodyModel body, StereoRig rig);
    BodyPoseResult estimate(const StereoPair &pair, const BodyObservation &observation) const;
    const PhoneBodyModel &body() const {
        return body_;
    }
    const StereoRig &rig() const {
        return rig_;
    }
    // Curved polylines in native pixels, sampled along all 12 cuboid edges.
    std::vector<std::vector<ImagePoint>> wireframe(const BodyPose &pose, std::size_t view) const;

  private:
    PhoneBodyModel body_;
    StereoRig rig_;
};

// Conservative, manually associated baseline. Uses OpenCV rectification,
// contours, side-line fitting and joint stereo pose. Requires the whole front
// boundary in both views; it is not yet a partial-occlusion model tracker.
// A failed update latches loss: only an explicit initialize can resume tracking.
class MarkerlessTracker {
  public:
    explicit MarkerlessTracker(MarkerlessPoseEstimator estimator);
    ~MarkerlessTracker();
    MarkerlessTracker(const MarkerlessTracker &) = delete;
    MarkerlessTracker &operator=(const MarkerlessTracker &) = delete;
    BodyPoseResult initialize(const StereoPair &pair, const BodyObservation &observation);
    BodyPoseResult update(const StereoPair &pair);
    bool active() const;

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace framephone
