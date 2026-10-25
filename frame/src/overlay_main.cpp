#include "arcore_handoff.hpp"
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <dlfcn.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <openvr.h>
#include <sys/prctl.h>
#include <thread>
#include <time.h>
#include <unistd.h>

namespace {
using namespace framephone::surface;
using Json = nlohmann::json;
volatile std::sig_atomic_t stopped = 0;
void stop(int) {
    stopped = 1;
}
std::uint64_t now_ns() {
    timespec t{};
    clock_gettime(CLOCK_MONOTONIC, &t);
    return std::uint64_t(t.tv_sec) * 1'000'000'000 + std::uint64_t(t.tv_nsec);
}
Json read(const std::filesystem::path &path) {
    if (std::filesystem::file_size(path) > 65536)
        throw std::runtime_error("VR metadata exceeds limit");
    std::ifstream file(path);
    return Json::parse(file);
}
std::filesystem::path client_library() {
    if (const char *explicit_path = std::getenv("FRAMEPHONE_OPENVR_LIBRARY"))
        return explicit_path;
    const char *config = std::getenv("XDG_CONFIG_HOME"), *home = std::getenv("HOME");
    auto directory = config ? std::filesystem::path(config)
                     : home ? std::filesystem::path(home) / ".config"
                            : std::filesystem::path{};
#if defined(__aarch64__)
    const char *platform = "linuxarm64";
#else
    const char *platform = "linux64";
#endif
    auto registry = directory / "openvr/openvrpaths.vrpath";
    if (std::filesystem::exists(registry))
        for (const auto &runtime : read(registry).at("runtime")) {
            auto path = std::filesystem::path(runtime.get<std::string>()) / "bin" / platform /
                        "libopenvr_api.so";
            if (std::filesystem::is_regular_file(path))
                return path;
        }
    auto fallback = std::filesystem::path("/opt/steamvr/bin") / platform / "libopenvr_api.so";
    if (std::filesystem::is_regular_file(fallback))
        return fallback;
    throw std::runtime_error("SteamVR client library not found; run on Frame with SteamVR active");
}
struct Client {
    void *library = nullptr;
    void (*shutdown)() = nullptr;
    vr::IVROverlay *overlay = nullptr;
    vr::IVRSystem *system = nullptr;
    bool initialized = false;
    template <typename T> T symbol(const char *name) {
        auto value = dlsym(library, name);
        if (!value)
            throw std::runtime_error(std::string("SteamVR missing client symbol: ") + name);
        return reinterpret_cast<T>(value);
    }
    void open() {
        auto path = client_library();
        library = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
        if (!library)
            throw std::runtime_error(std::string("Cannot load SteamVR client: ") + dlerror());
        auto init =
            symbol<std::uint32_t (*)(vr::EVRInitError *, vr::EVRApplicationType, const char *)>(
                "VR_InitInternal2");
        shutdown = symbol<void (*)()>("VR_ShutdownInternal");
        auto interface =
            symbol<void *(*)(const char *, vr::EVRInitError *)>("VR_GetGenericInterface");
        auto description =
            symbol<const char *(*)(vr::EVRInitError)>("VR_GetVRInitErrorAsEnglishDescription");
        vr::EVRInitError error = vr::VRInitError_None;
        init(&error, vr::VRApplication_Overlay, nullptr);
        if (error != vr::VRInitError_None)
            throw std::runtime_error(std::string("SteamVR overlay initialization failed: ") +
                                     description(error));
        initialized = true;
        overlay = static_cast<vr::IVROverlay *>(interface(vr::IVROverlay_Version, &error));
        if (!overlay || error != vr::VRInitError_None)
            throw std::runtime_error("SteamVR overlay interface unavailable");
        system = static_cast<vr::IVRSystem *>(interface(vr::IVRSystem_Version, &error));
        if (!system || error != vr::VRInitError_None)
            throw std::runtime_error("SteamVR system interface unavailable");
    }
    ~Client() {
        if (initialized)
            shutdown();
        if (library)
            dlclose(library);
    }
};
struct Display {
    Client &client;
    Geometry screen;
    vr::VROverlayHandle_t handle = vr::k_ulOverlayHandleInvalid;
    explicit Display(Client &c, Geometry g) : client(c), screen(g) {}
    void check(vr::EVROverlayError result) {
        if (result != vr::VROverlayError_None)
            throw std::runtime_error(std::string("VR screen: ") +
                                     client.overlay->GetOverlayErrorNameFromEnum(result));
    }
    void create() {
        auto key = "framephone.screen." + std::to_string(getpid());
        check(client.overlay->CreateOverlay(key.c_str(), "FramePhone screen", &handle));
        check(client.overlay->SetOverlayFlag(handle, vr::VROverlayFlags_VisibleInDashboard, true));
        check(client.overlay->SetOverlayWidthInMeters(handle, float(screen.width)));
        check(client.overlay->SetOverlayTexelAspect(handle, float(screen.texel_aspect())));
        auto pixels = texture();
        check(client.overlay->SetOverlayRaw(handle, pixels.data(), texture_size, texture_size, 4));
    }
    void update(const std::optional<Matrix> &pose, bool world = false) {
        if (!pose) {
            check(client.overlay->HideOverlay(handle));
            return;
        }
        vr::HmdMatrix34_t matrix{};
        for (int row = 0; row < 3; ++row)
            for (int col = 0; col < 4; ++col)
                matrix.m[row][col] = float((*pose)[row * 4 + col]);
        if (world)
            check(client.overlay->SetOverlayTransformAbsolute(handle, vr::TrackingUniverseStanding,
                                                              &matrix));
        else
            check(client.overlay->SetOverlayTransformTrackedDeviceRelative(
                handle, vr::k_unTrackedDeviceIndex_Hmd, &matrix));
        check(client.overlay->ShowOverlay(handle));
    }
    ~Display() {
        if (handle != vr::k_ulOverlayHandleInvalid) {
            client.overlay->HideOverlay(handle);
            client.overlay->DestroyOverlay(handle);
        }
    }
};
void self_test() {
    Json message{{"schema", "framephone-fiducial-pose-v1"},
                 {"transform", "T_HM"},
                 {"status", "measured"},
                 {"processed_host_monotonic_ns", std::uint64_t(1'000'000'000)},
                 {"candidates", Json::array({{{"rotation", {1, 0, 0, 0, 1, 0, 0, 0, 1}},
                                              {"translation_m", {.1, .2, -.6}}}})}};
    auto check = [](bool ok) {
        if (!ok)
            throw std::runtime_error("VR surface self-test failed");
    };
    auto transform = pose(message, 1'010'000'000);
    check(transform && (*transform)[3] == .1 && (*transform)[7] == .2 && (*transform)[11] == -.6);
    check(!pose(message, 1'250'000'001) && !pose(message, 999'999'999));
    message["status"] = "lost";
    check(!pose(message, 1'010'000'000));
    message["status"] = "measured";
    message["candidates"][0]["rotation"][0] = -1;
    bool rejected = false;
    try {
        pose(message, 1'010'000'000);
    } catch (const std::exception &) {
        rejected = true;
    }
    check(rejected);
    Json session{{"schema", "framephone-fiducial-session-v1"},
                 {"fiducial",
                  {{"black_edge_m", .064},
                   {"screen_width_px", 1080},
                   {"screen_height_px", 2400},
                   {"black_edge_px", 864}}}};
    auto screen = Geometry::from_session(session);
    check(std::abs(screen.width - .08) < 1e-12 && std::abs(screen.height - 8. / 45) < 1e-12);
    check(std::abs(screen.width / screen.texel_aspect() - screen.height) < 1e-12);
    auto invalid = session;
    invalid["fiducial"].erase("screen_width_px");
    rejected = false;
    try {
        Geometry::from_session(invalid);
    } catch (const std::exception &) {
        rejected = true;
    }
    check(rejected);
    invalid = session;
    invalid["fiducial"]["black_edge_px"] = 0;
    rejected = false;
    try {
        Geometry::from_session(invalid);
    } catch (const std::exception &) {
        rejected = true;
    }
    check(rejected);
    const auto pixels = texture();
    check(pixels[3] == 255 &&
          pixels[(texture_size / 2 * texture_size + texture_size / 2) * 4 + 3] == 100);
    std::cout << "VR screen pose validation, stale/lost rejection, physical dimensions and "
                 "rectangle texture passed "
                 "(no SteamVR required).\n";
}
} // namespace
int main(int argc, char **argv) {
    std::cout.setf(std::ios::unitbuf);
    try {
        if (argc == 2 && std::string(argv[1]) == "--self-test") {
            self_test();
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout << "FramePhone head-relative VR screen rectangle\n  --session DIRECTORY\n "
                         " --self-test\n";
            return 0;
        }
        if (argc != 3 || std::string(argv[1]) != "--session")
            throw std::runtime_error("use --session DIRECTORY or --self-test");
        auto parent = getppid();
        prctl(PR_SET_PDEATHSIG, SIGTERM);
        if (getppid() != parent)
            return 1;
        std::signal(SIGTERM, stop);
        std::signal(SIGINT, stop);
        auto session = std::filesystem::path(argv[2]);
        const auto config = read(session / "session.json");
        auto geometry = Geometry::from_session(config);
        const bool arcore = config.value("arcore_handoff", false);
        ArcoreHandoff handoff;
        std::uint64_t last_state_write = 0;
        Client client;
        client.open();
        Display display(client, geometry);
        display.create();
        std::cout << (arcore ? "VR screen ready: ARCore handoff; hold phone and headset still.\n"
                             : "VR screen ready: fiducial-driven rectangle; headset alignment and "
                               "motion timing are provisional.\n");
        std::string previous_state;
        while (!stopped) {
            vr::VREvent_t event{};
            while (client.system->PollNextEvent(&event, sizeof(event)))
                if (event.eventType == vr::VREvent_Quit)
                    stopped = 1;
                else if (event.eventType == vr::VREvent_StandingZeroPoseReset ||
                         event.eventType == vr::VREvent_SeatedZeroPoseReset ||
                         event.eventType == vr::VREvent_ChaperoneUniverseHasChanged)
                    handoff.reset("headset tracking origin changed; show marker again");
            vr::TrackedDevicePose_t head{};
            client.system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding, 0, &head,
                                                           1);
            const auto now = now_ns();
            const bool head_valid = head.bPoseIsValid && head.bDeviceIsConnected;
            if (head_valid) {
                Matrix matrix{};
                for (int r = 0; r < 3; ++r)
                    for (int c = 0; c < 4; ++c)
                        matrix[r * 4 + c] = head.mDeviceToAbsoluteTracking.m[r][c];
                handoff.head(now, matrix);
            }
            std::optional<Matrix> current;
            std::string state = "waiting for an accepted optical pose";
            try {
                if (arcore && !stopped && head_valid) {
                    Json phone = Json::object(), optical = Json::object();
                    if (std::filesystem::exists(session / "phone-pose.json"))
                        phone = read(session / "phone-pose.json");
                    if (std::filesystem::exists(session / "vr-pose.json"))
                        optical = read(session / "vr-pose.json");
                    if (!phone.empty() && phone.at("session") != config.at("phone_session"))
                        throw std::runtime_error("phone session changed");
                    current = handoff.update(phone, optical, now);
                    state = handoff.state.at("reason").get<std::string>();
                } else if (!arcore && !stopped &&
                           std::filesystem::exists(session / "vr-pose.json")) {
                    const auto message = read(session / "vr-pose.json");
                    current = pose(message, now_ns());
                    state = current ? "visible"
                            : message.value("status", "") == "measured"
                                ? "hidden: pose stale (over 250 ms) or clock invalid"
                                : "hidden: no accepted optical pose";
                }
            } catch (const std::exception &error) {
                state = std::string("hidden: ") + error.what();
                handoff.reset(state);
            }
            if (!head_valid) {
                current.reset();
                state = "hidden: headset tracking unavailable";
                handoff.reset(state);
            }
            if (arcore && now - last_state_write >= 100'000'000) {
                auto status = handoff.state;
                status["updated_host_monotonic_ns"] = now;
                const auto temporary = session / "arcore-state.json.tmp";
                std::ofstream file(temporary);
                file << status.dump() << '\n';
                file.close();
                if (!file)
                    throw std::runtime_error("cannot publish ARCore handoff state");
                std::filesystem::rename(temporary, session / "arcore-state.json");
                last_state_write = now;
            }
            if (state != previous_state) {
                std::cout << "VR screen " << state << '\n';
                previous_state = state;
            }
            display.update(current, arcore);
            std::this_thread::sleep_for(std::chrono::milliseconds(16));
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "framephone-overlay: " << error.what() << '\n';
        return 1;
    }
}
