#pragma once
#include "framephone/stereo.hpp"

namespace framephone {
struct PlanarTarget {
    double width_m{}, height_m{}, plane_z_m{};
    void validate() const;
    std::array<Point3, 4> front() const;
};
using PlanarCorners = std::array<ImagePoint, 4>;
struct PlanarObservation {
    // Decoded physical TL/TR/BR/BL in native distorted pixels.
    std::array<PlanarCorners, 2> corners;
};
struct Pose {
    std::array<double, 9> rotation{};
    std::array<double, 3> translation_m{};
    double rms_px{}, max_error_px{};
};
struct PoseResult {
    std::string status{"lost"}, reason;
    // Candidates are diagnostic unless status == measured.
    std::vector<Pose> candidates;
};
class PlanarPoseEstimator {
  public:
    PlanarPoseEstimator(PlanarTarget target, StereoRig rig);
    PoseResult estimate(const StereoPair &, const PlanarObservation &) const;
    std::vector<std::vector<ImagePoint>> wireframe(const Pose &, std::size_t view) const;
    const StereoRig &rig() const {
        return rig_;
    }

  private:
    PlanarTarget body_;
    StereoRig rig_;
};
} // namespace framephone
