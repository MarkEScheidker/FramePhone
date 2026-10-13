#include "framephone/diagnostic.hpp"

#include <cmath>
#include <iomanip>
#include <stdexcept>

namespace framephone {

const CameraDiagnostics &DiagnosticSession::observe(const CameraFrame &frame,
                                                    const DetectionBatch &batch,
                                                    bool detection_enabled) {
    auto &camera = cameras_[{frame.camera_id, frame.clock_domain}];
    ++camera.frames;
    camera.current_ids.clear();
    if (!detection_enabled)
        return camera;
    for (const auto &tag : batch.detections)
        camera.current_ids.insert(tag.id);
    if (camera.current_ids.empty()) {
        ++camera.missing_streak;
    } else {
        ++camera.frames_with_tags;
        if (camera.seen_tags && camera.missing_streak > 0)
            ++camera.reacquisitions;
        camera.seen_tags = true;
        camera.missing_streak = 0;
    }
    return camera;
}

namespace {
void csv_string(std::ostream &output, const std::string &value) {
    output << '"';
    for (const char ch : value) {
        if (ch == '"')
            output << '"';
        output << ch;
    }
    output << '"';
}
} // namespace

void write_diagnostic_csv_header(std::ostream &output) {
    output << "session,frame,camera_id,capture_timestamp_ns,clock_domain,calibration_id,"
              "exposure_us,status,detection_us,processing_ms,rejected_unknown_ids,tag_count,"
              "ring_frame,dequeue_monotonic_ns,publish_monotonic_ns,v4l2_sequence,skipped_frames,"
              "id,hamming,decision_margin,x0,y0,x1,y1,x2,y2,x3,y3\n";
}

void write_diagnostic_csv(std::ostream &output, std::uint64_t session, std::uint64_t frame_index,
                          const CameraFrame &frame, const DetectionBatch &batch,
                          bool detection_enabled, double processing_ms) {
    if (!std::isfinite(processing_ms) || processing_ms < 0)
        throw std::invalid_argument("invalid processing duration");
    const auto prefix = [&] {
        output << session << ',' << frame_index << ',';
        csv_string(output, frame.camera_id);
        output << ',' << frame.capture_time_ns << ',';
        csv_string(output, frame.clock_domain);
        output << ',';
        csv_string(output, frame.calibration_id);
        output << ',' << std::setprecision(17);
        if (frame.exposure_us)
            output << *frame.exposure_us;
        output << ','
               << (!detection_enabled         ? "preview_only"
                   : batch.detections.empty() ? "no_tags"
                                              : "tags_visible")
               << ',';
        if (detection_enabled)
            output << std::chrono::duration<double, std::micro>(batch.detection_time).count();
        output << ',' << processing_ms << ',' << batch.rejected_unknown_ids << ','
               << batch.detections.size();
        if (frame.ring_transport) {
            const auto &r = *frame.ring_transport;
            output << ',' << r.frame_number << ',' << r.dequeue_monotonic_ns << ','
                   << r.publish_monotonic_ns << ',' << r.v4l2_sequence << ','
                   << r.skipped_since_previous;
        } else
            output << ",,,,,";
    };
    if (batch.detections.empty()) {
        prefix();
        output << ",,,,,,,,,,,\n";
    } else {
        for (const auto &tag : batch.detections) {
            prefix();
            output << ',' << tag.id << ',' << tag.hamming << ',' << tag.decision_margin;
            for (const auto &point : tag.corners)
                output << ',' << point.x << ',' << point.y;
            output << '\n';
        }
    }
    if (!output)
        throw std::runtime_error("failed writing diagnostic CSV");
}

void write_detection_corners(std::ostream &output, const DetectionBatch &batch) {
    if (batch.detections.empty())
        output << '-';
    for (std::size_t i = 0; i < batch.detections.size(); ++i) {
        if (i)
            output << ';';
        for (std::size_t j = 0; j < 4; ++j) {
            const auto &p = batch.detections[i].corners[j];
            output << (j ? "," : "") << p.x << ',' << p.y;
        }
    }
}

void write_detection_status(std::ostream &output, std::uint64_t frame_index,
                            const CameraFrame &frame, const DetectionBatch &batch,
                            bool detection_enabled, double processing_ms) {
    output << "detection frame=" << frame_index << " evaluated=" << detection_enabled
           << " tags=" << batch.detections.size() << " ids=";
    if (batch.detections.empty())
        output << '-';
    for (std::size_t i = 0; i < batch.detections.size(); ++i)
        output << (i ? "," : "") << batch.detections[i].id;
    output << " corners=";
    write_detection_corners(output, batch);
    output << " width=" << frame.width << " height=" << frame.height
           << " processing_ms=" << processing_ms << '\n';
    output.flush();
    if (!output)
        throw std::runtime_error("failed writing detection status");
}

} // namespace framephone
