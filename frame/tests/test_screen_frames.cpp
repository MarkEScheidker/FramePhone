#include "../src/screen_frames.hpp"
#include <iostream>

using namespace framephone::surface;
namespace {
void check(bool ok, const char *reason) {
    if (!ok)
        throw std::runtime_error(reason);
}
struct Fixture {
    std::filesystem::path directory;
    int fd = -1;
    std::uint8_t *data = nullptr;
    Fixture() {
        char name[] = "/tmp/framephone-screen-test-XXXXXX";
        directory = mkdtemp(name);
        const auto path = directory / "rgba";
        fd = open(path.c_str(), O_CREAT | O_RDWR | O_EXCL, 0600);
        const auto size = ScreenFrames::header_size + ScreenFrames::max_pixels * 4;
        check(fd >= 0 && ftruncate(fd, size) == 0, "create synthetic screen buffer");
        data = static_cast<std::uint8_t *>(
            mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0));
        check(data != MAP_FAILED, "map synthetic pixels");
        std::ofstream metadata(directory / "screen.json");
        metadata << nlohmann::json{{"schema", "framephone-screen-v1"}, {"path", path.string()}};
    }
    template <class T> void put(std::size_t offset, T value) {
        std::memcpy(data + offset, &value, sizeof(value));
    }
    void publish(std::uint64_t time) {
        std::memcpy(data, "FPSCRN01", 8);
        put<std::uint32_t>(8, 16);
        put<std::uint32_t>(12, 32);
        put<std::uint64_t>(16, 1);
        put<std::uint64_t>(24, time);
        put<std::uint32_t>(32, 16 * 32 * 4);
        put<std::uint32_t>(36, 1);
        put<std::uint64_t>(40, 7);
        std::memset(data + 64, 123, 16 * 32 * 4);
    }
    ~Fixture() {
        if (data && data != MAP_FAILED)
            munmap(data, ScreenFrames::header_size + ScreenFrames::max_pixels * 4);
        if (fd >= 0)
            close(fd);
        std::filesystem::remove_all(directory);
    }
};
} // namespace
int main() {
    try {
        Fixture fixture;
        ScreenFrames frames(fixture.directory / "screen.json");
        constexpr std::uint64_t stamp = 1'000'000'000;
        check(!frames.poll(stamp, true) && !frames.active(stamp), "empty publication stays black");
        fixture.publish(stamp);
        auto image = frames.poll(stamp, true);
        check(image && image->width == 16 && image->height == 32 && image->rgba[0] == 123 &&
                  frames.epoch == 7,
              "read Python-compatible LE header and complete pixels");
        check(!frames.poll(stamp, true), "unchanged frames must not be uploaded twice");
        check(!frames.active(stamp + 500'000'001), "stale video must turn black");
        check(!frames.active(stamp - 1), "future decoder timestamps must be rejected");
        fixture.put<std::uint64_t>(16, 2);
        flock(fixture.fd, LOCK_EX);
        check(!frames.poll(stamp, true),
              "render poll must not block behind decoder's exclusive lock");
        flock(fixture.fd, LOCK_UN);
        check(bool(frames.poll(stamp, true)),
              "latest frame must remain available after a lock conflict");
        fixture.put<std::uint32_t>(36, 0);
        fixture.put<std::uint64_t>(40, 8);
        check(!frames.poll(stamp, true) && !frames.active(stamp) && frames.epoch == 8,
              "revocation immediately invalidates buffered video and advances epoch");
        fixture.put<std::uint32_t>(36, 1);
        fixture.put<std::uint32_t>(32, 0);
        check(!frames.poll(stamp, true), "wrong pixel length must not read or allocate");
        std::cout << "Private screen frames, freshness, epochs and nonblocking locking passed.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
