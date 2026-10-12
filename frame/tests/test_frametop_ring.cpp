#include "framephone/frametop_ring.hpp"
#include <array>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <time.h>
#include <unistd.h>

namespace {
void check(bool condition, const char *message) {
    if (!condition)
        throw std::runtime_error(message);
}
template <class F> void fails(F function) {
    bool failed = false;
    try {
        function();
    } catch (const std::exception &) {
        failed = true;
    }
    check(failed, "expected ring failure");
}
std::uint64_t now() {
    timespec t{};
    clock_gettime(CLOCK_MONOTONIC, &t);
    return std::uint64_t(t.tv_sec) * 1'000'000'000 + std::uint64_t(t.tv_nsec);
}
struct Fixture {
    std::filesystem::path path =
        std::filesystem::temp_directory_path() / ("framephone-ring-" + std::to_string(getpid()));
    std::array<std::uint8_t, 1856> bytes{};
    Fixture() {
        std::memcpy(bytes.data(), "FHRING01", 8);
        put(8, 1, 4);
        put(12, 1344, 4);
        put(16, 1, 4);
        put(24, bytes.size());
        put(32, 123);
        put(40, now());
        std::memcpy(bytes.data() + 64, "sensor-test", 12);
        std::memcpy(bytes.data() + 96, "front-left", 11);
        put(64 + 72, 8, 4);
        put(64 + 76, 6, 4);
        put(64 + 80, 8, 4);
        put(64 + 84, 4, 4);
        put(64 + 88, 1344);
        put(64 + 96, 128);
        save();
    }
    ~Fixture() {
        std::filesystem::remove(path);
    }
    void put(std::size_t offset, std::uint64_t value, std::size_t n = 8) {
        for (std::size_t i = 0; i < n; ++i)
            bytes[offset + i] = std::uint8_t(value >> (8 * i));
    }
    void save() {
        std::ofstream f(path, std::ios::binary | std::ios::trunc);
        f.write(reinterpret_cast<char *>(bytes.data()), bytes.size());
    }
    void update(std::size_t offset, std::uint64_t value, std::size_t n = 8) {
        put(offset, value, n);
        int fd = open(path.c_str(), O_WRONLY);
        check(fd >= 0, "open fixture");
        const auto written = pwrite(fd, bytes.data() + offset, n, off_t(offset));
        close(fd);
        check(written == ssize_t(n), "write fixture");
    }
    void publish(std::uint64_t n) {
        const auto offset = 1344 + std::size_t(n % 4) * 128;
        put(offset, 2 * n + 2);
        put(offset + 8, n);
        put(offset + 16, 9'007'199'254'740'993 + n);
        put(offset + 24, 1234 + n);
        put(offset + 32, 5678 + n);
        put(offset + 40, 42 + n, 4);
        std::fill_n(bytes.begin() + std::ptrdiff_t(offset + 64), 48, std::uint8_t(n));
        put(64 + 104, n);
        save();
    }
    framephone::RingOptions options() {
        return {path, "front-left", "cal-1", "independent-camera-clock"};
    }
};
} // namespace
int main() {
    try {
        {
            Fixture f;
            framephone::FrametopRing reader(f.options());
            check(!reader.poll(), "empty ring");
            f.publish(1);
            auto first = reader.poll();
            check(bool(first), "frame missing");
            check(first->image.capture_time_ns == 9'007'199'254'740'994ULL, "timestamp precision");
            check(first->image.clock_domain == "independent-camera-clock" &&
                      first->image.calibration_id == "cal-1",
                  "identity");
            check(first->dequeue_monotonic_ns == 1235 && first->publish_monotonic_ns == 5679 &&
                      first->v4l2_sequence == 43,
                  "transport times");
            check(first->image.pixels == std::vector<std::uint8_t>(48, 1), "pixel copy");
            check(!reader.poll(), "duplicate frame");
            f.publish(4);
            auto fourth = reader.poll();
            check(fourth && fourth->skipped_since_previous == 2, "skipped frames");
            f.publish(5);
            f.update(1344 + 128, 11);
            check(!reader.poll(), "odd seqlock accepted");
            f.update(1344 + 128, 12);
            check(bool(reader.poll()), "completed slot missing");
            f.publish(6);
            f.update(1344 + 256 + 16, 1);
            fails([&] { reader.poll(); });
        }
        {
            Fixture f;
            f.publish(1);
            framephone::FrametopRing reader(f.options());
            f.update(40, 1);
            fails([&] { reader.poll(); });
        }
        {
            Fixture f;
            framephone::FrametopRing reader(f.options());
            std::filesystem::resize_file(f.path, 1500);
            fails([&] { reader.poll(); });
        }
        {
            Fixture f;
            framephone::FrametopRing reader(f.options());
            f.update(64 + 72, 9, 4);
            fails([&] { reader.poll(); });
        }
        {
            Fixture f;
            f.update(8, 2, 4);
            fails([&] { framephone::FrametopRing reader(f.options()); });
        }
        {
            Fixture f;
            f.update(64 + 96, 0xffffffffffffffffULL);
            fails([&] { framephone::FrametopRing reader(f.options()); });
        }
        {
            Fixture f;
            auto options = f.options();
            options.camera_name = "missing";
            fails([&] { framephone::FrametopRing reader(options); });
        }
        {
            Fixture f;
            framephone::FrametopRing reader(f.options());
            std::filesystem::remove(f.path);
            f.save();
            fails([&] { reader.poll(); });
        }
        std::cout << "Ring reader: stable/empty/torn/stale, identity, skips, precision, corruption "
                     "and replacement passed.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
