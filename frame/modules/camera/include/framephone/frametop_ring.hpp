#pragma once

#include "framephone/camera_source.hpp"
#include <memory>

namespace framephone {

struct RingOptions {
    std::filesystem::path path;
    std::string camera_name;
    std::string calibration_id;
    // capture_ns is a camera clock, not automatically CLOCK_MONOTONIC or XR time.
    std::string capture_clock_domain;
    std::uint64_t stale_after_ns{3'000'000'000};
};

struct RingFrame {
    CameraFrame image;
    std::uint64_t frame_number{};
    std::uint64_t dequeue_monotonic_ns{};
    std::uint64_t publish_monotonic_ns{};
    std::uint32_t v4l2_sequence{};
    std::uint64_t skipped_since_previous{};
};

struct RingCameraInfo {
    std::string name, sensor;
    std::int32_t node{};
    std::uint32_t width{}, height{}, flags{};
};
// Inspect only the bounded ABI header. No capture or calibration-name inference.
std::vector<RingCameraInfo> list_frametop_cameras(const std::filesystem::path &path);

// Read-only consumer of Frametop FHRING01 v1. Does not launch/install a broker,
// open camera devices, request capabilities, or convert timestamp domains.
// Uses bounded pread copies instead of mmap (a truncated file cannot SIGBUS).
class FrametopRing final {
  public:
    explicit FrametopRing(RingOptions options);
    ~FrametopRing();
    FrametopRing(const FrametopRing &) = delete;
    FrametopRing &operator=(const FrametopRing &) = delete;
    // Empty means no NEW stable frame, not EOF. Caller controls polling/cancel.
    // Stale writer, replacement, malformed ABI or changed geometry throw.
    std::optional<RingFrame> poll();

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace framephone
