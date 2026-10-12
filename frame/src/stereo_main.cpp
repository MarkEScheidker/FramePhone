#include "framephone/diagnostic.hpp"
#include "framephone/frametop_ring.hpp"
#include "framephone/stereo.hpp"
#include <charconv>
#include <cmath>
#include <csignal>
#include <fstream>
#include <iostream>
#include <set>
#include <thread>

namespace {
using namespace framephone;
volatile std::sig_atomic_t stopped = 0;
void stop(int) {
    stopped = 1;
}
struct Options {
    std::filesystem::path root{"/"}, ring, replay, layout, jsonl, csv, record;
    std::string left, right, left_ring, right_ring, id, clock;
    std::uint32_t frames{300}, idle_ms{5000}, skew_us{3000};
    bool list{}, list_ring{};
};
void help() {
    std::cout << "FramePhone stereo headset diagnostic (native Linux; terminal output)\n"
                 "  --list-cameras --factory-root ROOT --calibration-id ID\n"
                 "  --list-ring FILE                Inspect ring names/sensors/video nodes\n"
                 "  --ring FILE | --replay DIRECTORY\n"
                 "  --left NAME --right NAME       Factory sourceCamera names\n"
                 "  --left-ring NAME --right-ring NAME  Explicit corresponding ring slugs\n"
                 "  --factory-root ROOT           Contains persist/*.json (default /)\n"
                 "  --calibration-id ID            Your revision of these factory files\n"
                 "  --phone-layout FILE            Current Android layout export\n"
                 "  --capture-clock NAME           Verified shared capture clock; required live\n"
                 "  --frames N                     Pair limit (default 300, max 1000000)\n"
                 "  --max-skew-us N                Capture tolerance (default/max 3000)\n"
                 "  --idle-timeout-ms N             No-pair failure (default 5000, max 60000)\n"
                 "  --pose-jsonl FILE --csv FILE    Optional exports, refuse existing files\n"
                 "  --record-dir DIRECTORY         Save paired raw PGM images + manifest\n"
                 "Outputs T_HP: phone meters -> headset, right/up/back. No world/XR pose.\n";
}
std::uint32_t positive(const std::string &s) {
    std::uint32_t n{};
    const auto [end, ec] = std::from_chars(s.data(), s.data() + s.size(), n);
    if (ec != std::errc{} || end != s.data() + s.size() || !n)
        throw std::invalid_argument("expected positive integer");
    return n;
}
Options parse(int argc, char **argv) {
    Options o;
    std::set<std::string> seen;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (!seen.insert(arg).second)
            throw std::invalid_argument("duplicate option: " + arg);
        if (arg == "--list-cameras") {
            o.list = true;
            continue;
        }
        if (i + 1 >= argc)
            throw std::invalid_argument("missing value for " + arg);
        const std::string value = argv[++i];
        if (value.empty())
            throw std::invalid_argument("empty value for " + arg);
        if (arg == "--list-ring") {
            o.list_ring = true;
            o.ring = value;
        } else if (arg == "--factory-root")
            o.root = value;
        else if (arg == "--ring")
            o.ring = value;
        else if (arg == "--replay")
            o.replay = value;
        else if (arg == "--left")
            o.left = value;
        else if (arg == "--right")
            o.right = value;
        else if (arg == "--left-ring")
            o.left_ring = value;
        else if (arg == "--right-ring")
            o.right_ring = value;
        else if (arg == "--calibration-id")
            o.id = value;
        else if (arg == "--capture-clock")
            o.clock = value;
        else if (arg == "--phone-layout")
            o.layout = value;
        else if (arg == "--pose-jsonl")
            o.jsonl = value;
        else if (arg == "--csv")
            o.csv = value;
        else if (arg == "--record-dir")
            o.record = value;
        else if (arg == "--frames")
            o.frames = positive(value);
        else if (arg == "--idle-timeout-ms")
            o.idle_ms = positive(value);
        else if (arg == "--max-skew-us")
            o.skew_us = positive(value);
        else
            throw std::invalid_argument("unknown option: " + arg);
    }
    if (o.list_ring) {
        if (seen.size() != 1)
            throw std::invalid_argument("--list-ring only accepts a ring path");
        return o;
    }
    if (o.id.empty())
        throw std::invalid_argument("--calibration-id is required");
    if (o.list) {
        for (const auto &key : seen)
            if (key != "--list-cameras" && key != "--factory-root" && key != "--calibration-id")
                throw std::invalid_argument(
                    "--list-cameras only accepts --factory-root and --calibration-id");
        return o;
    }
    if (o.ring.empty() == o.replay.empty())
        throw std::invalid_argument("select --ring or --replay");
    if (o.left.empty() || o.right.empty() || o.left == o.right || o.layout.empty())
        throw std::invalid_argument("provide distinct --left/--right names and --phone-layout");
    if (!o.ring.empty() && o.clock.empty())
        throw std::invalid_argument("live stereo requires --capture-clock");
    if (o.left_ring.empty() != o.right_ring.empty() || (!o.ring.empty() && o.left_ring.empty()))
        throw std::invalid_argument(
            "live input requires explicit --left-ring and --right-ring mappings");
    if (!o.left_ring.empty() && o.left_ring == o.right_ring)
        throw std::invalid_argument("ring camera mappings must differ");
    if (o.frames > 1'000'000 || o.idle_ms > 60000 || o.skew_us > 3000)
        throw std::invalid_argument("numeric option exceeds its limit");
    if (o.id.find_first_of("\t\r\n") != std::string::npos ||
        o.clock.find_first_of("\t\r\n") != std::string::npos)
        throw std::invalid_argument("identities cannot contain TSV separators");
    std::vector<std::filesystem::path> outputs;
    for (const auto &p : {o.jsonl, o.csv, o.record})
        if (!p.empty()) {
            if (std::filesystem::exists(p))
                throw std::invalid_argument("output already exists: " + p.string());
            outputs.push_back(std::filesystem::weakly_canonical(p));
        }
    for (std::size_t i = 0; i < outputs.size(); ++i)
        for (std::size_t j = 0; j < i; ++j)
            if (outputs[i] == outputs[j])
                throw std::invalid_argument("export paths must differ");
    if (!o.record.empty())
        for (const auto &p : {o.csv, o.jsonl})
            if (!p.empty()) {
                const auto relative = std::filesystem::weakly_canonical(p).lexically_relative(
                    std::filesystem::weakly_canonical(o.record));
                if (!relative.empty() && *relative.begin() != "..")
                    throw std::invalid_argument(
                        "put CSV/JSONL outside the raw recording directory");
            }
    return o;
}
class Recorder {
  public:
    explicit Recorder(std::filesystem::path directory) : directory_(std::move(directory)) {
        if (!std::filesystem::create_directory(directory_))
            throw std::runtime_error("cannot create recording directory");
        manifest_.open(directory_ / "manifest.tsv");
        manifest_ << "framephone-recording-v1\n";
        if (!manifest_)
            throw std::runtime_error("cannot write recording manifest");
    }
    void write(const StereoPair &pair, std::uint64_t index) {
        for (std::size_t v = 0; v < 2; ++v) {
            const auto &f = pair.frames[v];
            for (const auto &field : {f.camera_id, f.clock_domain, f.calibration_id})
                if (field.find_first_of("\t\r\n") != std::string::npos)
                    throw std::invalid_argument("recording identity contains TSV separators");
            const auto name = "pair-" + std::to_string(index) + "-" + std::to_string(v) + ".pgm";
            std::ofstream image(directory_ / name, std::ios::binary);
            image << "P5\n" << f.width << ' ' << f.height << "\n255\n";
            for (std::uint32_t y = 0; y < f.height; ++y)
                image.write(reinterpret_cast<const char *>(f.pixels.data() +
                                                           std::size_t(y) * f.stride_bytes),
                            f.width);
            image.close();
            if (!image)
                throw std::runtime_error("failed writing recording image");
            manifest_ << f.camera_id << '\t' << f.capture_time_ns << '\t' << f.clock_domain << '\t'
                      << f.calibration_id << '\t';
            if (f.exposure_us)
                manifest_ << *f.exposure_us;
            else
                manifest_ << '-';
            manifest_ << '\t' << name << '\n';
        }
        manifest_.flush();
        if (!manifest_)
            throw std::runtime_error("failed writing recording manifest");
    }

  private:
    std::filesystem::path directory_;
    std::ofstream manifest_;
};
} // namespace
int main(int argc, char **argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--help") {
            help();
            return 0;
        }
        const auto o = parse(argc, argv);
        if (o.list_ring) {
            for (const auto &c : list_frametop_cameras(o.ring))
                std::cout << c.name << " sensor=" << c.sensor << " video" << c.node << " "
                          << c.width << 'x' << c.height << " flags=" << c.flags << '\n';
            return 0;
        }
        const auto all = load_frametop_calibration(o.root, o.id);
        if (o.list) {
            for (const auto &[name, c] : all) {
                std::cout << name << "  " << c.calibration.width << 'x' << c.calibration.height
                          << " KB4 origin_H_m=";
                for (double x : c.origin_m)
                    std::cout << x << ' ';
                std::cout << '\n';
            }
            return 0;
        }
        if (!all.contains(o.left) || !all.contains(o.right))
            throw std::invalid_argument(
                "selected names absent from factory KB4 cameras; use --list-cameras");
        StereoRig rig{{all.at(o.left), all.at(o.right)}};
        if (!o.left_ring.empty()) {
            rig.cameras[0].calibration.camera_id = o.left_ring;
            rig.cameras[1].calibration.camera_id = o.right_ring;
        }
        StereoPoseEstimator estimator(load_phone_layout(o.layout), rig);
        StereoFramePairer pairer(rig, std::uint64_t(o.skew_us) * 1000);
        std::array<std::unique_ptr<FrametopRing>, 2> rings;
        std::unique_ptr<RecordedFrameSource> replay;
        if (!o.ring.empty())
            for (std::size_t v = 0; v < 2; ++v)
                rings[v] = std::make_unique<FrametopRing>(
                    RingOptions{o.ring, rig.cameras[v].calibration.camera_id, o.id, o.clock});
        else
            replay = std::make_unique<RecordedFrameSource>(o.replay);
        AprilTag36h11Detector detector;
        std::ofstream jsonl, csv;
        if (!o.jsonl.empty()) {
            jsonl.open(o.jsonl);
            if (!jsonl)
                throw std::runtime_error("cannot open JSONL");
        }
        if (!o.csv.empty()) {
            csv.open(o.csv);
            if (!csv)
                throw std::runtime_error("cannot open CSV");
            write_diagnostic_csv_header(csv);
        }
        std::unique_ptr<Recorder> recorder;
        if (!o.record.empty())
            recorder = std::make_unique<Recorder>(o.record);
        std::signal(SIGINT, stop);
        std::signal(SIGTERM, stop);
        std::uint64_t processed{}, accepted{};
        bool eof = false;
        auto last_pair = std::chrono::steady_clock::now();
        std::cout << "Tracking " << rig.cameras[0].calibration.camera_id << " -> " << o.left
                  << " + " << rig.cameras[1].calibration.camera_id << " -> " << o.right
                  << "; T_HP, factory_imported, max skew " << o.skew_us << " us\n";
        while (!stopped && processed < o.frames) {
            if (replay && !eof) {
                auto f = replay->next();
                if (f)
                    pairer.push(std::move(*f));
                else
                    eof = true;
            } else if (!replay)
                for (auto &ring : rings) {
                    auto f = ring->poll();
                    if (f)
                        pairer.push(std::move(f->image));
                }
            auto pair = pairer.poll();
            if (!pair) {
                if (eof)
                    break;
                if (!replay) {
                    if (std::chrono::steady_clock::now() - last_pair >
                        std::chrono::milliseconds(o.idle_ms))
                        throw std::runtime_error("no synchronized pair before timeout; check "
                                                 "cameras, clock and capture skew; dropped=" +
                                                 std::to_string(pairer.dropped_frames()));
                    std::this_thread::sleep_for(std::chrono::milliseconds(2));
                }
                continue;
            }
            last_pair = std::chrono::steady_clock::now();
            const auto begin = last_pair;
            std::array<DetectionBatch, 2> batches{detector.detect(pair->frames[0]),
                                                  detector.detect(pair->frames[1])};
            const auto result = estimator.estimate(*pair, batches);
            ++processed;
            const double ms =
                std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - begin)
                    .count();
            if (result.status == "accepted")
                ++accepted;
            if (jsonl.is_open())
                write_stereo_jsonl(jsonl, *pair, estimator, result);
            if (csv.is_open())
                for (std::size_t v = 0; v < 2; ++v)
                    write_diagnostic_csv(csv, 1, processed, pair->frames[v], batches[v], true, ms);
            if (recorder)
                recorder->write(*pair, processed);
            std::cout << "pair=" << processed << " tags=" << batches[0].detections.size() << '/'
                      << batches[1].detections.size() << " shared=" << result.shared_tags
                      << " skew_us=" << pair->skew_ns() / 1000 << " status=" << result.status;
            if (result.status == "accepted") {
                const auto &p = result.candidates[0];
                const auto &t = p.translation_m;
                std::cout << " xyz_H_m=" << t[0] << ',' << t[1] << ',' << t[2]
                          << " distance_m=" << std::sqrt(t[0] * t[0] + t[1] * t[1] + t[2] * t[2])
                          << " rms_px=" << p.rms_px;
            }
            std::cout << " processing_ms=" << ms << '\n';
        }
        if (jsonl.is_open()) {
            jsonl.close();
            if (!jsonl)
                throw std::runtime_error("JSONL close failed");
        }
        if (csv.is_open()) {
            csv.close();
            if (!csv)
                throw std::runtime_error("CSV close failed");
        }
        std::cout << "pairs=" << processed << " accepted=" << accepted
                  << " dropped_unpaired=" << pairer.dropped_frames() << '\n';
        if (!processed && !stopped)
            throw std::runtime_error("input ended without a synchronized pair");
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "framephone-stereo: " << e.what() << '\n';
        return 1;
    }
}
