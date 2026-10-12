#include "framephone/diagnostic.hpp"
#include "framephone/frametop_ring.hpp"
#ifdef FRAMEPHONE_HAS_POSE
#include "framephone/pose.hpp"
#endif
#ifdef FRAMEPHONE_HAS_SDL2
#include "framephone/diagnostic_view.hpp"
#endif

#include <algorithm>
#include <charconv>
#include <cmath>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>

namespace {
volatile std::sig_atomic_t stopped = 0;
void stop(int) {
    stopped = 1;
}

struct Options {
    std::filesystem::path replay;
    std::filesystem::path csv;
    std::filesystem::path ring, phone_layout, camera_calibration, pose_jsonl;
    std::string camera_name, calibration_id, capture_clock;
    std::string snapshot;
    std::uint32_t frames{300};
    std::uint32_t marker_px{32};
    std::uint32_t blank_every{};
    std::uint32_t fps{30};
    std::uint32_t idle_timeout_ms{5000};
    bool motion{};
    bool headless{};
    bool detect{true};
    bool quit_at_end{};
};

void help() {
    std::cout << "FramePhone native fiducial diagnostic / optional camera-relative pose\n"
                 "Usage: framephone-diagnostic [--synthetic | --replay DIRECTORY | --frametop-ring "
                 "FILE] [options]\n"
                 "  --frames N           Synthetic/live frame limit (default 300, max 1000000)\n"
                 "  --marker-px N        Synthetic tag boundary, multiple of 8 (default 32)\n"
                 "  --motion             Translate the synthetic image over time\n"
                 "  --blank-every N      Replace every Nth synthetic frame with a blank\n"
                 "  --fps N              Preview playback rate, 1..240 (default 30)\n"
                 "  --headless           Process without a window, unpaced; print summary\n"
                 "  --no-detect          Preview only; never reports fabricated detections\n"
                 "  --csv FILE           Explicit local CSV export; refuses existing files\n"
                 "  --snapshot FILE.bmp  Save the final preview on end of stream\n"
                 "  --quit-at-end        Close preview at end (otherwise stays open)\n"
                 "  --capabilities       Show compiled detector/viewer availability\n"
                 "  --frametop-ring FILE Read existing FHRING01 v1 ring read-only\n"
                 "  --camera NAME        Exact ring camera name (required for live input)\n"
                 "  --calibration-id ID  Calibration identity attached to ring frames\n"
                 "  --capture-clock NAME Explicit camera capture clock domain\n"
                 "  --idle-timeout-ms N  Fail if live input stops (default 5000, max 60000)\n"
                 "  --phone-layout FILE  Exported phone-layout v1 JSON (enables pose)\n"
                 "  --camera-calibration FILE Camera intrinsics/distortion JSON\n"
                 "  --pose-jsonl FILE    Optional local T_CP export; refuses existing files\n"
                 "Preview keys: SPACE pause, RIGHT step, R restart, ESC/Q quit\n"
                 "Replay uses a fixed display rate, retaining each original camera timestamp.\n";
}

std::uint32_t integer(const std::string &value, const std::string &option) {
    std::uint32_t result{};
    const auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), result);
    if (error != std::errc{} || end != value.data() + value.size() || result == 0)
        throw std::invalid_argument(option + " requires a positive 32-bit integer");
    return result;
}

Options parse(int argc, char **argv) {
    Options result;
    bool source_selected{};
    bool synthetic_options{};
    bool frames_selected{}, ring_options{};
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        const auto value = [&]() -> std::string {
            if (i + 1 >= argc)
                throw std::invalid_argument("missing value for " + arg);
            return argv[++i];
        };
        if (arg == "--synthetic" || arg == "--replay" || arg == "--frametop-ring") {
            if (source_selected)
                throw std::invalid_argument("select exactly one input source");
            source_selected = true;
            if (arg == "--replay") {
                result.replay = value();
                if (result.replay.empty())
                    throw std::invalid_argument("--replay requires a directory");
            }
            if (arg == "--frametop-ring") {
                result.ring = value();
                if (result.ring.empty())
                    throw std::invalid_argument("--frametop-ring requires a file");
            }
        } else if (arg == "--frames") {
            result.frames = integer(value(), arg);
            frames_selected = true;
        } else if (arg == "--marker-px") {
            result.marker_px = integer(value(), arg);
            synthetic_options = true;
        } else if (arg == "--blank-every") {
            result.blank_every = integer(value(), arg);
            synthetic_options = true;
        } else if (arg == "--fps")
            result.fps = integer(value(), arg);
        else if (arg == "--motion") {
            result.motion = true;
            synthetic_options = true;
        } else if (arg == "--headless")
            result.headless = true;
        else if (arg == "--no-detect")
            result.detect = false;
        else if (arg == "--quit-at-end")
            result.quit_at_end = true;
        else if (arg == "--csv") {
            result.csv = value();
            if (result.csv.empty())
                throw std::invalid_argument("--csv requires a file");
        } else if (arg == "--snapshot") {
            result.snapshot = value();
            if (result.snapshot.empty())
                throw std::invalid_argument("--snapshot requires a file");
        } else if (arg == "--camera") {
            result.camera_name = value();
            ring_options = true;
        } else if (arg == "--calibration-id") {
            result.calibration_id = value();
            ring_options = true;
        } else if (arg == "--capture-clock") {
            result.capture_clock = value();
            ring_options = true;
        } else if (arg == "--idle-timeout-ms") {
            result.idle_timeout_ms = integer(value(), arg);
            ring_options = true;
        } else if (arg == "--phone-layout") {
            result.phone_layout = value();
            if (result.phone_layout.empty())
                throw std::invalid_argument("empty phone layout");
        } else if (arg == "--camera-calibration") {
            result.camera_calibration = value();
            if (result.camera_calibration.empty())
                throw std::invalid_argument("empty camera calibration");
        } else if (arg == "--pose-jsonl") {
            result.pose_jsonl = value();
            if (result.pose_jsonl.empty())
                throw std::invalid_argument("empty pose output path");
        } else
            throw std::invalid_argument("unknown option: " + arg);
    }
    if (result.frames > 1'000'000)
        throw std::invalid_argument("--frames exceeds 1000000");
    if (result.fps > 240)
        throw std::invalid_argument("--fps exceeds 240");
    if (!result.replay.empty() && (synthetic_options || frames_selected))
        throw std::invalid_argument("synthetic options cannot be used with --replay");
    if (!result.ring.empty() && synthetic_options)
        throw std::invalid_argument("synthetic options cannot be used with live input");
    if (result.ring.empty() && ring_options)
        throw std::invalid_argument("ring options require --frametop-ring");
    if (!result.ring.empty() && (result.camera_name.empty() || result.calibration_id.empty() ||
                                 result.capture_clock.empty()))
        throw std::invalid_argument(
            "live input requires --camera, --calibration-id and --capture-clock");
    if (result.idle_timeout_ms > 60000)
        throw std::invalid_argument("idle timeout exceeds 60000 ms");
    if (result.phone_layout.empty() != result.camera_calibration.empty())
        throw std::invalid_argument("pose requires both phone layout and camera calibration");
    if (!result.pose_jsonl.empty() && result.phone_layout.empty())
        throw std::invalid_argument("pose output requires calibration inputs");
    if (!result.phone_layout.empty() && !result.detect)
        throw std::invalid_argument("pose requires detection");
    if (!result.pose_jsonl.empty() && std::filesystem::exists(result.pose_jsonl))
        throw std::invalid_argument("pose file already exists");
    if (!result.csv.empty() && std::filesystem::exists(result.csv))
        throw std::invalid_argument("CSV file already exists");
    const std::array<std::filesystem::path, 3> outputs{result.csv, result.pose_jsonl,
                                                       result.snapshot};
    for (std::size_t i = 0; i < outputs.size(); ++i)
        for (std::size_t j = 0; j < i; ++j)
            if (!outputs[i].empty() && !outputs[j].empty() &&
                std::filesystem::weakly_canonical(outputs[i]) ==
                    std::filesystem::weakly_canonical(outputs[j]))
                throw std::invalid_argument("export output paths must differ");
    if (!result.snapshot.empty() && result.headless)
        throw std::invalid_argument("--snapshot requires the preview window");
    if (!result.snapshot.empty() && std::filesystem::exists(result.snapshot))
        throw std::invalid_argument("snapshot file already exists");
    return result;
}

class DiagnosticSyntheticSource final : public framephone::CameraSource {
  public:
    explicit DiagnosticSyntheticSource(const Options &options)
        : source_(synthetic_options(options), options.frames), options_(options) {}
    std::optional<framephone::CameraFrame> next() override {
        auto frame = source_.next();
        if (!frame)
            return frame;
        ++index_;
        if (options_.blank_every && index_ % options_.blank_every == 0) {
            std::fill(frame->pixels.begin(), frame->pixels.end(), 24);
        } else if (options_.motion) {
            auto original = frame->pixels;
            std::fill(frame->pixels.begin(), frame->pixels.end(), 24);
            const int dx = static_cast<int>(std::lround(28 * std::sin(index_ * 0.07)));
            const int dy = static_cast<int>(std::lround(12 * std::sin(index_ * 0.11)));
            for (int y = 0; y < static_cast<int>(frame->height); ++y)
                for (int x = 0; x < static_cast<int>(frame->width); ++x) {
                    const int sx = x - dx, sy = y - dy;
                    if (sx >= 0 && sy >= 0 && sx < static_cast<int>(frame->width) &&
                        sy < static_cast<int>(frame->height))
                        frame->pixels[static_cast<std::size_t>(y) * frame->stride_bytes +
                                      static_cast<std::size_t>(x)] =
                            original[static_cast<std::size_t>(sy) * frame->stride_bytes +
                                     static_cast<std::size_t>(sx)];
                }
        }
        return frame;
    }

  private:
    static framephone::SyntheticOptions synthetic_options(const Options &options) {
        framephone::SyntheticOptions result;
        result.marker_boundary_px = options.marker_px;
        return result;
    }
    framephone::SyntheticFrameSource source_;
    Options options_;
    std::uint32_t index_{};
};

std::unique_ptr<framephone::CameraSource> source(const Options &options) {
    if (options.replay.empty())
        return std::make_unique<DiagnosticSyntheticSource>(options);
    return std::make_unique<framephone::RecordedFrameSource>(options.replay);
}

int run(int argc, char **argv) {
    if (argc == 2 && std::string(argv[1]) == "--help") {
        help();
        return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--capabilities") {
        std::cout << "AprilTag3="
#ifdef FRAMEPHONE_HAS_APRILTAG
                  << "available"
#else
                  << "unavailable"
#endif
                  << " SDL2="
#ifdef FRAMEPHONE_HAS_SDL2
                  << "available"
#else
                  << "unavailable"
#endif
                  << " live_camera=frametop_ring_v1 pose_6dof="
#ifdef FRAMEPHONE_HAS_POSE
                  << "camera_relative"
#else
                  << "unavailable"
#endif
                  << '\n';
        return 0;
    }
    const auto options = parse(argc, argv);
#ifdef FRAMEPHONE_HAS_POSE
    std::unique_ptr<framephone::PlanarPoseEstimator> estimator;
    framephone::PoseResult pose;
    if (!options.phone_layout.empty())
        estimator = std::make_unique<framephone::PlanarPoseEstimator>(
            framephone::load_phone_layout(options.phone_layout),
            framephone::load_camera_calibration(options.camera_calibration));
#else
    if (!options.phone_layout.empty())
        throw std::runtime_error("OpenCV/JSON pose support is unavailable in this build");
#endif
#ifdef FRAMEPHONE_HAS_APRILTAG
    std::unique_ptr<framephone::AprilTag36h11Detector> detector;
    if (options.detect)
        detector = std::make_unique<framephone::AprilTag36h11Detector>();
#else
    if (options.detect)
        throw std::runtime_error("AprilTag 3 is unavailable in this build. Install it and rebuild, "
                                 "or use --no-detect for preview only.");
#endif
#ifdef FRAMEPHONE_HAS_SDL2
    std::unique_ptr<framephone::DiagnosticView> view;
    if (!options.headless)
        view = std::make_unique<framephone::DiagnosticView>();
#else
    if (!options.headless)
        throw std::runtime_error("SDL2 is unavailable in this build. Install SDL2 development "
                                 "files and rebuild, or use --headless.");
#endif
    std::unique_ptr<framephone::FrametopRing> ring;
    if (!options.ring.empty())
        ring = std::make_unique<framephone::FrametopRing>(framephone::RingOptions{
            options.ring, options.camera_name, options.calibration_id, options.capture_clock});
    auto input = ring ? nullptr : source(options);
    std::ofstream pose_output;
    if (!options.pose_jsonl.empty()) {
        pose_output.open(options.pose_jsonl);
        if (!pose_output)
            throw std::runtime_error("cannot create pose JSONL");
    }
    std::ofstream csv;
    if (!options.csv.empty()) {
        if (std::filesystem::exists(options.csv))
            throw std::runtime_error("CSV file already exists");
        csv.open(options.csv);
        if (!csv)
            throw std::runtime_error("cannot create CSV: " + options.csv.string());
        framephone::write_diagnostic_csv_header(csv);
    }
    std::signal(SIGINT, stop);
    std::signal(SIGTERM, stop);
    framephone::DiagnosticSession session;
    framephone::CameraDiagnostics stats;
    framephone::DetectionBatch batch;
    std::optional<framephone::CameraFrame> frame;
    std::uint64_t frame_index{}, detected_frames{}, session_index{1};
    std::uint64_t accepted_poses{}, ambiguous_poses{};
    std::string pose_summary;
    bool paused{}, ended{}, step_pending{};
#ifdef FRAMEPHONE_HAS_SDL2
    bool snapshot_saved{};
#endif
    double processing_ms{};
    using Clock = std::chrono::steady_clock;
    auto due = Clock::now();
    auto last_progress = Clock::now();
    const std::string source_label = ring ? "LIVE FRAMETOP RING / CAMERA CAPTURE CLOCK"
                                     : options.replay.empty()
                                         ? "SYNTHETIC INPUT / NOT A CAMERA TEST"
                                         : "RECORDED INPUT / ORIGINAL CAPTURE TIMESTAMPS";
    std::cout << (ring                     ? "Frametop ring input. "
                  : options.replay.empty() ? "Synthetic input (not hardware validation). "
                                           : "Recorded input. ")
              << (options.detect ? "Real AprilTag detection enabled.\n"
                                 : "Preview only: detection disabled.\n");
    while (!stopped) {
#ifdef FRAMEPHONE_HAS_SDL2
        bool redraw{};
#endif
#ifdef FRAMEPHONE_HAS_SDL2
        if (view) {
            const auto commands = view->poll();
            redraw = commands.redraw || commands.toggle_pause || commands.restart;
            if (commands.quit)
                break;
            if (commands.restart) {
                if (ring)
                    ring = std::make_unique<framephone::FrametopRing>(
                        framephone::RingOptions{options.ring, options.camera_name,
                                                options.calibration_id, options.capture_clock});
                else
                    input = source(options);
                session = framephone::DiagnosticSession{};
                frame.reset();
                batch = {};
                stats = {};
                frame_index = 0;
                detected_frames = 0;
                ++session_index;
                accepted_poses = 0;
                ambiguous_poses = 0;
                pose_summary.clear();
                paused = false;
                ended = false;
                step_pending = false;
                due = Clock::now();
                last_progress = Clock::now();
            }
            if (commands.toggle_pause) {
                paused = !paused;
                step_pending = false;
                due = Clock::now();
                last_progress = Clock::now();
            }
            if (commands.step) {
                paused = true;
                step_pending = true;
                last_progress = Clock::now();
            }
        }
#endif
        if (!ended && (options.headless || step_pending || (!paused && Clock::now() >= due))) {
            const auto started = Clock::now();
            std::optional<framephone::CameraFrame> next;
            if (ring && frame_index < options.frames) {
                auto result = ring->poll();
                if (result) {
                    next = std::move(result->image);
                    last_progress = Clock::now();
                } else {
                    if (Clock::now() - last_progress >
                        std::chrono::milliseconds(options.idle_timeout_ms))
                        throw std::runtime_error("live camera idle timeout; no new stable frames");
                    std::this_thread::sleep_for(std::chrono::milliseconds(5));
                    continue;
                }
            } else if (!ring)
                next = input->next();
            step_pending = false;
            if (!next) {
                ended = true;
#ifdef FRAMEPHONE_HAS_SDL2
                redraw = true;
#endif
                if (options.headless)
                    break;
            } else {
                frame = std::move(next);
#ifdef FRAMEPHONE_HAS_SDL2
                redraw = true;
#endif
                batch = {};
#ifdef FRAMEPHONE_HAS_APRILTAG
                if (detector)
                    batch = detector->detect(*frame);
#endif
#ifdef FRAMEPHONE_HAS_POSE
                if (estimator) {
                    pose = estimator->estimate(*frame, batch);
                    pose_summary = "POSE " + pose.status;
                    if (pose.status == "accepted")
                        ++accepted_poses;
                    if (pose.status == "ambiguous")
                        ++ambiguous_poses;
                }
#endif
                stats = session.observe(*frame, batch, options.detect);
                processing_ms =
                    std::chrono::duration<double, std::milli>(Clock::now() - started).count();
                ++frame_index;
                if (!batch.detections.empty())
                    ++detected_frames;
                if (csv.is_open())
                    framephone::write_diagnostic_csv(csv, session_index, frame_index, *frame, batch,
                                                     options.detect, processing_ms);
#ifdef FRAMEPHONE_HAS_POSE
                if (estimator && pose_output.is_open())
                    framephone::write_pose_jsonl(pose_output, *frame, *estimator, pose);
#endif
                due = started + std::chrono::nanoseconds(1'000'000'000 / options.fps);
            }
        }
#ifdef FRAMEPHONE_HAS_SDL2
        if (view && frame && redraw) {
            if (ended && !options.snapshot.empty() && !snapshot_saved) {
                view->save_snapshot(options.snapshot);
                snapshot_saved = true;
            }
            view->show(*frame, batch, stats, options.detect, source_label, paused, ended,
                       processing_ms, pose_summary);
        }
#endif
        if (ended && options.quit_at_end)
            break;
        if (!options.headless)
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    if (csv.is_open()) {
        csv.flush();
        if (!csv)
            throw std::runtime_error("failed flushing diagnostic CSV");
    }
    std::cout << "Processed " << frame_index << " frames; ";
    if (options.detect)
        std::cout << detected_frames << " frames with at least one tag";
    else
        std::cout << "detection not evaluated";
    if (options.phone_layout.empty())
        std::cout << ". No calibrated 6DoF pose is produced.\n";
    else
        std::cout << "; " << accepted_poses << " accepted camera-relative poses, "
                  << ambiguous_poses << " ambiguous frames. No XR/world alignment.\n";
    if (pose_output.is_open()) {
        pose_output.flush();
        if (!pose_output)
            throw std::runtime_error("failed flushing pose JSONL");
    }
    return 0;
}
} // namespace

int main(int argc, char **argv) {
    try {
        return run(argc, argv);
    } catch (const std::exception &error) {
        std::cerr << "framephone-diagnostic: " << error.what() << '\n';
        return 1;
    }
}
