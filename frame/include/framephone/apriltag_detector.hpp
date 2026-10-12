#pragma once

#include "framephone/camera_source.hpp"

#include <array>
#include <chrono>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace framephone {

struct ImagePoint {
    double x{};
    double y{};
};

struct TagDetection {
    std::int32_t id{};
    // AprilTag p[0..3]: decoded tag coordinates (-1,+1),(+1,+1),(+1,-1),(-1,-1),
    // Canonical decoded order rotates with the tag; these are not necessarily
    // the current image's TL/TR/BR/BL. Adapt using exported phone raster rotation.
    std::array<ImagePoint, 4> corners{};
    double decision_margin{};
    std::int32_t hamming{};
    std::string camera_id;
    std::uint64_t capture_time_ns{};
};

struct DetectionBatch {
    std::vector<TagDetection> detections;
    std::size_t rejected_unknown_ids{};
    std::chrono::nanoseconds detection_time{};
};

// This class is available only when built with the real AprilTag 3 library.
// The library is never emulated; CMake omits it if the dependency is absent.
class AprilTag36h11Detector {
  public:
    explicit AprilTag36h11Detector(int threads = 1);
    ~AprilTag36h11Detector();
    AprilTag36h11Detector(AprilTag36h11Detector &&) noexcept;
    AprilTag36h11Detector &operator=(AprilTag36h11Detector &&) noexcept;
    AprilTag36h11Detector(const AprilTag36h11Detector &) = delete;
    AprilTag36h11Detector &operator=(const AprilTag36h11Detector &) = delete;

    DetectionBatch detect(const CameraFrame &frame);

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace framephone
