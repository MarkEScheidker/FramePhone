#pragma once
#include "framephone/stereo.hpp"
#include <fstream>

namespace framephone {
void write_pgm(const std::filesystem::path &path, const CameraFrame &frame);
// Shared by fiducial live recording and replay.
class StereoRecorder {
  public:
    explicit StereoRecorder(std::filesystem::path directory);
    void write(const StereoPair &pair, std::uint64_t index);

  private:
    std::filesystem::path directory_;
    std::ofstream manifest_;
};
} // namespace framephone
