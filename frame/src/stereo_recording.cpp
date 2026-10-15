#include "framephone/stereo_recording.hpp"

namespace framephone {
void write_pgm(const std::filesystem::path &path, const CameraFrame &f) {
    f.validate();
    std::ofstream image(path, std::ios::binary);
    image << "P5\n" << f.width << ' ' << f.height << "\n255\n";
    for (std::uint32_t y = 0; y < f.height; ++y)
        image.write(
            reinterpret_cast<const char *>(f.pixels.data() + std::size_t(y) * f.stride_bytes),
            f.width);
    image.close();
    if (!image)
        throw std::runtime_error("failed writing recording image");
}
StereoRecorder::StereoRecorder(std::filesystem::path directory) : directory_(std::move(directory)) {
    if (!std::filesystem::create_directory(directory_))
        throw std::runtime_error("cannot create recording directory");
    manifest_.open(directory_ / "manifest.tsv");
    manifest_ << "framephone-recording-v1\n";
    if (!manifest_)
        throw std::runtime_error("cannot write recording manifest");
}
void StereoRecorder::write(const StereoPair &pair, std::uint64_t index) {
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &f = pair.frames[v];
        for (const auto &field : {f.camera_id, f.clock_domain, f.calibration_id})
            if (field.find_first_of("\t\r\n") != std::string::npos)
                throw std::invalid_argument("recording identity contains TSV separators");
        const auto name = "pair-" + std::to_string(index) + "-" + std::to_string(v) + ".pgm";
        write_pgm(directory_ / name, f);
        manifest_ << f.camera_id << '\t' << f.capture_time_ns << '\t' << f.clock_domain << '\t'
                  << f.calibration_id << '\t';
        if (f.exposure_us)
            manifest_ << *f.exposure_us;
        else
            manifest_ << '-';
        manifest_ << '\t' << name << '\n';
    }
    manifest_.flush();
    if (!manifest_)
        throw std::runtime_error("failed writing recording manifest");
}
} // namespace framephone
