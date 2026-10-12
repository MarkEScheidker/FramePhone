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

void synthetic_source_emits_deterministic_gray_tags_and_timestamps() {
    framephone::SyntheticFrameSource source({}, 2);
    const auto first = source.next();
    const auto second = source.next();
    check(first.has_value() && second.has_value(), "synthetic source ended early");
    check(first->width == 640 && first->height == 480 && first->stride_bytes == 640,
          "unexpected synthetic image geometry");
    check(first->pixel_format == framephone::PixelFormat::Gray8, "synthetic image is not Gray8");
    check(first->capture_time_ns == 1'000'000'000, "synthetic first timestamp changed");
    check(second->capture_time_ns == 1'033'333'333, "synthetic timestamp cadence changed");
    check(first->clock_domain == "synthetic-monotonic-ns", "synthetic clock domain missing");
    check(first->pixels == second->pixels, "default synthetic frames should be deterministic");
    check(first->pixels[0] == 24, "synthetic background is unexpected");
    // ID 0 top-left raster starts at (144,40): the quiet zone is white; the
    // first black detector-border cell starts 4 px inward on each axis.
    check(first->pixels[40 * first->stride_bytes + 144] == 255, "white quiet border is missing");
    check(first->pixels[44 * first->stride_bytes + 148] == 0, "black tag border is missing");
    const std::array<std::string, 4> official_rows{
        "1111111111/1000000001/1011010101/1001110101/1001100001/1010100001/1001011001/1000010001/"
        "1000000001/1111111111",
        "1111111111/1000000001/1011011001/1001011101/1011110001/1001100001/1010110101/1000100101/"
        "1000000001/1111111111",
        "1111111111/1000000001/1011011101/1001001001/1010000001/1000100101/1000010001/1000111001/"
        "1000000001/1111111111",
        "1111111111/1000000001/1011100101/1000011101/1010011101/1010100101/1011001001/1001100001/"
        "1000000001/1111111111",
    };
    const std::array<std::pair<std::uint32_t, std::uint32_t>, 4> origins{{
        {144, 40},
        {456, 40},
        {456, 400},
        {144, 400},
    }};
    for (std::size_t id = 0; id < official_rows.size(); ++id) {
        std::array<std::string, 10> rows;
        std::size_t start{};
        for (auto &row : rows) {
            const auto end = official_rows[id].find('/', start);
            row = official_rows[id].substr(start, end - start);
            start = end == std::string::npos ? official_rows[id].size() : end + 1;
        }
        for (std::uint32_t cy = 0; cy < 10; ++cy)
            for (std::uint32_t cx = 0; cx < 10; ++cx) {
                const auto x = origins[id].first + cx * 4 + 2;
                const auto y = origins[id].second + cy * 4 + 2;
                const auto expected = rows[cy][cx] == '1' ? 255 : 0;
                check(first->pixels[y * first->stride_bytes + x] == expected,
                      "synthetic tag cell diverges from independent upstream PNG fixture");
            }
    }
    check(source.next() == std::nullopt, "synthetic source exceeded frame count");
}

void synthetic_source_rejects_noninteger_cells_and_unfittable_tags() {
    auto options = framephone::SyntheticOptions{};
    options.marker_boundary_px = 31;
    throws([&] { framephone::SyntheticFrameSource invalid(options, 1); },
           "noninteger tag cells accepted");
    options.marker_boundary_px = 512;
    framephone::SyntheticFrameSource too_large(options, 1);
    throws([&] { too_large.next(); }, "unfittable synthetic tags accepted");
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
        synthetic_source_emits_deterministic_gray_tags_and_timestamps();
        synthetic_source_rejects_noninteger_cells_and_unfittable_tags();
        recorded_source_preserves_metadata_stride_and_binary_pixels();
        recorded_source_rejects_timestamp_regression_within_camera_clock();
        recorded_source_rejects_path_traversal_and_truncated_raster();
        std::cout << "All six camera source tests passed.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "Camera source test failed: " << error.what() << '\n';
        return 1;
    }
}
