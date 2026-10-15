#pragma once
#include "framephone/geometry.hpp"
#include <deque>

namespace framephone {
struct RigCamera {
    CameraCalibration calibration;
    // Factory sourceCamera stays separate from an explicitly mapped ring slug.
    std::string factory_camera_id;
    // T_HC, optical camera -> OpenVR head (right, up, backwards), meters.
    std::array<double, 9> rotation{1, 0, 0, 0, 1, 0, 0, 0, 1};
    std::array<double, 3> origin_m{};
    Point3 ray(ImagePoint pixel) const;
    ImagePoint project(Point3 head, double *optical_depth = nullptr) const;
};
// Explicit root containing persist/{xrservice,device_config}.json. No networking.
// Imported factory data is labelled factory_imported, not hardware verified.
std::map<std::string, RigCamera> load_frametop_calibration(const std::filesystem::path &device_root,
                                                           const std::string &calibration_id);
struct StereoRig {
    std::array<RigCamera, 2> cameras;
};
void validate_stereo_rig(const StereoRig &rig);

struct StereoPair {
    std::array<CameraFrame, 2> frames;
    std::uint64_t skew_ns() const;
};
// Frametop's new-frame / <=3 ms capture-spread policy, bounded to four queued
// frames per camera. Each frame can be consumed once. Requires one shared clock.
class StereoFramePairer {
  public:
    explicit StereoFramePairer(StereoRig rig, std::uint64_t max_skew_ns = 3'000'000);
    void push(CameraFrame frame);
    std::optional<StereoPair> poll();
    std::uint64_t dropped_frames() const {
        return dropped_;
    }

  private:
    StereoRig rig_;
    std::uint64_t max_skew_, dropped_{};
    std::array<std::uint64_t, 2> last_{};
    std::array<std::deque<CameraFrame>, 2> pending_;
    std::string clock_;
};
struct TriangulatedPoint {
    Point3 point;
    double ray_rms_m{}, angle_rad{};
};
std::optional<TriangulatedPoint> triangulate_stereo(const StereoRig &rig,
                                                    const std::array<ImagePoint, 2> &pixels);

} // namespace framephone
