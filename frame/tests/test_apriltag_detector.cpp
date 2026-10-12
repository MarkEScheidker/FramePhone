#include "framephone/apriltag_detector.hpp"
#include "framephone/camera_source.hpp"

#include <array>
#include <cmath>
#include <iostream>
#include <set>
#include <stdexcept>

int main() {
    try {
        framephone::SyntheticFrameSource source;
        const auto frame = source.next();
        if (!frame)
            throw std::runtime_error("synthetic source produced no frame");
        framephone::AprilTag36h11Detector detector(1);
        const auto result = detector.detect(*frame);
        std::set<int> ids;
        for (const auto &detection : result.detections) {
            ids.insert(detection.id);
            if (detection.hamming != 0)
                throw std::runtime_error("synthetic tag required bit correction");
            if (detection.decision_margin <= 0)
                throw std::runtime_error("synthetic tag has a nonpositive decision margin");
            if (detection.camera_id != frame->camera_id ||
                detection.capture_time_ns != frame->capture_time_ns)
                throw std::runtime_error("detection lost frame identity or capture timestamp");
            for (const auto &corner : detection.corners) {
                if (!std::isfinite(corner.x) || !std::isfinite(corner.y) || corner.x < 0 ||
                    corner.x >= frame->width || corner.y < 0 || corner.y >= frame->height)
                    throw std::runtime_error("detector returned an invalid image-space corner");
            }
        }
        if (ids != std::set<int>{0, 1, 2, 3})
            throw std::runtime_error("expected exactly the four rendered tag36h11 IDs 0–3");
        std::cout << "AprilTag 3 detected all four synthetic IDs with decision margins; elapsed "
                  << result.detection_time.count() << " ns. Synthetic result only.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "AprilTag detector test failed: " << error.what() << '\n';
        return 1;
    }
}
