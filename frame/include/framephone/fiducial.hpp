#pragma once
#include "framephone/planar_pose.hpp"

namespace framephone {
struct TagDetection {
    int id{}, hamming{};
    double margin{};
    PlanarCorners corners;
};
class TagDetector {
  public:
    TagDetector();
    ~TagDetector();
    TagDetector(const TagDetector &) = delete;
    TagDetector &operator=(const TagDetector &) = delete;
    std::vector<TagDetection> detect(const CameraFrame &);

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
// Public deterministic marker raster, including one white quiet cell each side.
CameraFrame render_tag(int id = 0, int cell_pixels = 32);
struct FiducialResult {
    PoseResult pose;
    std::array<std::vector<TagDetection>, 2> detections;
};
class FiducialTracker {
  public:
    FiducialTracker(double black_edge_m, StereoRig rig);
    FiducialResult update(const StereoPair &);
    const PlanarPoseEstimator &estimator() const {
        return estimator_;
    }

  private:
    TagDetector detector_;
    PlanarPoseEstimator estimator_;
};
} // namespace framephone
