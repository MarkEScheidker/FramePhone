#include "framephone/frametop_ring.hpp"
#include <chrono>
#include <iostream>
#include <thread>

int main(int argc, char **argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout << "Usage: framephone-camera-read RING [CAMERA]\n"
                         "List cameras, or print ten new frames from one camera.\n";
            return 0;
        }
        if (argc != 2 && argc != 3)
            throw std::runtime_error("use --help for usage");
        if (argc == 2) {
            for (const auto &camera : framephone::list_frametop_cameras(argv[1]))
                std::cout << camera.name << " " << camera.width << "x" << camera.height << '\n';
            return 0;
        }
        // These labels explicitly carry no calibration or clock-alignment claim.
        framephone::FrametopRing reader(
            {argv[1], argv[2], "preview-only", "unverified-camera-clock"});
        auto last_frame = std::chrono::steady_clock::now();
        for (int count = 0; count < 10;) {
            if (auto frame = reader.poll()) {
                std::cout << frame->frame_number << " " << frame->image.width << "x"
                          << frame->image.height << " capture_ns=" << frame->image.capture_time_ns
                          << '\n';
                last_frame = std::chrono::steady_clock::now();
                ++count;
            } else {
                if (std::chrono::steady_clock::now() - last_frame > std::chrono::seconds(5))
                    throw std::runtime_error("no new camera frames for five seconds");
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
            }
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "camera reader: " << error.what() << '\n';
        return 1;
    }
}
