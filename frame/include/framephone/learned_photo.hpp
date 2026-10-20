#pragma once
#include "framephone/photo.hpp"
#include <functional>

namespace framephone {
// Static-photo experiment: official XFeat/LighterGlue worker, calibrated tiled
// views and the same native stereo acceptance gates as the baseline.
class LearnedPhotoTracker {
  public:
    LearnedPhotoTracker(CameraFrame reference, StereoRig rig, std::function<bool()> cancelled = {});
    ~LearnedPhotoTracker();
    LearnedPhotoTracker(const LearnedPhotoTracker &) = delete;
    LearnedPhotoTracker &operator=(const LearnedPhotoTracker &) = delete;
    PhotoPose update(const StereoPair &);

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace framephone
