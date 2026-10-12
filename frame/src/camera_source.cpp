#include "framephone/camera_source.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <charconv>
#include <cmath>
#include <fstream>
#include <limits>
#include <map>
#include <sstream>
#include <string_view>

namespace framephone {
namespace {

// tag36h11 family data adapted from AprilTag 3 v3.4.5; see THIRD_PARTY_NOTICES.md.
constexpr std::array<std::uint64_t, 6> kTag36h11Codes{
    0xD7E00984BULL, 0xDDA664CA7ULL, 0xDC4A1C821ULL, 0xE17B470E9ULL, 0xEF91D01B1ULL, 0xF429CDD73ULL,
};
constexpr std::array<int, 36> kBitX{
    1, 2, 3, 4, 5, 2, 3, 4, 3, 6, 6, 6, 6, 6, 5, 5, 5, 4,
    6, 5, 4, 3, 2, 5, 4, 3, 4, 1, 1, 1, 1, 1, 2, 2, 2, 3,
};
constexpr std::array<int, 36> kBitY{
    1, 1, 1, 1, 1, 2, 2, 2, 3, 1, 2, 3, 4, 5, 2, 3, 4, 3,
    6, 6, 6, 6, 6, 5, 5, 5, 4, 6, 5, 4, 3, 2, 5, 4, 3, 4,
};

void draw_tag(CameraFrame &frame, int id, std::uint32_t left, std::uint32_t top,
              std::uint32_t cell_size) {
    std::array<bool, 100> cells{};
    for (int y = 0; y < 10; ++y) {
        for (int x = 0; x < 10; ++x) {
            cells[static_cast<std::size_t>(y * 10 + x)] = x == 0 || x == 9 || y == 0 || y == 9;
        }
    }
    for (std::size_t bit = 0; bit < kBitX.size(); ++bit) {
        const bool white =
            (kTag36h11Codes.at(static_cast<std::size_t>(id)) & (1ULL << (35 - bit))) != 0;
        cells[static_cast<std::size_t>((kBitY[bit] + 1) * 10 + kBitX[bit] + 1)] = white;
    }
    for (std::uint32_t cy = 0; cy < 10; ++cy) {
        for (std::uint32_t cx = 0; cx < 10; ++cx) {
            const auto value = cells[static_cast<std::size_t>(cy * 10 + cx)] ? 255 : 0;
            for (std::uint32_t y = top + cy * cell_size; y < top + (cy + 1) * cell_size; ++y) {
                const auto begin = frame.pixels.begin() +
                                   static_cast<std::ptrdiff_t>(y) * frame.stride_bytes +
                                   static_cast<std::ptrdiff_t>(left + cx * cell_size);
                std::fill_n(begin, cell_size, static_cast<std::uint8_t>(value));
            }
        }
    }
}

std::string manifest_field(std::string_view line, std::size_t &offset) {
    const auto end = line.find('\t', offset);
    const auto field =
        line.substr(offset, end == std::string_view::npos ? line.size() - offset : end - offset);
    offset = end == std::string_view::npos ? line.size() : end + 1;
    return std::string(field);
}

template <typename T> T parse_integer(const std::string &text, const char *field) {
    T value{};
    const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), value);
    if (error != std::errc{} || end != text.data() + text.size())
        throw std::runtime_error(std::string("invalid recording ") + field);
    return value;
}

std::string pgm_token(std::istream &input) {
    while (input) {
        const int next = input.peek();
        if (next == '#') {
            input.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
        } else if (next != EOF && std::isspace(static_cast<unsigned char>(next))) {
            input.get();
        } else {
            break;
        }
    }
    std::string token;
    while (input) {
        const int next = input.peek();
        if (next == EOF || next == '#' || std::isspace(static_cast<unsigned char>(next)))
            break;
        token.push_back(static_cast<char>(input.get()));
    }
    if (token.empty())
        throw std::runtime_error("malformed PGM header");
    return token;
}

std::vector<std::uint8_t> read_pgm(const std::filesystem::path &path, std::uint32_t &width,
                                   std::uint32_t &height) {
    std::ifstream input(path, std::ios::binary);
    if (!input)
        throw std::runtime_error("cannot open recorded image: " + path.string());
    if (pgm_token(input) != "P5")
        throw std::runtime_error("recorded image must be binary PGM P5: " + path.string());
    width = parse_integer<std::uint32_t>(pgm_token(input), "PGM width");
    height = parse_integer<std::uint32_t>(pgm_token(input), "PGM height");
    if (pgm_token(input) != "255")
        throw std::runtime_error("PGM max value must be 255: " + path.string());
    const int separator = input.get();
    if (separator == '\r' && input.peek() == '\n')
        input.get();
    else if (separator == EOF || !std::isspace(static_cast<unsigned char>(separator)))
        throw std::runtime_error("malformed PGM raster separator: " + path.string());
    if (width == 0 || height == 0 || width > 16'384 || height > 16'384 ||
        static_cast<std::uint64_t>(width) * height > 128ULL * 1024 * 1024)
        throw std::runtime_error("recorded image dimensions exceed limits: " + path.string());
    std::vector<std::uint8_t> pixels(static_cast<std::size_t>(width) * height);
    input.read(reinterpret_cast<char *>(pixels.data()),
               static_cast<std::streamsize>(pixels.size()));
    if (input.gcount() != static_cast<std::streamsize>(pixels.size()))
        throw std::runtime_error("truncated PGM raster: " + path.string());
    return pixels;
}

} // namespace

void CameraFrame::validate() const {
    if (camera_id.empty())
        throw std::invalid_argument("camera_id is required");
    if (width == 0 || height == 0)
        throw std::invalid_argument("frame dimensions must be positive");
    if (stride_bytes < width)
        throw std::invalid_argument("Gray8 stride is smaller than width");
    const auto required = static_cast<std::uint64_t>(stride_bytes) * height;
    if (required > pixels.size())
        throw std::invalid_argument("frame pixel buffer is shorter than stride × height");
    if (pixel_format != PixelFormat::Gray8)
        throw std::invalid_argument("only Gray8 frames are supported");
    if (clock_domain.empty())
        throw std::invalid_argument("capture timestamp clock domain is required");
    if (calibration_id.empty())
        throw std::invalid_argument("calibration_id is required");
    if (exposure_us && (!std::isfinite(*exposure_us) || *exposure_us <= 0.0))
        throw std::invalid_argument("exposure_us must be finite and positive");
}

SyntheticFrameSource::SyntheticFrameSource(SyntheticOptions options, std::uint32_t frame_count)
    : options_(std::move(options)), frame_count_(frame_count) {
    if (options_.width < 160 || options_.height < 160 || options_.width > 16'384 ||
        options_.height > 16'384 ||
        static_cast<std::uint64_t>(options_.width) * options_.height > 128ULL * 1024 * 1024 ||
        options_.marker_boundary_px < 8 || options_.marker_boundary_px > 8'192 || frame_count == 0)
        throw std::invalid_argument(
            "synthetic frame dimensions, marker size, and frame count are too small");
    if (options_.marker_boundary_px % 8 != 0)
        throw std::invalid_argument(
            "synthetic tag boundary must be divisible by eight for whole-pixel cells");
    if (options_.frame_period_ns == 0 ||
        static_cast<std::uint64_t>(frame_count - 1) >
            (std::numeric_limits<std::uint64_t>::max() - options_.first_capture_ns) /
                options_.frame_period_ns ||
        options_.camera_id.empty() || options_.calibration_id.empty())
        throw std::invalid_argument("synthetic timestamps and identifiers must be valid");
}

std::optional<CameraFrame> SyntheticFrameSource::next() {
    if (emitted_ == frame_count_)
        return std::nullopt;
    CameraFrame frame{
        .camera_id = options_.camera_id,
        .width = options_.width,
        .height = options_.height,
        .stride_bytes = options_.width,
        .pixel_format = PixelFormat::Gray8,
        .capture_time_ns = options_.first_capture_ns +
                           static_cast<std::uint64_t>(emitted_) * options_.frame_period_ns,
        .clock_domain = "synthetic-monotonic-ns",
        .calibration_id = options_.calibration_id,
        .exposure_us = std::nullopt,
        .pixels = std::vector<std::uint8_t>(
            static_cast<std::size_t>(options_.width) * options_.height, 24),
    };
    // Bright phone display on a dim background, with four true tag36h11 rasters.
    const std::uint32_t screen_left = options_.width / 5;
    const std::uint32_t screen_right = options_.width - screen_left;
    const std::uint32_t screen_top = options_.height / 20;
    const std::uint32_t screen_bottom = options_.height - screen_top;
    for (std::uint32_t y = screen_top; y < screen_bottom; ++y) {
        auto row = frame.pixels.begin() + static_cast<std::ptrdiff_t>(y) * frame.stride_bytes;
        std::fill(row + screen_left, row + screen_right, 210);
    }
    const std::uint32_t cell = options_.marker_boundary_px / 8;
    const std::uint32_t tag_size = cell * 10;
    const std::uint32_t margin = std::max(cell * 2, options_.width / 40);
    if (screen_right - screen_left < tag_size * 2 + margin * 2 ||
        screen_bottom - screen_top < tag_size * 2 + margin * 2)
        throw std::invalid_argument("synthetic tags do not fit frame; lower marker_boundary_px");
    draw_tag(frame, 0, screen_left + margin, screen_top + margin, cell);
    draw_tag(frame, 1, screen_right - margin - tag_size, screen_top + margin, cell);
    draw_tag(frame, 2, screen_right - margin - tag_size, screen_bottom - margin - tag_size, cell);
    draw_tag(frame, 3, screen_left + margin, screen_bottom - margin - tag_size, cell);
    frame.validate();
    ++emitted_;
    return frame;
}

RecordedFrameSource::RecordedFrameSource(std::filesystem::path directory) {
    const auto manifest_path = directory / "manifest.tsv";
    std::ifstream manifest(manifest_path);
    if (!manifest)
        throw std::runtime_error("cannot open recording manifest: " + manifest_path.string());
    std::string line;
    if (!std::getline(manifest, line))
        throw std::runtime_error(
            "unsupported recording manifest; expected framephone-recording-v1");
    if (!line.empty() && line.back() == '\r')
        line.pop_back();
    if (line != "framephone-recording-v1")
        throw std::runtime_error(
            "unsupported recording manifest; expected framephone-recording-v1");
    std::map<std::pair<std::string, std::string>, std::uint64_t> last_time_by_camera_clock;
    while (std::getline(manifest, line)) {
        if (!line.empty() && line.back() == '\r')
            line.pop_back();
        if (line.empty() || line[0] == '#')
            continue;
        std::size_t offset{};
        Record record;
        record.camera_id = manifest_field(line, offset);
        record.capture_time_ns =
            parse_integer<std::uint64_t>(manifest_field(line, offset), "capture timestamp");
        record.clock_domain = manifest_field(line, offset);
        record.calibration_id = manifest_field(line, offset);
        const auto exposure = manifest_field(line, offset);
        if (exposure != "-") {
            std::size_t used{};
            try {
                record.exposure_us = std::stod(exposure, &used);
            } catch (const std::exception &) {
                throw std::runtime_error("invalid recording exposure_us");
            }
            if (used != exposure.size() || !std::isfinite(*record.exposure_us) ||
                *record.exposure_us <= 0.0)
                throw std::runtime_error("invalid recording exposure_us");
        }
        const auto filename = manifest_field(line, offset);
        if (offset != line.size() || record.camera_id.empty() || record.clock_domain.empty() ||
            record.calibration_id.empty() || filename.empty())
            throw std::runtime_error("recording manifest row has missing or extra fields");
        record.image_path = directory / filename;
        if (record.image_path.parent_path() != directory || record.image_path.extension() != ".pgm")
            throw std::runtime_error(
                "recorded image must be a .pgm file in its recording directory");
        const auto clock_key = std::pair{record.camera_id, record.clock_domain};
        const auto previous = last_time_by_camera_clock.find(clock_key);
        if (previous != last_time_by_camera_clock.end() &&
            record.capture_time_ns < previous->second)
            throw std::runtime_error(
                "recording timestamps must be ordered within each camera clock domain");
        last_time_by_camera_clock.insert_or_assign(clock_key, record.capture_time_ns);
        records_.push_back(std::move(record));
    }
    if (records_.empty())
        throw std::runtime_error("recording manifest contains no frames");
}

std::optional<CameraFrame> RecordedFrameSource::next() {
    if (cursor_ == records_.size())
        return std::nullopt;
    const auto &record = records_[cursor_++];
    CameraFrame frame;
    frame.camera_id = record.camera_id;
    frame.capture_time_ns = record.capture_time_ns;
    frame.clock_domain = record.clock_domain;
    frame.calibration_id = record.calibration_id;
    frame.exposure_us = record.exposure_us;
    frame.pixels = read_pgm(record.image_path, frame.width, frame.height);
    frame.stride_bytes = frame.width;
    frame.validate();
    return frame;
}

} // namespace framephone
