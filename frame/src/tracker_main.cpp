#include "framephone/apriltag_detector.hpp"
#include "framephone/camera_source.hpp"

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

#ifdef FRAMEPHONE_HAS_APRILTAG
#include "framephone/apriltag_detector.hpp"
#endif

namespace {

void write_pgm(const std::filesystem::path &path, const framephone::CameraFrame &frame) {
    std::ofstream output(path, std::ios::binary);
    if (!output)
        throw std::runtime_error("cannot write synthetic PGM: " + path.string());
    output << "P5\n" << frame.width << ' ' << frame.height << "\n255\n";
    for (std::uint32_t y = 0; y < frame.height; ++y) {
        const auto *row = frame.pixels.data() + static_cast<std::size_t>(y) * frame.stride_bytes;
        output.write(reinterpret_cast<const char *>(row), frame.width);
    }
    if (!output)
        throw std::runtime_error("failed writing synthetic PGM: " + path.string());
}

void print_help() {
    std::cout << "FramePhone native camera/detection diagnostic\n"
              << "  framephone-frame --synthetic [count] [output-directory]\n"
              << "  framephone-frame --replay <recording-directory> [--detect]\n"
              << "AprilTag detection is built only when AprilTag 3 is installed.\n";
}

int run(int argc, char **argv) {
    if (argc < 2 || std::string(argv[1]) == "--help") {
        print_help();
        return 0;
    }
    std::unique_ptr<framephone::CameraSource> source;
    bool write_recording = false;
    std::filesystem::path output_dir;
    bool detect = false;
    if (std::string(argv[1]) == "--synthetic") {
        std::uint32_t count = 1;
        if (argc >= 3 && std::string(argv[2]).find_first_not_of("0123456789") == std::string::npos)
            count = static_cast<std::uint32_t>(std::stoul(argv[2]));
        const int output_arg =
            argc >= 3 && std::string(argv[2]).find_first_not_of("0123456789") == std::string::npos
                ? 3
                : 2;
        if (argc > output_arg) {
            output_dir = argv[output_arg];
            std::filesystem::create_directories(output_dir);
            write_recording = true;
        }
        if (argc > output_arg + 1)
            throw std::invalid_argument("too many synthetic arguments");
        source = std::make_unique<framephone::SyntheticFrameSource>(framephone::SyntheticOptions{},
                                                                    count);
    } else if (std::string(argv[1]) == "--replay" && argc >= 3) {
        source = std::make_unique<framephone::RecordedFrameSource>(argv[2]);
        detect = argc >= 4 && std::string(argv[3]) == "--detect";
        if (argc > 4 || (argc == 4 && !detect))
            throw std::invalid_argument("unknown replay option");
    } else {
        print_help();
        return 2;
    }
    if (write_recording) {
        std::ofstream manifest(output_dir / "manifest.tsv", std::ios::trunc);
        if (!manifest)
            throw std::runtime_error("cannot create recording manifest");
        manifest << "framephone-recording-v1\n";
        for (std::uint32_t index = 0;; ++index) {
            auto frame = source->next();
            if (!frame)
                break;
            const auto filename = "frame-" + std::to_string(index) + ".pgm";
            write_pgm(output_dir / filename, *frame);
            manifest << frame->camera_id << '\t' << frame->capture_time_ns << '\t'
                     << frame->clock_domain << '\t' << frame->calibration_id << '\t'
                     << (frame->exposure_us ? std::to_string(*frame->exposure_us) : "-") << '\t'
                     << filename << '\n';
            std::cout << "synthetic frame " << filename << ": " << frame->width << 'x'
                      << frame->height << " Gray8 camera=" << frame->camera_id
                      << " capture_ns=" << frame->capture_time_ns << '\n';
        }
        std::cout << "Wrote synthetic recording to " << output_dir
                  << " (synthetic data, not camera capture).\n";
        return 0;
    }
#ifdef FRAMEPHONE_HAS_APRILTAG
    std::unique_ptr<framephone::AprilTag36h11Detector> detector;
    if (detect)
        detector = std::make_unique<framephone::AprilTag36h11Detector>();
#else
    if (detect)
        throw std::runtime_error("this build has no AprilTag 3 library; detection is unavailable");
#endif
    std::uint64_t frame_count{};
    for (;;) {
        auto frame = source->next();
        if (!frame)
            break;
        ++frame_count;
        std::cout << "frame=" << frame_count << " camera=" << frame->camera_id << " "
                  << frame->width << 'x' << frame->height << " stride=" << frame->stride_bytes
                  << " format=Gray8 capture_ns=" << frame->capture_time_ns
                  << " clock=" << frame->clock_domain << " calibration=" << frame->calibration_id;
        if (frame->exposure_us)
            std::cout << " exposure_us=" << *frame->exposure_us;
#ifdef FRAMEPHONE_HAS_APRILTAG
        if (detector) {
            const auto batch = detector->detect(*frame);
            std::cout << " detect_us="
                      << std::chrono::duration_cast<std::chrono::microseconds>(batch.detection_time)
                             .count()
                      << " rejected_unknown=" << batch.rejected_unknown_ids << " tags=";
            for (const auto &tag : batch.detections) {
                std::cout << tag.id << "(margin=" << tag.decision_margin << ",corners=";
                for (const auto &point : tag.corners)
                    std::cout << point.x << ':' << point.y << '|';
                std::cout << ") ";
            }
        }
#endif
        std::cout << '\n';
    }
    std::cout << "end of stream; processed " << frame_count << " frames\n";
    return 0;
}

} // namespace

int main(int argc, char **argv) {
    try {
        return run(argc, argv);
    } catch (const std::exception &error) {
        std::cerr << "framephone-frame: " << error.what() << '\n';
        return 1;
    }
}
