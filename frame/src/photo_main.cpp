#include "calibration_json.hpp"
#include "framephone/frametop_ring.hpp"
#include "framephone/photo.hpp"
#include "framephone/stereo_recording.hpp"
#include <csignal>
#include <iostream>
#include <opencv2/core.hpp>
#include <thread>

namespace {
using namespace framephone;
using namespace calibration_json;
volatile std::sig_atomic_t stopped = 0;
void stop(int) {
    stopped = 1;
}
void self_test() {
    StereoRig rig;
    StereoPair pair;
    for (std::size_t v = 0; v < 2; ++v) {
        auto &camera = rig.cameras[v];
        camera.calibration = {"synthetic",
                              v ? "right" : "left",
                              "fisheye_kb4",
                              "synthetic",
                              640,
                              480,
                              600,
                              600,
                              319.5,
                              239.5,
                              {.04, -.01, .001, -.0001}};
        camera.rotation = {1, 0, 0, 0, -1, 0, 0, 0, -1};
        camera.origin_m = {v ? .032 : -.032, 0, 0};
        pair.frames[v] = {camera.calibration.camera_id,
                          640,
                          480,
                          640,
                          PixelFormat::Gray8,
                          1,
                          "synthetic",
                          "synthetic",
                          {},
                          std::vector<std::uint8_t>(640 * 480)};
    }
    std::vector<PhotoMatch> matches;
    for (int y = 0; y < 7; ++y)
        for (int x = 0; x < 6; ++x) {
            ImagePoint p{-.4 + x * .16, .6 - y * .2};
            std::array<ImagePoint, 2> pixels;
            for (std::size_t v = 0; v < 2; ++v)
                pixels[v] = rig.cameras[v].project({p.x * .07, p.y * .07, -.6});
            matches.push_back({p, pixels});
        }
    auto result = estimate_photo_pose(rig, pair, matches, 1.5);
    require(result.status == "measured" && std::abs(result.width_m - .07) < 1e-6 &&
                std::abs(result.pose.translation_m[2] + .6) < 1e-6,
            "photo stereo geometry self-test failed");
    std::cout << "Photo stereo geometry self-test passed (synthetic; photo matching and hardware "
                 "accuracy unverified).\n";
}
void save(const std::filesystem::path &path, const Json &j) {
    auto temporary = path;
    temporary += ".tmp";
    std::ofstream f(temporary);
    f << j.dump() << '\n';
    f.close();
    require(bool(f), "cannot write photo diagnostic metadata");
    std::filesystem::rename(temporary, path);
}
Json result_json(const StereoPair &pair, const PhotoPose &result, const std::string &identity) {
    Json j{{"schema", "framephone-photo-pose-v1"},
           {"transform", "T_HP"},
           {"origin", "displayed_photo_center"},
           {"reference_id", identity},
           {"status", result.status},
           {"reason", result.reason},
           {"view_inliers", result.view_inliers},
           {"reference_features", result.reference_features},
           {"scene_features", result.scene_features},
           {"descriptor_matches", result.descriptor_matches},
           {"stereo_candidates", result.stereo_candidates},
           {"triangulated", result.triangulated},
           {"pose_inliers", result.pose_inliers},
           {"coverage", result.coverage},
           {"capture_skew_ns", pair.skew_ns()},
           {"scale_source", "factory_calibrated_stereo"},
           {"calibration_status", "factory_imported"},
           {"alignment_status", "not_implemented"},
           {"frames", Json::array()},
           {"matches", Json::array()},
           {"view_points", Json::array()},
           {"search_outline", Json::array()},
           {"outline", Json::array()}};
    for (std::size_t v = 0; v < 2; ++v) {
        for (auto key : {"view_points", "search_outline"}) {
            Json points = Json::array();
            const auto &source = std::string(key) == "view_points" ? result.view_points[v]
                                                                   : result.search_outline[v];
            for (auto p : source)
                points.push_back({p.x, p.y});
            j[key].push_back(std::move(points));
        }
    }
    for (const auto &f : pair.frames) {
        Json frame{{"camera_id", f.camera_id}, {"capture_timestamp_ns", f.capture_time_ns},
                   {"clock", f.clock_domain},  {"calibration_id", f.calibration_id},
                   {"width", f.width},         {"height", f.height}};
        if (f.exposure_us)
            frame["exposure_us"] = *f.exposure_us;
        if (f.ring_transport) {
            const auto &r = *f.ring_transport;
            frame["transport"] = {{"frame_number", r.frame_number},
                                  {"dequeue_monotonic_ns", r.dequeue_monotonic_ns},
                                  {"publish_monotonic_ns", r.publish_monotonic_ns},
                                  {"v4l2_sequence", r.v4l2_sequence},
                                  {"skipped_since_previous", r.skipped_since_previous}};
        }
        j["frames"].push_back(frame);
    }
    if (result.status == "measured") {
        j["pose"] = {
            {"rotation", result.pose.rotation}, {"translation_m", result.pose.translation_m},
            {"width_m", result.width_m},        {"height_m", result.height_m},
            {"rms_px", result.pose.rms_px},     {"max_error_px", result.pose.max_error_px}};
        for (const auto &m : result.matches)
            j["matches"].push_back(
                {{"reference", {m.reference.x, m.reference.y}},
                 {"pixels", {{m.pixels[0].x, m.pixels[0].y}, {m.pixels[1].x, m.pixels[1].y}}}});
        for (const auto &view : result.outline) {
            Json points = Json::array();
            for (auto p : view)
                points.push_back({p.x, p.y});
            j["outline"].push_back(points);
        }
    }
    return j;
}
void preview(const std::filesystem::path &out, const StereoPair &pair, std::uint64_t index) {
    const auto slot = out / ("preview-" + std::to_string(index % 3));
    std::filesystem::create_directories(slot);
    std::filesystem::remove(slot / "token.json");
    for (std::size_t v = 0; v < 2; ++v) {
        auto path = slot / (std::to_string(v) + ".pgm");
        auto temp = path;
        temp += ".tmp";
        write_pgm(temp, pair.frames[v]);
        std::filesystem::rename(temp, path);
    }
    save(slot / "token.json", index);
}
} // namespace
int main(int argc, char **argv) {
    std::cout.setf(std::ios::unitbuf);
    try {
        cv::setNumThreads(2);
        if (argc == 2 && std::string(argv[1]) == "--self-test") {
            self_test();
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout
                << "FramePhone fixed-photo stereo tracker\n"
                   "  --self-test\n"
                   "  --session DIR --track --output NEW_DIR\n"
                   "  --session DIR --replay RECORDING --output NEW_DIR\n"
                   "Uses factory KB4 pixel rays; no target-size/DPI assumption or ARCore fusion.\n";
            return 0;
        }
        std::filesystem::path session, output, replay_path;
        bool live = false;
        std::set<std::string> seen;
        for (int i = 1; i < argc; ++i) {
            std::string arg = argv[i];
            require(seen.insert(arg).second, "duplicate photo option");
            if (arg == "--track")
                live = true;
            else if (arg == "--session" || arg == "--output" || arg == "--replay") {
                require(i + 1 < argc, "missing option value");
                std::filesystem::path value = argv[++i];
                if (arg == "--session")
                    session = value;
                else if (arg == "--output")
                    output = value;
                else
                    replay_path = value;
            } else
                throw std::invalid_argument("unknown photo option");
        }
        require(!session.empty() && !output.empty() && live != !replay_path.empty(),
                "provide --session, --output and one of --track/--replay; see --help");
        auto config = read_json(session / "session.json");
        require(config.at("schema") == "framephone-photo-session-v1", "unsupported photo session");
        auto id = string(config.at("calibration_id")),
             reference_id = string(config.at("reference_id"));
        auto cameras = load_frametop_calibration(session / "factory", id);
        StereoRig rig{
            {cameras.at(string(config.at("left"))), cameras.at(string(config.at("right")))}};
        rig.cameras[0].calibration.camera_id = string(config.at("left_stream"));
        rig.cameras[1].calibration.camera_id = string(config.at("right_stream"));
        RecordedFrameSource references(session / "reference");
        auto reference = references.next();
        require(reference && !references.next(), "expected one reference image");
        require(reference->calibration_id == reference_id, "reference identity mismatch");
        PhotoTracker tracker(std::move(*reference), rig);
        StereoFramePairer pairer(rig);
        std::array<std::unique_ptr<FrametopRing>, 2> rings;
        std::unique_ptr<RecordedFrameSource> replay;
        if (!live)
            replay = std::make_unique<RecordedFrameSource>(replay_path);
        else
            for (std::size_t v = 0; v < 2; ++v)
                rings[v] = std::make_unique<FrametopRing>(
                    RingOptions{string(config.at("ring")), rig.cameras[v].calibration.camera_id, id,
                                string(config.at("capture_clock"))});
        require(std::filesystem::create_directory(output), "photo output directory must be new");
        std::ofstream log(output / "poses.jsonl");
        require(bool(log), "cannot open photo pose log");
        std::unique_ptr<StereoRecorder> recorder;
        if (config.value("record", false))
            recorder = std::make_unique<StereoRecorder>(output / "paired-images");
        std::signal(SIGINT, stop);
        std::signal(SIGTERM, stop);
        std::uint64_t index = 0, bytes = 0;
        bool eof = false;
        auto last = std::chrono::steady_clock::now();
        const auto max_pairs = integer(config.value("max_pairs", Json(1000000)), 1, 1000000);
        while (!stopped && index < std::uint64_t(max_pairs)) {
            if (replay && !eof) {
                if (auto f = replay->next())
                    pairer.push(std::move(*f));
                else
                    eof = true;
            } else if (live)
                for (auto &ring : rings)
                    if (auto f = ring->poll())
                        pairer.push(std::move(f->image));
            auto pair = pairer.poll();
            if (!pair) {
                if (eof)
                    break;
                require(std::chrono::steady_clock::now() - last < std::chrono::seconds(5),
                        "no synchronized front pair for 5 seconds; verify mapping and clocks");
                if (live)
                    std::this_thread::sleep_for(std::chrono::milliseconds(2));
                continue;
            }
            last = std::chrono::steady_clock::now();
            ++index;
            if (recorder) {
                for (const auto &f : pair->frames)
                    bytes += std::uint64_t(f.width) * f.height;
                require(bytes <= 512ULL * 1024 * 1024, "512 MiB camera recording limit reached");
                recorder->write(*pair, index);
            }
            auto result = tracker.update(*pair);
            auto j = result_json(*pair, result, reference_id);
            j["processing_ms"] =
                std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - last)
                    .count();
            j["pair"] = index;
            log << j.dump() << '\n';
            log.flush();
            require(bool(log) && log.tellp() <= 128LL * 1024 * 1024,
                    "photo log write failed or 128 MiB limit reached");
            preview(output, *pair, index);
            j["preview_slot"] = index % 3;
            std::cout << j.dump() << '\n';
        }
        require(index > 0 || stopped, "input ended without synchronized camera pairs");
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "framephone-photo: " << e.what() << '\n';
        return 1;
    }
}
