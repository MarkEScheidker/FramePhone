#include "framephone/fiducial.hpp"
#include <apriltag.h>
#include <cmath>
#include <tag36h11.h>

namespace framephone {
struct TagDetector::Impl {
    apriltag_family_t *family = tag36h11_create();
    apriltag_detector_t *detector = apriltag_detector_create();
    Impl() {
        if (!family || !detector)
            throw std::runtime_error("cannot create AprilTag detector");
        apriltag_detector_add_family_bits(detector, family, 0);
        detector->nthreads = 2;
        detector->quad_decimate = 1;
        detector->refine_edges = true;
    }
    ~Impl() {
        apriltag_detector_destroy(detector);
        tag36h11_destroy(family);
    }
};
TagDetector::TagDetector() : impl_(std::make_unique<Impl>()) {}
TagDetector::~TagDetector() = default;
std::vector<TagDetection> TagDetector::detect(const CameraFrame &frame) {
    frame.validate();
    image_u8_t image{int(frame.width), int(frame.height), int(frame.stride_bytes),
                     const_cast<std::uint8_t *>(frame.pixels.data())};
    auto *found = apriltag_detector_detect(impl_->detector, &image);
    std::vector<TagDetection> result;
    try {
        for (int i = 0; i < zarray_size(found); ++i) {
            apriltag_detection_t *d;
            zarray_get(found, i, &d);
            TagDetection tag;
            tag.id = d->id;
            tag.hamming = d->hamming;
            tag.margin = d->decision_margin;
            // AprilTag's image raster order is BL/BR/TR/TL. Convert to decoded
            // TL/TR/BR/BL for a right/up/out-of-screen marker frame.
            for (std::size_t k = 0; k < 4; ++k)
                tag.corners[k] = {d->p[3 - k][0], d->p[3 - k][1]};
            result.push_back(tag);
        }
    } catch (...) {
        apriltag_detections_destroy(found);
        throw;
    }
    apriltag_detections_destroy(found);
    return result;
}
CameraFrame render_tag(int id, int cell_pixels) {
    if (id < 0 || id >= 587 || cell_pixels < 1 || cell_pixels > 256)
        throw std::invalid_argument("invalid tag renderer input");
    auto *family = tag36h11_create();
    auto *image = apriltag_to_image(family, id);
    CameraFrame frame;
    frame.camera_id = "synthetic-tag";
    frame.width = std::uint32_t(image->width * cell_pixels);
    frame.height = std::uint32_t(image->height * cell_pixels);
    frame.stride_bytes = frame.width;
    frame.pixel_format = PixelFormat::Gray8;
    frame.capture_time_ns = 1;
    frame.clock_domain = "synthetic";
    frame.calibration_id = "synthetic";
    frame.pixels.resize(std::size_t(frame.width) * frame.height);
    for (std::uint32_t y = 0; y < frame.height; ++y)
        for (std::uint32_t x = 0; x < frame.width; ++x)
            frame.pixels[std::size_t(y) * frame.width + x] =
                image->buf[(y / std::uint32_t(cell_pixels)) * std::uint32_t(image->stride) +
                           x / std::uint32_t(cell_pixels)];
    // Some packaged AprilTag builds do not export common image destroy helpers.
    free(image->buf);
    free(image);
    tag36h11_destroy(family);
    return frame;
}
FiducialTracker::FiducialTracker(double edge, StereoRig rig)
    : estimator_({edge, edge, 0}, std::move(rig)) {}
FiducialResult FiducialTracker::update(const StereoPair &pair) {
    const auto &rig = estimator_.rig();
    if (pair.skew_ns() > 3'000'000 || pair.frames[0].clock_domain != pair.frames[1].clock_domain)
        throw std::invalid_argument("fiducial views require <=3ms skew in one capture clock");
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &f = pair.frames[v];
        const auto &k = rig.cameras[v].calibration;
        if (f.camera_id != k.camera_id || f.calibration_id != k.id || f.width != k.width ||
            f.height != k.height)
            throw std::invalid_argument(
                "fiducial frame/calibration identity or dimensions mismatch");
    }
    FiducialResult result;
    result.pose.reason = "tag0_not_visible_in_both_front_cameras";
    PlanarObservation observation;
    bool ready = true;
    for (std::size_t v = 0; v < 2; ++v) {
        result.detections[v] = detector_.detect(pair.frames[v]);
        int count = 0;
        for (const auto &tag : result.detections[v])
            if (tag.id == 0 && tag.hamming == 0 && std::isfinite(tag.margin) && tag.margin >= 15) {
                observation.corners[v] = tag.corners;
                ++count;
            }
        if (count != 1) {
            ready = false;
            if (count > 1)
                result.pose.reason = "multiple_tag0_detections";
        }
    }
    if (ready) {
        result.pose = estimator_.estimate(pair, observation);
        if (result.pose.status == "measured")
            result.pose.reason = "single_tag_stereo_pose";
    }
    return result;
}
} // namespace framephone
