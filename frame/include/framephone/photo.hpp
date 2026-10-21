#pragma once
#include "framephone/planar_pose.hpp"
#include <memory>

namespace framephone {
// A reference coordinate is normalized by photo width, centered, with Y up.
// Stereo, not a user-entered target width, establishes the metric scale.
struct PhotoMatch {
    ImagePoint reference;
    std::array<ImagePoint, 2> pixels; // native distorted pixels
};
struct PhotoPose {
    std::string status{"lost"}, reason{"insufficient_stereo_matches"};
    std::string backend{"rootsift"};
    std::string tracking_method{"feature_matching"};
    std::string pose_method{"triangulated_features"};
    std::size_t search_view{}, search_view_count{1};
    Pose pose;
    double width_m{}, height_m{}, coverage{};
    std::size_t reference_features{}, stereo_candidates{}, triangulated{}, pose_inliers{};
    std::array<std::size_t, 2> scene_features{}, descriptor_matches{};
    std::array<std::size_t, 2> view_inliers{};
    // Per-view evidence is diagnostic only; it does not imply an accepted 3D pose.
    std::array<std::vector<ImagePoint>, 2> view_points, search_outline;
    std::vector<PhotoMatch> matches;
    std::array<std::vector<ImagePoint>, 2> outline;
};
PhotoPose estimate_photo_pose(const StereoRig &, const StereoPair &,
                              const std::vector<PhotoMatch> &, double aspect,
                              const PhotoPose *initial = nullptr);

// CPU SIFT with cached multi-scale references and calibrated perspective views.
// Every result is a fresh stereo measurement. No temporal pose is fabricated.
class PhotoTracker {
  public:
    PhotoTracker(CameraFrame reference, StereoRig rig);
    ~PhotoTracker();
    PhotoTracker(const PhotoTracker &) = delete;
    PhotoTracker &operator=(const PhotoTracker &) = delete;
    PhotoPose update(const StereoPair &);
    const StereoRig &rig() const;

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace framephone
