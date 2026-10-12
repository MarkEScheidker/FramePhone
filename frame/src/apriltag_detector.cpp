#include "framephone/apriltag_detector.hpp"

#ifdef FRAMEPHONE_APRILTAG_NESTED_HEADERS
#include <apriltag/apriltag.h>
#include <apriltag/tag36h11.h>
#else
#include <apriltag.h>
#include <tag36h11.h>
#endif

#include <algorithm>
#include <stdexcept>

namespace framephone {

struct AprilTag36h11Detector::Impl {
    apriltag_family_t *family{tag36h11_create()};
    apriltag_detector_t *detector{apriltag_detector_create()};

    explicit Impl(int threads) {
        if (family == nullptr || detector == nullptr) {
            if (detector != nullptr)
                apriltag_detector_destroy(detector);
            if (family != nullptr)
                tag36h11_destroy(family);
            detector = nullptr;
            family = nullptr;
            throw std::runtime_error("AprilTag 3 initialization failed");
        }
        detector->nthreads = threads;
        // Decode the source at full image resolution. Tune decimation only after
        // measuring target-camera detection rate and latency.
        detector->quad_decimate = 1.0F;
        detector->quad_sigma = 0.0F;
        detector->refine_edges = true;
        detector->decode_sharpening = 0.25;
        apriltag_detector_add_family(detector, family);
    }

    ~Impl() {
        if (detector != nullptr)
            apriltag_detector_destroy(detector);
        if (family != nullptr)
            tag36h11_destroy(family);
    }
};

AprilTag36h11Detector::AprilTag36h11Detector(int threads) {
    if (threads < 1)
        throw std::invalid_argument("AprilTag worker thread count must be positive");
    impl_ = std::make_unique<Impl>(threads);
}
AprilTag36h11Detector::~AprilTag36h11Detector() = default;
AprilTag36h11Detector::AprilTag36h11Detector(AprilTag36h11Detector &&) noexcept = default;
AprilTag36h11Detector &
AprilTag36h11Detector::operator=(AprilTag36h11Detector &&) noexcept = default;

DetectionBatch AprilTag36h11Detector::detect(const CameraFrame &frame) {
    frame.validate();
    const auto started = std::chrono::steady_clock::now();
    if (frame.width > static_cast<std::uint32_t>(INT32_MAX) ||
        frame.height > static_cast<std::uint32_t>(INT32_MAX) ||
        frame.stride_bytes > static_cast<std::uint32_t>(INT32_MAX))
        throw std::invalid_argument(
            "AprilTag image dimensions exceed its signed 32-bit image contract");
    image_u8_t image{static_cast<std::int32_t>(frame.width),
                     static_cast<std::int32_t>(frame.height),
                     static_cast<std::int32_t>(frame.stride_bytes),
                     const_cast<std::uint8_t *>(frame.pixels.data())};
    zarray_t *raw = apriltag_detector_detect(impl_->detector, &image);
    if (raw == nullptr)
        throw std::runtime_error("AprilTag 3 returned no detection array");
    const auto destroy_detections = [](zarray_t *array) { apriltag_detections_destroy(array); };
    std::unique_ptr<zarray_t, decltype(destroy_detections)> detections(raw, destroy_detections);

    DetectionBatch batch;
    const int count = zarray_size(detections.get());
    batch.detections.reserve(static_cast<std::size_t>(std::max(count, 0)));
    for (int index = 0; index < count; ++index) {
        apriltag_detection_t *detection = nullptr;
        zarray_get(detections.get(), index, &detection);
        if (detection == nullptr)
            continue;
        if (detection->id < 0 || detection->id > 5 || detection->family != impl_->family) {
            ++batch.rejected_unknown_ids;
            continue;
        }
        TagDetection accepted{
            .id = detection->id,
            .decision_margin = detection->decision_margin,
            .hamming = detection->hamming,
            .camera_id = frame.camera_id,
            .capture_time_ns = frame.capture_time_ns,
        };
        for (std::size_t corner = 0; corner < accepted.corners.size(); ++corner) {
            accepted.corners[corner] = {detection->p[corner][0], detection->p[corner][1]};
        }
        batch.detections.push_back(std::move(accepted));
    }
    batch.detection_time = std::chrono::steady_clock::now() - started;
    return batch;
}

} // namespace framephone
