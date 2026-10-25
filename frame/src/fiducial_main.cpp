#include "calibration_json.hpp"
#include "framephone/fiducial.hpp"
#include "framephone/frametop_ring.hpp"
#include "framephone/stereo_recording.hpp"
#include <csignal>
#include <iostream>
#include <opencv2/imgproc.hpp>
#include <sstream>
#include <sys/prctl.h>
#include <thread>
#include <unistd.h>

namespace {
using namespace framephone;
using namespace calibration_json;
volatile std::sig_atomic_t stopped = 0;
void self_test() {
    StereoRig rig;
    StereoPair pair;
    const PlanarTarget body{.06, .06, 0};
    PlanarObservation observation;
    for (std::size_t v = 0; v < 2; ++v) {
        auto &camera = rig.cameras[v];
        const auto name = v ? "synthetic-right" : "synthetic-left";
        camera.calibration = {"self-test", name, "fisheye_kb4", "synthetic", 640,         480,
                              800,         800,  319.5,         239.5,       {0, 0, 0, 0}};
        camera.rotation = {1, 0, 0, 0, -1, 0, 0, 0, -1};
        camera.origin_m = {v ? .032 : -.032, 0, 0};
        pair.frames[v] = {
            name,          640,         480,         640, PixelFormat::Gray8,
            1'000'000'000, "synthetic", "self-test", {},  std::vector<std::uint8_t>(640 * 480)};
        const auto corners = body.front();
        for (std::size_t i = 0; i < corners.size(); ++i) {
            auto p = corners[i];
            p.z -= .6;
            observation.corners[v][i] = camera.project(p);
        }
    }
    const auto tags = TagDetector().detect(render_tag());
    require(tags.size() == 1 && tags[0].id == 0, "AprilTag raster self-test failed");
    const auto result = PlanarPoseEstimator(body, rig).estimate(pair, observation);
    require(result.status == "measured" &&
                std::abs(result.candidates.at(0).translation_m[2] + .6) < 1e-6,
            "synthetic body geometry self-test failed");
    std::cout << "Fiducial detection and geometry self-test passed (synthetic; no hardware "
                 "accuracy claim).\n";
}
void stop(int) {
    stopped = 1;
}
void save_json(const std::filesystem::path &path, const Json &json) {
    auto temporary = path;
    temporary += ".tmp";
    std::ofstream file(temporary);
    file << json.dump() << '\n';
    file.close();
    require(bool(file), "cannot write session metadata");
    std::filesystem::rename(temporary, path);
}
Json frames_json(const StereoPair &pair) {
    Json frames = Json::array();
    for (const auto &f : pair.frames)
        frames.push_back({{"camera_id", f.camera_id},
                          {"calibration_id", f.calibration_id},
                          {"capture_timestamp_ns", f.capture_time_ns},
                          {"clock", f.clock_domain},
                          {"width", f.width},
                          {"height", f.height}});
    return frames;
}
Json result_json(const StereoPair &pair, const PlanarPoseEstimator &estimator,
                 const PoseResult &result, double axis_length) {
    Json j{{"schema", "framephone-fiducial-pose-v1"},
           {"transform", "T_HM"},
           {"status", result.status},
           {"reason", result.reason},
           {"frames", frames_json(pair)},
           {"capture_skew_ns", pair.skew_ns()},
           {"calibration_status", "factory_imported"},
           {"orientation_source", "decoded_tag36h11_id0"},
           {"candidates", Json::array()}};
    for (const auto &p : result.candidates) {
        Json projections = Json::array();
        for (std::size_t v = 0; v < 2; ++v) {
            Json lines = Json::array();
            for (const auto &line : estimator.wireframe(p, v)) {
                Json pixels = Json::array();
                for (auto xy : line)
                    pixels.push_back({xy.x, xy.y});
                lines.push_back(pixels);
            }
            projections.push_back(lines);
        }
        Json axes = Json::array();
        for (std::size_t view = 0; view < 2; ++view) {
            Json lines = Json::array();
            for (std::size_t axis = 0; axis < 3; ++axis) {
                Json line = Json::array();
                for (int step = 0; step <= 8; ++step) {
                    const double distance = axis_length * step / 8;
                    const Point3 head{p.translation_m[0] + p.rotation[axis] * distance,
                                      p.translation_m[1] + p.rotation[3 + axis] * distance,
                                      p.translation_m[2] + p.rotation[6 + axis] * distance};
                    double depth = 0;
                    auto pixel = estimator.rig().cameras[view].project(head, &depth);
                    if (depth <= 0 || !std::isfinite(pixel.x) || !std::isfinite(pixel.y)) {
                        line = Json::array();
                        break;
                    }
                    line.push_back({pixel.x, pixel.y});
                }
                lines.push_back(line);
            }
            axes.push_back(lines);
        }
        j["candidates"].push_back({{"rotation", p.rotation},
                                   {"translation_m", p.translation_m},
                                   {"rms_px", p.rms_px},
                                   {"max_error_px", p.max_error_px},
                                   {"wireframe", projections},
                                   {"axes", axes}});
    }
    return j;
}
void preview(const std::filesystem::path &directory, const StereoPair &pair, std::uint64_t index) {
    const auto slot = directory / ("preview-" + std::to_string(index % 3));
    std::filesystem::create_directories(slot);
    // Invalidate before replacing images. Readers check the token both before
    // and after loading, so a GUI can never overlay a pose on a different pair.
    std::filesystem::remove(slot / "token.json");
    for (std::size_t v = 0; v < 2; ++v) {
        const auto target = slot / (std::to_string(v) + ".pgm");
        auto temp = target;
        temp += ".tmp";
        write_pgm(temp, pair.frames[v]);
        std::filesystem::rename(temp, target);
    }
    save_json(slot / "token.json", index);
}
std::string waiting_status(const std::array<std::uint64_t, 2> &counts,
                           const std::array<std::uint64_t, 2> &captures) {
    std::ostringstream out;
    out << "Stereo waiting: left " << counts[0] << " frames, right " << counts[1] << " frames";
    if (captures[0] && captures[1]) {
        const auto skew =
            captures[0] > captures[1] ? captures[0] - captures[1] : captures[1] - captures[0];
        out << "; latest skew " << double(skew) / 1e6 << " ms (limit 3 ms)";
    } else
        out << "; no frames from "
            << (captures[0]   ? "right"
                : captures[1] ? "left"
                              : "either camera");
    return out.str();
}
void camera_preview(const std::filesystem::path &path, const std::string &camera) {
    std::cout.unsetf(std::ios::unitbuf);
    FrametopRing ring({path, camera, "camera-preview", "steam-frame-mono-v4l2"});
    TagDetector detector;
    auto last_frame = std::chrono::steady_clock::now();
    auto last_notice = last_frame;
    while (!stopped) {
        auto frame = ring.poll();
        auto now = std::chrono::steady_clock::now();
        if (!frame) {
            if (now - last_frame >= std::chrono::seconds(1) &&
                now - last_notice >= std::chrono::seconds(1)) {
                std::cout << Json{{"schema", "framephone-camera-preview-v1"},
                                  {"camera_id", camera},
                                  {"image_bytes", 0},
                                  {"reason", "Waiting for camera frames"}}
                                 .dump()
                          << '\n'
                          << std::flush;
                last_notice = now;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            continue;
        }
        last_frame = now;
        auto &image = frame->image;
        require(image.width <= 4096 && image.height <= 4096,
                "preview image exceeds 4096 pixels per side");
        auto tags = detector.detect(image);
        cv::Mat gray(int(image.height), int(image.width), CV_8U, image.pixels.data(),
                     image.stride_bytes);
        Json detections = Json::array();
        for (const auto &tag : tags) {
            Json corners = Json::array();
            cv::Point center{};
            for (std::size_t i = 0; i < 4; ++i) {
                auto a = tag.corners[i], b = tag.corners[(i + 1) % 4];
                cv::Point p{int(std::lround(a.x)), int(std::lround(a.y))};
                cv::Point q{int(std::lround(b.x)), int(std::lround(b.y))};
                cv::line(gray, p, q, cv::Scalar(0), 5);
                cv::line(gray, p, q, cv::Scalar(255), 2);
                corners.push_back({a.x, a.y});
                center += p;
            }
            center.x /= 4;
            center.y /= 4;
            cv::drawMarker(gray, center, cv::Scalar(0), cv::MARKER_CROSS, 15, 5);
            cv::drawMarker(gray, center, cv::Scalar(255), cv::MARKER_CROSS, 15, 2);
            auto label = "ID " + std::to_string(tag.id);
            cv::putText(gray, label, center + cv::Point(8, -8), cv::FONT_HERSHEY_SIMPLEX, .55,
                        cv::Scalar(0), 4);
            cv::putText(gray, label, center + cv::Point(8, -8), cv::FONT_HERSHEY_SIMPLEX, .55,
                        cv::Scalar(255), 1);
            detections.push_back({{"id", tag.id},
                                  {"hamming", tag.hamming},
                                  {"margin", tag.margin},
                                  {"corners", corners}});
        }
        const auto pgm =
            "P5\n" + std::to_string(image.width) + " " + std::to_string(image.height) + "\n255\n";
        std::cout << Json{{"schema", "framephone-camera-preview-v1"},
                          {"camera_id", camera},
                          {"sequence", frame->frame_number},
                          {"width", image.width},
                          {"height", image.height},
                          {"capture_timestamp_ns", image.capture_time_ns},
                          {"publish_monotonic_ns", frame->publish_monotonic_ns},
                          {"image_bytes", pgm.size() + std::size_t(image.width) * image.height},
                          {"detections", detections}}
                         .dump()
                  << '\n';
        std::cout << pgm;
        for (std::uint32_t y = 0; y < image.height; ++y)
            std::cout.write(reinterpret_cast<const char *>(image.pixels.data() +
                                                           std::size_t(y) * image.stride_bytes),
                            image.width);
        std::cout.flush();
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
    }
}
} // namespace

int main(int argc, char **argv) {
    std::cout.setf(std::ios::unitbuf);
    try {
        std::signal(SIGINT, stop);
        std::signal(SIGTERM, stop);
        auto parent = getppid();
        prctl(PR_SET_PDEATHSIG, SIGTERM);
        if (getppid() != parent)
            return 1;
        if (argc == 5 && std::string(argv[1]) == "--preview-ring" &&
            std::string(argv[3]) == "--camera") {
            camera_preview(argv[2], argv[4]);
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--self-test") {
            self_test();
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout << "FramePhone single AprilTag stereo tracker\n"
                         "  --self-test\n"
                         "  --preview-ring FILE --camera NAME (annotated per-camera preview)\n"
                         "  --session DIRECTORY --track --output NEW_DIRECTORY\n"
                         "  --session DIRECTORY --replay RECORDING --output NEW_DIRECTORY\n";
            return 0;
        }
        std::filesystem::path session, output, replay_path;
        std::string mode;
        std::set<std::string> seen;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            require(seen.insert(arg).second, "duplicate option");
            if (arg == "--track") {
                require(mode.empty(), "select one mode");
                mode = arg;
            } else if (arg == "--session" || arg == "--output" || arg == "--replay") {
                require(i + 1 < argc, "missing option value");
                const std::string value = argv[++i];
                require(!value.empty(), "empty option value");
                if (arg == "--session")
                    session = value;
                if (arg == "--output")
                    output = value;
                if (arg == "--replay") {
                    require(mode.empty(), "select one mode");
                    mode = arg;
                    replay_path = value;
                }
            } else
                throw std::invalid_argument("unknown option: " + arg);
        }
        require(!session.empty() && !mode.empty(), "provide --session and one mode; see --help");
        const bool running = mode == "--track" || mode == "--replay";
        require(running == !output.empty(), "--output is required only for track/replay");
        const auto config = read_json(session / "session.json");
        require(config.at("schema") == "framephone-fiducial-session-v1",
                "unsupported session schema");
        const auto &target = config.at("fiducial");
        require(target.at("family") == "tag36h11" && target.at("id") == 0, "unsupported fiducial");
        const auto edge = number(target.at("black_edge_m"));
        require(edge >= .01 && edge <= .2, "invalid measured black-edge size");
        const auto id = string(config.at("calibration_id"));
        const auto all = load_frametop_calibration(session / "factory", id);
        StereoRig rig{{all.at(string(config.at("left"))), all.at(string(config.at("right")))}};
        rig.cameras[0].calibration.camera_id = string(config.at("left_stream"));
        rig.cameras[1].calibration.camera_id = string(config.at("right_stream"));
        FiducialTracker tracker(edge, rig);
        const auto &estimator = tracker.estimator();
        const auto clock = string(config.at("capture_clock"));
        const auto max_pairs = integer(config.value("max_pairs", Json(1000000)), 1, 1000000);
        const bool record = config.value("record", false);
        StereoFramePairer pairer(rig);
        std::array<std::unique_ptr<FrametopRing>, 2> rings;
        std::unique_ptr<RecordedFrameSource> replay;
        if (!replay_path.empty())
            replay = std::make_unique<RecordedFrameSource>(replay_path);
        else
            for (std::size_t v = 0; v < 2; ++v)
                rings[v] = std::make_unique<FrametopRing>(RingOptions{
                    string(config.at("ring")), rig.cameras[v].calibration.camera_id, id, clock});
        std::unique_ptr<StereoRecorder> recorder;
        std::ofstream results;
        if (running) {
            require(std::filesystem::create_directory(output), "output directory must be new");
            results.open(output / "poses.jsonl");
            require(bool(results), "cannot create pose log");
            if (record)
                recorder = std::make_unique<StereoRecorder>(output / "paired-images");
        }
        std::signal(SIGINT, stop);
        std::signal(SIGTERM, stop);
        bool eof = false;
        std::uint64_t index = 0, recorded_bytes = 0;
        auto last_pair = std::chrono::steady_clock::now();
        auto last_status = last_pair;
        std::array<std::uint64_t, 2> received{}, captures{};
        while (!stopped && index < std::uint64_t(max_pairs)) {
            if (!replay && config.value("arcore_handoff", false) &&
                std::filesystem::exists(session / "optical-paused")) {
                pairer = StereoFramePairer(rig);
                last_pair = last_status = std::chrono::steady_clock::now();
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
                continue;
            }
            if (replay && !eof) {
                auto frame = replay->next();
                if (frame)
                    pairer.push(std::move(*frame));
                else
                    eof = true;
            } else if (!replay)
                for (std::size_t v = 0; v < rings.size(); ++v)
                    if (auto frame = rings[v]->poll()) {
                        ++received[v];
                        captures[v] = frame->image.capture_time_ns;
                        pairer.push(std::move(frame->image));
                    }
            auto pair = pairer.poll();
            if (!pair) {
                if (eof)
                    break;
                if (!replay) {
                    const auto now = std::chrono::steady_clock::now();
                    if (now - last_status >= std::chrono::seconds(1)) {
                        std::cerr << waiting_status(received, captures) << '\n';
                        last_status = now;
                    }
                    require(now - last_pair < std::chrono::seconds(5),
                            "no synchronized pair for 5 seconds; " +
                                waiting_status(received, captures));
                    std::this_thread::sleep_for(std::chrono::milliseconds(2));
                }
                continue;
            }
            last_pair = std::chrono::steady_clock::now();
            ++index;
            if (recorder) {
                for (const auto &f : pair->frames)
                    recorded_bytes += std::uint64_t(f.width) * f.height;
                require(recorded_bytes <= 512ULL * 1024 * 1024,
                        "512 MiB image recording limit reached; start another trial");
                recorder->write(*pair, index);
            }
            const auto result = tracker.update(*pair);
            auto message = result_json(*pair, estimator, result.pose, edge * .5);
            message["fiducial"] = target;
            message["scale_status"] = "phone_reported_unverified";
            message["detections"] = Json::array();
            for (const auto &view : result.detections) {
                Json tags = Json::array();
                for (const auto &tag : view) {
                    Json corners = Json::array();
                    for (auto p : tag.corners)
                        corners.push_back({p.x, p.y});
                    tags.push_back({{"id", tag.id},
                                    {"hamming", tag.hamming},
                                    {"margin", tag.margin},
                                    {"corners", corners}});
                }
                message["detections"].push_back(tags);
            }
            message["processing_ms"] = std::chrono::duration<double, std::milli>(
                                           std::chrono::steady_clock::now() - last_pair)
                                           .count();
            message["observed_host_monotonic_ns"] = std::uint64_t(
                std::chrono::duration_cast<std::chrono::nanoseconds>(last_pair.time_since_epoch())
                    .count());
            message["processed_host_monotonic_ns"] =
                std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                  std::chrono::steady_clock::now().time_since_epoch())
                                  .count());
            message["pair"] = index;
            // Pose logs preserve measurements; preview slots remain bounded even
            // when image recording is off. No network credentials are recorded.
            results << message.dump() << '\n';
            results.flush();
            require(bool(results) && results.tellp() <= 128LL * 1024 * 1024,
                    "pose log write failed or 128 MiB trial limit reached");
            preview(output, *pair, index);
            message["preview_slot"] = index % 3;
            std::cout << message.dump() << '\n';
        }
        require(index > 0 || stopped, "input ended without a synchronized pair");
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "framephone-fiducial: " << e.what() << '\n';
        return 1;
    }
}
