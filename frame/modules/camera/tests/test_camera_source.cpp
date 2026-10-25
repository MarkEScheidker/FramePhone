#include "framephone/camera_source.hpp"

#include <array>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
void check(bool condition, const char *message) {
    if (!condition)
        throw std::runtime_error(message);
}

template <typename Function> void throws(Function &&function, const char *message) {
    try {
        function();
    } catch (const std::exception &) {
        return;
    }
    throw std::runtime_error(message);
}

struct TempDirectory {
    std::filesystem::path path =
        std::filesystem::temp_directory_path() /
        ("framephone-test-" +
         std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    TempDirectory() {
        std::filesystem::create_directories(path);
    }
    ~TempDirectory() {
        std::error_code ignored;
        std::filesystem::remove_all(path, ignored);
    }
};

void write_pgm(const std::filesystem::path &path, std::uint32_t width, std::uint32_t height,
               const std::array<std::uint8_t, 4> &pixels) {
    std::ofstream output(path, std::ios::binary);
    output << "P5\n# fixture\n" << width << ' ' << height << "\n255\n";
    output.write(reinterpret_cast<const char *>(pixels.data()),
                 static_cast<std::streamsize>(pixels.size()));
}

void frame_validation_checks_stride_and_clock_metadata() {
    framephone::CameraFrame frame{
        .camera_id = "camera-0",
        .width = 2,
        .height = 2,
        .stride_bytes = 2,
        .capture_time_ns = 4,
        .clock_domain = "fixture-clock",
        .calibration_id = "cal-v1",
        .exposure_us = std::nullopt,
        .pixels = {1, 2, 3, 4},
    };
    frame.validate();
    frame.stride_bytes = 1;
    throws([&] { frame.validate(); }, "short stride accepted");
    frame.stride_bytes = 2;
    frame.pixels.pop_back();
    throws([&] { frame.validate(); }, "truncated pixel buffer accepted");
}

void recorded_source_preserves_metadata_stride_and_binary_pixels() {
    TempDirectory temp;
    write_pgm(temp.path / "a.pgm", 2, 2, {255, 0, 16, 32});
    write_pgm(temp.path / "b.pgm", 2, 2, {1, 2, 3, 4});
    {
        std::ofstream manifest(temp.path / "manifest.tsv");
        manifest << "framephone-recording-v1\n"
                 << "front-left\t100\tsteam-clock-1\tcal-a\t550.5\ta.pgm\n"
                 << "front-right\t90\tsteam-clock-2\tcal-b\t-\tb.pgm\n";
    }
    framephone::RecordedFrameSource source(temp.path);
    const auto left = source.next();
    const auto right = source.next();
    check(left && right && !source.next(), "recording frame count is wrong");
    check(left->pixels == std::vector<std::uint8_t>({255, 0, 16, 32}),
          "binary first pixel was consumed as PGM whitespace");
    check(left->camera_id == "front-left" && left->capture_time_ns == 100,
          "left camera metadata changed");
    check(left->clock_domain == "steam-clock-1" && left->calibration_id == "cal-a",
          "left calibration metadata changed");
    check(left->exposure_us && *left->exposure_us == 550.5, "exposure metadata changed");
    check(!right->exposure_us && right->clock_domain == "steam-clock-2",
          "optional exposure or independent clock lost");
}

void recorded_source_rejects_timestamp_regression_within_camera_clock() {
    TempDirectory temp;
    {
        std::ofstream manifest(temp.path / "manifest.tsv");
        manifest << "framephone-recording-v1\n"
                 << "cam\t101\tclock\tcal\t-\ta.pgm\n"
                 << "cam\t100\tclock\tcal\t-\tb.pgm\n";
    }
    throws([&] { framephone::RecordedFrameSource source(temp.path); },
           "camera timestamp regression accepted");
}

void recorded_source_rejects_path_traversal_and_truncated_raster() {
    TempDirectory temp;
    {
        std::ofstream manifest(temp.path / "manifest.tsv");
        manifest << "framephone-recording-v1\ncam\t1\tclock\tcal\t-\t../escape.pgm\n";
    }
    throws([&] { framephone::RecordedFrameSource source(temp.path); }, "path traversal accepted");
    {
        std::ofstream manifest(temp.path / "manifest.tsv");
        manifest << "framephone-recording-v1\ncam\t1\tclock\tcal\t-\tshort.pgm\n";
    }
    {
        std::ofstream image(temp.path / "short.pgm", std::ios::binary);
        image << "P5\n2 2\n255\n";
        image.put('\x01');
    }
    framephone::RecordedFrameSource source(temp.path);
    throws([&] { source.next(); }, "truncated PGM accepted");
}
} // namespace

int main() {
    try {
        frame_validation_checks_stride_and_clock_metadata();
        recorded_source_preserves_metadata_stride_and_binary_pixels();
        recorded_source_rejects_timestamp_regression_within_camera_clock();
        recorded_source_rejects_path_traversal_and_truncated_raster();
        std::cout << "All four camera source tests passed.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "Camera source test failed: " << error.what() << '\n';
        return 1;
    }
}
