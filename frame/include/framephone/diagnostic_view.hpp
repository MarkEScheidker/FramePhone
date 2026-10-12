#pragma once

#include "framephone/diagnostic.hpp"

#include <memory>

namespace framephone {

struct ViewCommands {
    bool quit{};
    bool toggle_pause{};
    bool step{};
    bool restart{};
    bool redraw{};
};

// Optional SDL2 desktop view. The processing pipeline also runs headlessly.
class DiagnosticView {
  public:
    DiagnosticView();
    ~DiagnosticView();
    DiagnosticView(const DiagnosticView &) = delete;
    DiagnosticView &operator=(const DiagnosticView &) = delete;
    ViewCommands poll();
    void show(const CameraFrame &frame, const DetectionBatch &batch, const CameraDiagnostics &stats,
              bool detection_enabled, const std::string &source_label, bool paused, bool ended,
              double processing_ms, const std::string &pose_summary = {});
    void save_snapshot(const std::string &path);

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace framephone
