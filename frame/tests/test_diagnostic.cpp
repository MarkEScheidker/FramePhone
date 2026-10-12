#include "framephone/diagnostic.hpp"

#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace {
void check(bool condition, const char *message) {
    if (!condition)
        throw std::runtime_error(message);
}
void histories_are_isolated() {
    framephone::SyntheticFrameSource source;
    auto frame = *source.next();
    framephone::DiagnosticSession session;
    framephone::DetectionBatch visible;
    framephone::TagDetection tag;
    tag.id = 2;
    visible.detections = {tag};
    const framephone::DetectionBatch blank;
    auto stats = session.observe(frame, blank, true);
    check(stats.frames == 1 && stats.missing_streak == 1 && stats.reacquisitions == 0,
          "initial miss was not counted");
    stats = session.observe(frame, visible, true);
    check(stats.frames_with_tags == 1 && stats.reacquisitions == 0,
          "first acquisition was reported as reacquisition");
    session.observe(frame, blank, true);
    auto second = frame;
    second.camera_id = "second";
    stats = session.observe(second, visible, true);
    check(stats.frames == 1 && stats.reacquisitions == 0, "cameras share detection history");
    auto clock = frame;
    clock.clock_domain = "different-clock";
    stats = session.observe(clock, blank, true);
    check(stats.frames == 1 && stats.missing_streak == 1, "clocks share detection history");
    stats = session.observe(frame, visible, true);
    check(stats.frames == 4 && stats.frames_with_tags == 2 && stats.reacquisitions == 1 &&
              stats.missing_streak == 0 && stats.current_ids == std::set<int>{2},
          "reacquisition after an optical gap was lost");
}
void preview_is_not_detection() {
    framephone::SyntheticFrameSource source;
    const auto frame = *source.next();
    framephone::DiagnosticSession session;
    const auto stats = session.observe(frame, {}, false);
    check(stats.frames == 1 && stats.frames_with_tags == 0 && stats.missing_streak == 0 &&
              !stats.seen_tags,
          "disabled detector produced a tracking result");
    std::ostringstream csv;
    auto quoted = frame;
    quoted.camera_id = "camera,\"one\"";
    quoted.capture_time_ns = std::numeric_limits<std::uint64_t>::max();
    framephone::write_diagnostic_csv_header(csv);
    framephone::write_diagnostic_csv(csv, 1, 1, quoted, {}, false, 0.125);
    check(csv.str().find("\"camera,\"\"one\"\"\"") != std::string::npos,
          "CSV camera identity was not escaped");
    check(csv.str().find("18446744073709551615") != std::string::npos,
          "64-bit capture timestamp lost precision");
    check(csv.str().find("preview_only,,0.125") != std::string::npos,
          "preview-only CSV fabricated a detection duration");
}
} // namespace

int main() {
    try {
        histories_are_isolated();
        preview_is_not_detection();
        std::cout << "Diagnostic state/clock isolation and CSV tests passed.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "Diagnostic test failed: " << error.what() << '\n';
        return 1;
    }
}
