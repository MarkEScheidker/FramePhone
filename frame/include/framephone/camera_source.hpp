#pragma once

#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace framephone {

enum class PixelFormat { Gray8 };
struct RingTransport {
    std::uint64_t frame_number{}, dequeue_monotonic_ns{}, publish_monotonic_ns{};
    std::uint32_t v4l2_sequence{};
    std::uint64_t skipped_since_previous{};
};

// capture_time_ns is in the source's clock domain. Keep that domain explicit;
// Android elapsedRealtime and OpenXR time are not implicitly interchangeable.
struct CameraFrame {
    std::string camera_id;
    std::uint32_t width{};
    std::uint32_t height{};
    std::uint32_t stride_bytes{};
    PixelFormat pixel_format{PixelFormat::Gray8};
    std::uint64_t capture_time_ns{};
    std::string clock_domain;
    std::string calibration_id;
    std::optional<double> exposure_us;
    std::vector<std::uint8_t> pixels;
    std::optional<RingTransport> ring_transport{};

    void validate() const;
};

class CameraSource {
  public:
    virtual ~CameraSource() = default;
    // nullopt means end of stream. Invalid frame data or recording files throw.
    virtual std::optional<CameraFrame> next() = 0;
};

// Directory format is documented in frame/docs/RECORDINGS.md. PGM P5 raster
// files are paired with a manifest; no video decoding or timestamp invention.
class RecordedFrameSource final : public CameraSource {
  public:
    explicit RecordedFrameSource(std::filesystem::path directory);
    std::optional<CameraFrame> next() override;

  private:
    struct Record {
        std::string camera_id;
        std::uint64_t capture_time_ns{};
        std::string clock_domain;
        std::string calibration_id;
        std::optional<double> exposure_us;
        std::filesystem::path image_path;
    };
    std::vector<Record> records_;
    std::size_t cursor_{};
};

} // namespace framephone
