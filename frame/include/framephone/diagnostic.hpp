#pragma once

#include "framephone/apriltag_detector.hpp"

#include <map>
#include <ostream>
#include <set>
#include <string>
#include <utility>

namespace framephone {

// These describe image-space detections, not calibrated 6DoF tracking.
struct CameraDiagnostics {
    std::uint64_t frames{};
    std::uint64_t frames_with_tags{};
    std::uint64_t reacquisitions{};
    std::uint64_t missing_streak{};
    bool seen_tags{};
    std::set<int> current_ids;
};

class DiagnosticSession {
  public:
    // Keep separate histories for cameras whose clocks cannot be compared.
    const CameraDiagnostics &observe(const CameraFrame &frame, const DetectionBatch &batch,
                                     bool detection_enabled);

  private:
    std::map<std::pair<std::string, std::string>, CameraDiagnostics> cameras_;
};

void write_diagnostic_csv_header(std::ostream &output);
// One row per detection, or one row with empty detection fields if none exists.
// Retains original capture timestamps as decimal integers, without clock conversion.
void write_diagnostic_csv(std::ostream &output, std::uint64_t session, std::uint64_t frame_index,
                          const CameraFrame &frame, const DetectionBatch &batch,
                          bool detection_enabled, double processing_ms);

} // namespace framephone
