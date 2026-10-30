#pragma once
#include "phone_model.hpp"
#include <bit>
#include <cstring>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace framephone::surface {
/** A private, RAM-backed latest frame. Shared flock is nonblocking so decoding
 * can never make the headset render thread wait for a pixel copy. */
class ScreenFrames {
  public:
    static constexpr std::size_t header_size = 64, max_pixels = 2'000'000;
    explicit ScreenFrames(std::filesystem::path metadata) : metadata_(std::move(metadata)) {}
    ~ScreenFrames() {
        close();
    }
    ScreenFrames(const ScreenFrames &) = delete;
    ScreenFrames &operator=(const ScreenFrames &) = delete;
    std::uint64_t epoch = 0, sequence = 0;
    bool active(std::uint64_t now) const {
        return active_ && stamp_ <= now && now - stamp_ <= 500'000'000;
    }
    std::optional<Image> poll(std::uint64_t now, bool copy) {
        static_assert(std::endian::native == std::endian::little);
        if (fd_ < 0) {
            if (!std::filesystem::exists(metadata_))
                return {};
            if (std::filesystem::file_size(metadata_) > 4096)
                throw std::runtime_error("invalid screen metadata");
            std::ifstream input(metadata_);
            const auto value = nlohmann::json::parse(input);
            if (value.at("schema") != "framephone-screen-v1")
                throw std::runtime_error("unsupported screen publication");
            fd_ = ::open(value.at("path").get<std::string>().c_str(),
                         O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
            struct stat st {};
            if (fd_ < 0 || fstat(fd_, &st) || !S_ISREG(st.st_mode) || st.st_uid != geteuid() ||
                (st.st_mode & 0077) || st.st_size != std::int64_t(header_size + max_pixels * 4)) {
                close();
                throw std::runtime_error("screen pixels must be private and bounded");
            }
            data_ = static_cast<const std::uint8_t *>(
                mmap(nullptr, header_size + max_pixels * 4, PROT_READ, MAP_SHARED, fd_, 0));
            if (data_ == MAP_FAILED) {
                data_ = nullptr;
                close();
                throw std::runtime_error("cannot map screen pixels");
            }
        }
        if (flock(fd_, LOCK_SH | LOCK_NB))
            return {};
        struct Unlock {
            int fd;
            ~Unlock() {
                flock(fd, LOCK_UN);
            }
        } unlock{fd_};
        if (std::memcmp(data_, "FPSCRN01", 8)) {
            active_ = false;
            return {};
        }
        const auto w = field<std::uint32_t>(8), h = field<std::uint32_t>(12),
                   length = field<std::uint32_t>(32);
        sequence = field<std::uint64_t>(16);
        stamp_ = field<std::uint64_t>(24);
        epoch = field<std::uint64_t>(40);
        active_ = field<std::uint32_t>(36) == 1;
        if (!w || !h || w > 4096 || h > 4096 || std::uint64_t(w) * h > max_pixels ||
            length != std::uint64_t(w) * h * 4) {
            active_ = false;
            return {};
        }
        if (!active(now) || !copy || sequence == copied_)
            return {};
        Image image(w, h,
                    std::vector<std::uint8_t>(data_ + header_size, data_ + header_size + length));
        copied_ = sequence;
        return image;
    }

  private:
    template <class T> T field(std::size_t offset) const {
        T value;
        std::memcpy(&value, data_ + offset, sizeof(value));
        return value;
    }
    void close() {
        if (data_)
            munmap(const_cast<std::uint8_t *>(data_), header_size + max_pixels * 4);
        if (fd_ >= 0)
            ::close(fd_);
        data_ = nullptr;
        fd_ = -1;
        active_ = false;
    }
    std::filesystem::path metadata_;
    int fd_ = -1;
    const std::uint8_t *data_ = nullptr;
    std::uint64_t stamp_ = 0, copied_ = 0;
    bool active_ = false;
};
} // namespace framephone::surface
