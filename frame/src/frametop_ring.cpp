#include "framephone/frametop_ring.hpp"

#include <array>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

namespace framephone {
namespace {
// Fixed little-endian offsets from the pinned Frametop ABI. See LIVE_CAMERA.md
// and THIRD_PARTY_NOTICES.md; no compiler-dependent struct casts or atomics.
constexpr std::size_t header_size = 1344, camera_size = 160, slot_header = 64;
using Header = std::array<std::uint8_t, header_size>;
std::uint64_t le(const std::uint8_t *p, std::size_t size) {
    std::uint64_t value{};
    for (std::size_t i = 0; i < size; ++i)
        value |= std::uint64_t(p[i]) << (8 * i);
    return value;
}
std::string name(const std::uint8_t *p) {
    const auto *end = static_cast<const std::uint8_t *>(std::memchr(p, 0, 32));
    if (!end || end == p)
        throw std::runtime_error("ring camera name is empty or unterminated");
    return {reinterpret_cast<const char *>(p), static_cast<std::size_t>(end - p)};
}
std::uint64_t monotonic_ns() {
    timespec time{};
    if (clock_gettime(CLOCK_MONOTONIC, &time))
        throw std::runtime_error("CLOCK_MONOTONIC failed");
    return std::uint64_t(time.tv_sec) * 1'000'000'000 + std::uint64_t(time.tv_nsec);
}
void read_at(int fd, void *data, std::size_t size, std::uint64_t offset) {
    auto *bytes = static_cast<std::uint8_t *>(data);
    while (size) {
        const auto n = pread(fd, bytes, size, static_cast<off_t>(offset));
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            throw std::runtime_error("ring read failed or file truncated");
        bytes += n;
        size -= static_cast<std::size_t>(n);
        offset += static_cast<std::uint64_t>(n);
    }
}
} // namespace

std::vector<RingCameraInfo> list_frametop_cameras(const std::filesystem::path &path) {
    const int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
        throw std::runtime_error("cannot open ring header: " + path.string());
    struct Close {
        int fd;
        ~Close() {
            close(fd);
        }
    } owner{fd};
    struct stat st {};
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size < static_cast<off_t>(header_size))
        throw std::runtime_error("invalid ring header file");
    Header h{};
    read_at(fd, h.data(), h.size(), 0);
    if (std::memcmp(h.data(), "FHRING01", 8) || le(h.data() + 8, 4) != 1 ||
        le(h.data() + 12, 4) != header_size || le(h.data() + 16, 4) < 1 ||
        le(h.data() + 16, 4) > 8 || le(h.data() + 24, 8) != std::uint64_t(st.st_size))
        throw std::runtime_error("unsupported or malformed ring header");
    std::vector<RingCameraInfo> out;
    for (std::size_t i = 0; i < le(h.data() + 16, 4); ++i) {
        const auto *c = h.data() + 64 + i * camera_size;
        out.push_back({name(c + 32), name(c), static_cast<std::int32_t>(le(c + 64, 4)),
                       static_cast<std::uint32_t>(le(c + 72, 4)),
                       static_cast<std::uint32_t>(le(c + 76, 4)),
                       static_cast<std::uint32_t>(le(c + 128, 4))});
    }
    return out;
}

struct FrametopRing::Impl {
    RingOptions options;
    int fd{-1};
    struct stat identity {};
    Header initial{};
    std::size_t camera_offset{};
    std::uint64_t last_frame{}, last_capture{}, writer_pid{};
    ~Impl() {
        if (fd >= 0)
            close(fd);
    }

    Header header() const {
        struct stat current {
        }, path_stat{};
        if (fstat(fd, &current) || stat(options.path.c_str(), &path_stat) ||
            current.st_ino != path_stat.st_ino || current.st_dev != path_stat.st_dev ||
            current.st_size != identity.st_size)
            throw std::runtime_error("ring replaced or resized; restart the reader");
        Header h{};
        read_at(fd, h.data(), h.size(), 0);
        if (std::memcmp(h.data(), "FHRING01", 8) || le(h.data() + 8, 4) != 1 ||
            le(h.data() + 12, 4) != header_size || le(h.data() + 16, 4) == 0 ||
            le(h.data() + 16, 4) > 8 || le(h.data() + 24, 8) != std::uint64_t(current.st_size))
            throw std::runtime_error("unsupported or malformed Frametop ring header");
        const auto heartbeat = le(h.data() + 40, 8), now = monotonic_ns();
        if (!heartbeat || heartbeat > now || now - heartbeat > options.stale_after_ns)
            throw std::runtime_error("Frametop ring writer heartbeat is stale or invalid");
        return h;
    }
};

FrametopRing::FrametopRing(RingOptions options) : impl_(std::make_unique<Impl>()) {
    if (options.path.empty() || options.camera_name.empty() || options.calibration_id.empty() ||
        options.capture_clock_domain.empty() || !options.stale_after_ns)
        throw std::invalid_argument(
            "ring requires path, camera, calibration ID and capture clock domain");
    auto &s = *impl_;
    s.options = std::move(options);
    s.fd = open(s.options.path.c_str(), O_RDONLY | O_CLOEXEC | O_NONBLOCK);
    if (s.fd < 0)
        throw std::runtime_error("cannot open Frametop ring read-only: " + s.options.path.string());
    if (fstat(s.fd, &s.identity) || !S_ISREG(s.identity.st_mode) ||
        s.identity.st_size < off_t(header_size))
        throw std::runtime_error("Frametop ring must be a regular file with a complete header");
    s.initial = s.header();
    s.writer_pid = le(s.initial.data() + 32, 8);
    std::size_t selected{};
    for (std::size_t i = 0; i < le(s.initial.data() + 16, 4); ++i) {
        const auto offset = 64 + i * camera_size;
        const auto *c = s.initial.data() + offset;
        const auto width = le(c + 72, 4), height = le(c + 76, 4), stride = le(c + 80, 4),
                   slots = le(c + 84, 4);
        const auto start = le(c + 88, 8), bytes = le(c + 96, 8),
                   file_size = std::uint64_t(s.identity.st_size);
        if (le(c + 68, 4) != 0 || !width || !height || width > 16384 || height > 16384 ||
            stride < width || stride > 32768 || height * stride > 128 * 1024 * 1024 || !slots ||
            slots > 64 || start < header_size || start % 64 || bytes % 64 ||
            bytes < slot_header + height * stride || start > file_size ||
            bytes > (file_size - start) / slots)
            throw std::runtime_error("invalid ring camera dimensions, format or slot bounds");
        if (name(c + 32) == s.options.camera_name) {
            if (le(c + 128, 4) & 1)
                throw std::runtime_error("dark exposure camera is not a tracking input");
            s.camera_offset = offset;
            ++selected;
        }
        // Disjoint camera storage is required by this ABI.
        for (std::size_t j = 0; j < i; ++j) {
            const auto *other = s.initial.data() + 64 + j * camera_size;
            const auto os = le(other + 88, 8), oe = os + le(other + 96, 8) * le(other + 84, 4);
            if (start < oe && os < start + slots * bytes)
                throw std::runtime_error("overlapping ring camera slots");
        }
    }
    if (selected != 1)
        throw std::runtime_error("ring camera name must match exactly one camera");
}
FrametopRing::~FrametopRing() = default;

std::optional<RingFrame> FrametopRing::poll() {
    auto &s = *impl_;
    const auto h = s.header();
    if (le(h.data() + 16, 4) != le(s.initial.data() + 16, 4) ||
        le(h.data() + 32, 8) != s.writer_pid)
        throw std::runtime_error("ring producer changed; restart reader");
    const auto *c = h.data() + s.camera_offset;
    // Metadata and geometry are immutable for this reader's lifetime. Counters
    // and dark_mean may change, so only compare the immutable descriptor prefix.
    if (std::memcmp(c, s.initial.data() + s.camera_offset, 104) ||
        le(c + 128, 4) != le(s.initial.data() + s.camera_offset + 128, 4))
        throw std::runtime_error("ring camera descriptor changed; restart reader");
    const auto n = le(c + 104, 8);
    if (!n || n == s.last_frame)
        return std::nullopt;
    if (n < s.last_frame || n > (std::numeric_limits<std::uint64_t>::max() - 2) / 2)
        throw std::runtime_error("ring frame sequence regressed or overflowed");
    const auto offset = le(c + 88, 8) + (n % le(c + 84, 4)) * le(c + 96, 8), expected = 2 * n + 2;
    std::array<std::uint8_t, slot_header> slot{};
    read_at(s.fd, slot.data(), slot.size(), offset);
    if (le(slot.data(), 8) != expected)
        return std::nullopt;
    RingFrame result;
    auto &image = result.image;
    image.camera_id = s.options.camera_name;
    image.width = static_cast<std::uint32_t>(le(c + 72, 4));
    image.height = static_cast<std::uint32_t>(le(c + 76, 4));
    image.stride_bytes = static_cast<std::uint32_t>(le(c + 80, 4));
    image.calibration_id = s.options.calibration_id;
    image.clock_domain = s.options.capture_clock_domain;
    image.capture_time_ns = le(slot.data() + 16, 8);
    image.pixels.resize(std::size_t(image.height) * image.stride_bytes);
    read_at(s.fd, image.pixels.data(), image.pixels.size(), offset + slot_header);
    std::array<std::uint8_t, 8> sequence{};
    read_at(s.fd, sequence.data(), sequence.size(), offset);
    if (le(sequence.data(), 8) != expected)
        return std::nullopt;
    if (le(slot.data() + 8, 8) != n)
        throw std::runtime_error("ring slot frame number mismatch");
    if (s.last_frame && image.capture_time_ns <= s.last_capture)
        throw std::runtime_error("ring capture timestamp did not increase");
    result.frame_number = n;
    result.dequeue_monotonic_ns = le(slot.data() + 24, 8);
    result.publish_monotonic_ns = le(slot.data() + 32, 8);
    result.v4l2_sequence = static_cast<std::uint32_t>(le(slot.data() + 40, 4));
    result.skipped_since_previous = s.last_frame ? n - s.last_frame - 1 : 0;
    image.ring_transport =
        RingTransport{n, result.dequeue_monotonic_ns, result.publish_monotonic_ns,
                      result.v4l2_sequence, result.skipped_since_previous};
    image.validate();
    s.last_frame = n;
    s.last_capture = image.capture_time_ns;
    return result;
}
} // namespace framephone
