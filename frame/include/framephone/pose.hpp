#pragma once

#include "framephone/apriltag_detector.hpp"
#include <array>
#include <map>

namespace framephone {
struct Point3 {
    double x{}, y{}, z{};
};
struct PhoneLayout {
    std::string revision;
    // Ordered in AprilTag's canonical p[0..3] order, including raster rotation.
    std::map<int, std::array<Point3, 4>> markers;
};
struct CameraCalibration {
    std::string id, camera_id, model, status;
    std::uint32_t width{}, height{};
    double fx{}, fy{}, cx{}, cy{};
    std::vector<double> distortion;
};
PhoneLayout load_phone_layout(const std::filesystem::path &path);
CameraCalibration load_camera_calibration(const std::filesystem::path &path);

struct PoseCandidate {
    // T_CP: phone meters -> optical camera (X right, Y down, Z forward).
    std::array<double, 9> rotation_row_major{};
    std::array<double, 3> translation_m{};
    double rms_px{};
    std::vector<int> inlier_ids;
};
struct PoseResult {
    std::string status; // accepted, ambiguous, insufficient_tags, rejected
    std::vector<PoseCandidate> candidates;
    // Only accepted poses are usable. Candidates on ambiguous frames are diagnostic.
};
class PlanarPoseEstimator {
  public:
    PlanarPoseEstimator(PhoneLayout layout, CameraCalibration calibration);
    PoseResult estimate(const CameraFrame &frame, const DetectionBatch &detections) const;
    const PhoneLayout &layout() const {
        return layout_;
    }
    const CameraCalibration &calibration() const {
        return calibration_;
    }

  private:
    PhoneLayout layout_;
    CameraCalibration calibration_;
};
// JSONL preserves integer timestamps, source domains and both planar hypotheses.
void write_pose_jsonl(std::ostream &output, const CameraFrame &frame,
                      const PlanarPoseEstimator &estimator, const PoseResult &pose);
} // namespace framephone
