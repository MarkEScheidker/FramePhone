#include "headset_presence.hpp"
#include "phone_model.hpp"
#include "pose_smoothing.hpp"
#include "tracking_fade.hpp"
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <deque>
#include <dlfcn.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
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
struct Metadata {
    std::filesystem::path path;
    std::filesystem::file_time_type modified{};
    Json value = Json::object();
    bool loaded = false;
    const Json &get() {
        if (!std::filesystem::exists(path)) {
            loaded = false;
            value = Json::object();
        } else {
            auto stamp = std::filesystem::last_write_time(path);
            if (!loaded || stamp != modified) {
                value = read(path);
                modified = stamp;
                loaded = true;
            }
        }
        return value;
    }
};
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
    vr::IVRInput *input = nullptr;
    bool initialized = false;
    template <typename T> T symbol(const char *name) {
        auto value = dlsym(library, name);
        if (!value)
            throw std::runtime_error(std::string("SteamVR missing client symbol: ") + name);
        return reinterpret_cast<T>(value);
    }
    void open(vr::EVRApplicationType type = vr::VRApplication_Overlay) {
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
        init(&error, type, nullptr);
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
        input = static_cast<vr::IVRInput *>(interface(vr::IVRInput_Version, &error));
    }
    ~Client() {
        if (initialized)
            shutdown();
        if (library)
            dlclose(library);
    }
};
// Convex shell faces use the existing compositor path. Cull the far faces so
// transparency during the fade never exposes a mirrored screen or back text.
struct Display {
    struct Face {
        Surface surface;
        vr::VROverlayHandle_t handle = vr::k_ulOverlayHandleInvalid;
        bool shown = false;
        vr::VROverlayHandle_t spare = vr::k_ulOverlayHandleInvalid;
        bool loading = false, ready = false;
        double alpha = -1;
    };
    Client &client;
    PhoneModel model;
    std::vector<Face> faces;
    std::uint64_t diagnostics_at = 0;
    bool visible = false;
    explicit Display(Client &c, Geometry g) : client(c), model{g} {}
    void check(vr::EVROverlayError result) {
        if (result != vr::VROverlayError_None)
            throw std::runtime_error(std::string("VR phone: ") +
                                     client.overlay->GetOverlayErrorNameFromEnum(result));
    }
    void upload(const Face &face, Image image,
                vr::VROverlayHandle_t target = vr::k_ulOverlayHandleInvalid) {
        if (target == vr::k_ulOverlayHandleInvalid)
            target = face.handle;
        check(client.overlay->SetOverlayTexelAspect(
            target, float(face.surface.width / face.surface.height * image.height / image.width)));
        check(
            client.overlay->SetOverlayRaw(target, image.rgba.data(), image.width, image.height, 4));
    }
    void create_handle(vr::VROverlayHandle_t &handle, const std::string &key,
                       const Surface &surface) {
        check(client.overlay->CreateOverlay(key.c_str(), "FramePhone", &handle));
        check(client.overlay->SetOverlayFlag(handle, vr::VROverlayFlags_VisibleInDashboard, true));
        check(client.overlay->SetOverlayWidthInMeters(handle, float(surface.width)));
    }
    void create() {
        for (const auto &surface : model.surfaces()) {
            faces.push_back({surface});
            auto &face = faces.back();
            const auto key =
                "framephone.phone." + std::to_string(getpid()) + "." + std::to_string(faces.size());
            create_handle(face.handle, key, surface);
            if (surface.kind == PhoneFace::screen) {
                upload(face, Image(1, 1, 0));
                check(client.overlay->SetOverlaySortOrder(face.handle, 1));
            } else if (surface.kind == PhoneFace::back) {
                upload(face, diagnostic_texture(model, {}));
                create_handle(face.spare, key + ".spare", surface);
            } else
                upload(face, surface_texture(model, surface));
        }
    }
    void update(const PhonePresentation &presentation, bool world, const Matrix &head,
                const PhoneDiagnostics &diagnostics, std::uint64_t now) {
        const std::array<double, 3> eye = world ? std::array<double, 3>{head[3], head[7], head[11]}
                                                : std::array<double, 3>{0, 0, 0};
        visible = false;
        for (auto &face : faces) {
            if (face.spare != vr::k_ulOverlayHandleInvalid) {
                vr::VREvent_t event{};
                while (client.overlay->PollNextOverlayEvent(face.spare, &event, sizeof(event))) {
                    if (face.loading && event.eventType == vr::VREvent_ImageLoaded) {
                        face.loading = false;
                        face.ready = true;
                    } else if (event.eventType == vr::VREvent_ImageFailed) {
                        face.loading = face.ready = false;
                        std::cerr << "VR phone: diagnostic texture upload failed; retaining "
                                     "previous frame\n";
                    }
                }
            }
            const auto transform =
                presentation.pose ? compose(*presentation.pose, face.surface.local) : identity();
            const bool show =
                presentation.pose && presentation.opacity > 0 && facing(transform, eye);
            if (!show) {
                if (face.shown)
                    check(client.overlay->HideOverlay(face.handle));
                face.shown = false;
                continue;
            }
            vr::HmdMatrix34_t matrix{};
            for (int row = 0; row < 3; ++row)
                for (int col = 0; col < 4; ++col)
                    matrix.m[row][col] = float(transform[row * 4 + col]);
            if (world)
                check(client.overlay->SetOverlayTransformAbsolute(
                    face.handle, vr::TrackingUniverseStanding, &matrix));
            else
                check(client.overlay->SetOverlayTransformTrackedDeviceRelative(
                    face.handle, vr::k_unTrackedDeviceIndex_Hmd, &matrix));
            if (face.alpha != presentation.opacity) {
                check(client.overlay->SetOverlayAlpha(face.handle, float(presentation.opacity)));
                face.alpha = presentation.opacity;
            }
            if (face.ready && presentation.opacity == 1) {
                // SetOverlayRaw loads asynchronously. Only swap fully loaded
                // hidden textures; keep the current back visible until this point.
                // Swap at full opacity so temporary overlap cannot brighten a fade.
                if (world)
                    check(client.overlay->SetOverlayTransformAbsolute(
                        face.spare, vr::TrackingUniverseStanding, &matrix));
                else
                    check(client.overlay->SetOverlayTransformTrackedDeviceRelative(
                        face.spare, vr::k_unTrackedDeviceIndex_Hmd, &matrix));
                check(client.overlay->SetOverlayAlpha(face.spare, float(presentation.opacity)));
                check(client.overlay->ShowOverlay(face.spare));
                check(client.overlay->HideOverlay(face.handle));
                std::swap(face.handle, face.spare);
                face.ready = false;
                face.shown = true;
            }
            if (face.surface.kind == PhoneFace::back && !face.loading && !face.ready &&
                (!face.shown || now - diagnostics_at >= 250'000'000)) {
                vr::VREvent_t old{};
                while (client.overlay->PollNextOverlayEvent(face.spare, &old, sizeof(old))) {
                }
                face.loading = true;
                upload(face, diagnostic_texture(model, diagnostics), face.spare);
                diagnostics_at = now;
            }
            if (!face.shown)
                check(client.overlay->ShowOverlay(face.handle));
            face.shown = visible = true;
        }
    }
    ~Display() {
        for (const auto &face : faces)
            if (face.handle != vr::k_ulOverlayHandleInvalid) {
                client.overlay->HideOverlay(face.handle);
                client.overlay->DestroyOverlay(face.handle);
                if (face.spare != vr::k_ulOverlayHandleInvalid) {
                    client.overlay->HideOverlay(face.spare);
                    client.overlay->DestroyOverlay(face.spare);
                }
            }
    }
};
struct TemporaryDirectory {
    std::filesystem::path path;
    TemporaryDirectory() {
        char name[] = "/tmp/framephone-presence-XXXXXX";
        auto result = mkdtemp(name);
        if (!result)
            throw std::runtime_error("cannot create private presence bindings");
        path = result;
    }
    ~TemporaryDirectory() {
        std::error_code ignored;
        std::filesystem::remove_all(path, ignored);
    }
};
// Presence must be observable before a phone marker or screen renderer exists.
void presence(const std::filesystem::path &manifest) {
    Client client;
    client.open(vr::VRApplication_Background);
    vr::VRActionSetHandle_t set = vr::k_ulInvalidActionSetHandle;
    vr::VRActionHandle_t action = vr::k_ulInvalidActionHandle;
    std::unique_ptr<TemporaryDirectory> files;
    bool bound = false;
    try {
        if (!client.input)
            throw std::runtime_error("SteamVR input interface unavailable");
        vr::ETrackedPropertyError error{};
        char controller[128]{};
        client.system->GetStringTrackedDeviceProperty(vr::k_unTrackedDeviceIndex_Hmd,
                                                      vr::Prop_ControllerType_String, controller,
                                                      sizeof(controller), &error);
        // Some HMD drivers do not expose a controller type. It is not a condition
        // for using their system-level activity state.
        const std::string type =
            error == vr::TrackedProp_Success && controller[0] ? controller : "generic_hmd";
        auto actions = read(manifest), binding = read(manifest.parent_path() / "headset.json");
        actions["default_bindings"][0]["controller_type"] = type;
        binding["controller_type"] = type;
        files = std::make_unique<TemporaryDirectory>();
        const auto active_manifest = files->path / "actions.json";
        for (const auto &item : {std::make_pair(active_manifest, actions),
                                 std::make_pair(files->path / "headset.json", binding)}) {
            std::ofstream file(item.first);
            file << item.second.dump() << '\n';
            file.close();
            if (!file)
                throw std::runtime_error("cannot write proximity binding");
        }
        bound =
            client.input->SetActionManifestPath(active_manifest.c_str()) == vr::VRInputError_None &&
            client.input->GetActionSetHandle("/actions/presence", &set) == vr::VRInputError_None &&
            client.input->GetActionHandle("/actions/presence/in/worn", &action) ==
                vr::VRInputError_None;
    } catch (const std::exception &error) {
        std::cout << "Proximity binding unavailable: " << error.what()
                  << "; using SteamVR activity.\n";
    }
    HeadsetPresence policy;
    std::string previous_source;
    while (!stopped) {
        vr::VREvent_t event{};
        while (client.system->PollNextEvent(&event, sizeof(event)))
            if (event.eventType == vr::VREvent_Quit)
                stopped = 1;
        const bool connected =
            !stopped && client.system->IsTrackedDeviceConnected(vr::k_unTrackedDeviceIndex_Hmd);
        vr::InputDigitalActionData_t data{};
        vr::VRActiveActionSet_t active_set{};
        active_set.ulActionSet = set;
        std::optional<bool> proximity, active;
        if (connected && bound &&
            client.input->UpdateActionState(&active_set, sizeof(active_set), 1) ==
                vr::VRInputError_None &&
            client.input->GetDigitalActionData(action, &data, sizeof(data),
                                               vr::k_ulInvalidInputValueHandle) ==
                vr::VRInputError_None &&
            data.bActive)
            proximity = data.bState;
        if (connected) {
            const auto activity =
                client.system->GetTrackedDeviceActivityLevel(vr::k_unTrackedDeviceIndex_Hmd);
            switch (activity) {
            case vr::k_EDeviceActivityLevel_UserInteraction:
            case vr::k_EDeviceActivityLevel_UserInteraction_Timeout:
                active = true;
                break;
            case vr::k_EDeviceActivityLevel_Idle:
            case vr::k_EDeviceActivityLevel_Idle_Timeout:
            case vr::k_EDeviceActivityLevel_Standby:
                active = false;
                break;
            default:
                break;
            }
        }
        const auto now = now_ns();
        const auto state = policy.update(now, connected, proximity, active);
        const std::string source = state.proximity   ? "proximity"
                                   : state.available ? "steamvr_activity"
                                                     : "unavailable";
        if (source != previous_source) {
            std::cout << "Headset presence source: " << source << '\n';
            previous_source = source;
        }
        std::cout << Json{{"schema", "framephone-headset-presence-v1"},
                          {"available", state.available},
                          {"worn", state.worn},
                          {"source", source},
                          {"updated_host_monotonic_ns", now}}
                         .dump()
                  << '\n';
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
}
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
    const PhoneModel model{screen};
    const auto surfaces = model.surfaces();
    check(surfaces.size() < vr::k_unMaxOverlayCount - 1);
    const auto pixels = surface_texture(model, surfaces.front());
    check(pixels.rgba[3] == 255 && pixels.rgba[(256 * 256 + 128) * 4 + 3] == 0);
    std::cout << "VR screen pose validation, stale/lost rejection, physical dimensions and "
                 "phone shell passed "
                 "(no SteamVR required).\n";
}
} // namespace
int main(int argc, char **argv) {
    std::cout.setf(std::ios::unitbuf);
    try {
        if (argc == 3 && std::string(argv[1]) == "--presence") {
            const auto parent = getppid();
            prctl(PR_SET_PDEATHSIG, SIGTERM);
            if (getppid() != parent)
                return 1;
            std::signal(SIGTERM, stop);
            std::signal(SIGINT, stop);
            presence(argv[2]);
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--self-test") {
            self_test();
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout << "FramePhone tracked VR phone\n  --session DIRECTORY\n "
                         " --self-test\n  --presence ACTION_MANIFEST (wearer heartbeat)\n";
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
        PoseSmoothing smoothing;
        TrackingFade fade;
        std::string smoothing_key, gyro_key;
        bool gyro_epoch_verified = false;
        std::int64_t last_pose_time = 0;
        std::uint64_t last_state_write = 0;
        Client client;
        client.open();
        Display display(client, geometry);
        display.create();
        vr::ETrackedPropertyError property_error{};
        const auto frequency = client.system->GetFloatTrackedDeviceProperty(
            vr::k_unTrackedDeviceIndex_Hmd, vr::Prop_DisplayFrequency_Float, &property_error);
        const double render_hz = property_error == vr::TrackedProp_Success &&
                                         std::isfinite(frequency) && frequency >= 60 &&
                                         frequency <= 144
                                     ? frequency
                                     : 90;
        const auto period = std::chrono::duration_cast<std::chrono::steady_clock::duration>(
            std::chrono::duration<double>(1 / render_hz));
        auto next_render = std::chrono::steady_clock::now();
        std::deque<std::uint64_t> rendered;
        Metadata phone_metadata{session / "phone-pose.json"},
            optical_metadata{session / "vr-pose.json"};
        std::cout << (arcore ? "VR screen ready: ARCore handoff; briefly show the marker to both "
                               "front cameras.\n"
                             : "VR screen ready: fiducial-driven rectangle; headset alignment and "
                               "motion timing are provisional.\n");
        std::string previous_state;
        bool previous_tracking_visible = false;
        while (!stopped || display.visible) {
            vr::VREvent_t event{};
            while (client.system->PollNextEvent(&event, sizeof(event)))
                if (event.eventType == vr::VREvent_Quit)
                    stopped = 1;
                else if (event.eventType == vr::VREvent_StandingZeroPoseReset ||
                         event.eventType == vr::VREvent_SeatedZeroPoseReset ||
                         event.eventType == vr::VREvent_ChaperoneUniverseHasChanged) {
                    handoff.reset("headset tracking origin changed; show marker again");
                    fade.reset();
                }
            vr::TrackedDevicePose_t head{};
            client.system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding, 0, &head,
                                                           1);
            const auto now = now_ns();
            const bool head_valid = head.bPoseIsValid && head.bDeviceIsConnected;
            Matrix head_matrix = identity();
            if (head_valid) {
                auto &matrix = head_matrix;
                for (int r = 0; r < 3; ++r)
                    for (int c = 0; c < 4; ++c)
                        matrix[r * 4 + c] = head.mDeviceToAbsoluteTracking.m[r][c];
                handoff.head(now, matrix);
            }
            std::optional<Matrix> current;
            double prediction_ms = 0, pose_age_ms = 0, pose_hz = 0, source_hz = 0,
                   capture_delay_ms = 0, delivery_ms = 0;
            bool gyro_prediction = false, allow_fade_gyro = false;
            Json fade_gyro = Json::array();
            std::string state = "waiting for an accepted optical pose";
            try {
                if (arcore && !stopped && head_valid) {
                    const auto &phone = phone_metadata.get(), &optical = optical_metadata.get();
                    if (!phone.empty() && phone.at("session") != config.at("phone_session"))
                        throw std::runtime_error("phone session changed");
                    // Gyro can remain live while ARCore is paused. Only use it
                    // with the same verified phone/ARCore generation and clock.
                    // A new marker acquisition does not change IMU body axes.
                    if (phone.contains("poses") && !phone.at("poses").empty()) {
                        const auto &latest = phone.at("poses").back();
                        const auto key = phone.at("session").get<std::string>() + ":" +
                                         latest.at("generation").get<std::string>();
                        allow_fade_gyro = gyro_epoch_verified && key == gyro_key &&
                                          phone.value("clock_valid", false);
                        fade_gyro = phone.value("gyro", Json::array());
                        pose_hz = phone.value("pose_hz", 0.);
                        source_hz = phone.value("source_hz", pose_hz);
                    }
                    current = handoff.update(phone, optical, now);
                    if (current) {
                        const auto predicted = predict_pose(*current, phone, now);
                        const auto &latest = phone.at("poses").back();
                        const auto key = latest.at("generation").get<std::string>() + ":" +
                                         latest.at("acquisition").get<std::string>();
                        if (key != smoothing_key) {
                            smoothing.reset();
                            smoothing_key = key;
                        }
                        gyro_key = phone.at("session").get<std::string>() + ":" +
                                   latest.at("generation").get<std::string>();
                        gyro_epoch_verified = latest.contains("capture_t_ns");
                        current = smoothing.update(predicted.pose, now);
                        prediction_ms = predicted.milliseconds;
                        gyro_prediction = predicted.gyro;
                        last_pose_time = pose_time_ns(latest);
                        if (latest.contains("capture_t_ns"))
                            capture_delay_ms = (latest.at("t_ns").get<std::int64_t>() -
                                                latest.at("capture_t_ns").get<std::int64_t>()) /
                                               1e6;
                        delivery_ms = std::max(
                            0., (phone.at("received_host_monotonic_ns").get<std::int64_t>() -
                                 latest.at("host_t_ns").get<std::int64_t>()) /
                                    1e6);
                    }
                    state = handoff.state.at("reason").get<std::string>();
                } else if (!arcore && !stopped &&
                           std::filesystem::exists(session / "vr-pose.json")) {
                    const auto message = read(session / "vr-pose.json");
                    current = pose(message, now_ns());
                    if (current)
                        last_pose_time =
                            message.at("processed_host_monotonic_ns").get<std::int64_t>();
                    state = current ? "visible"
                            : message.value("status", "") == "measured"
                                ? "hidden: pose stale (over 250 ms) or clock invalid"
                                : "hidden: no accepted optical pose";
                }
            } catch (const std::exception &error) {
                state = std::string("hidden: ") + error.what();
                handoff.reset(state);
                allow_fade_gyro = false;
            }
            if (!head_valid) {
                current.reset();
                state = "hidden: headset tracking unavailable";
                handoff.reset(state);
                fade.reset(); // Never carry an old world pose through headset tracking loss.
            }
            if (!current)
                smoothing.reset();
            if (last_pose_time > 0)
                pose_age_ms = std::max(0., double(std::int64_t(now) - last_pose_time) / 1e6);
            const auto presentation = fade.update(current, now, fade_gyro, allow_fade_gyro);
            gyro_prediction = gyro_prediction || presentation.gyro;
            display.update(presentation, arcore, head_matrix,
                           {arcore, current.has_value(), gyro_prediction, pose_hz, pose_age_ms,
                            prediction_ms, presentation.opacity},
                           now);
            if (presentation.pose) {
                rendered.push_back(now);
                while (rendered.size() > 120 || now - rendered.front() > 1'000'000'000)
                    rendered.pop_front();
            } else
                rendered.clear();
            const bool tracking_visible = current.has_value() && display.visible;
            if (arcore && (now - last_state_write >= 100'000'000 || state != previous_state ||
                           tracking_visible != previous_tracking_visible)) {
                auto status = handoff.state;
                status["visible"] = tracking_visible;
                status["fading"] = !current && presentation.pose.has_value();
                status["opacity"] = presentation.opacity;
                status["updated_host_monotonic_ns"] = now;
                status["pose_hz"] = pose_hz;
                status["source_hz"] = source_hz;
                status["render_hz"] = rendered.size() > 1 ? (rendered.size() - 1) * 1e9 /
                                                                (rendered.back() - rendered.front())
                                                          : 0;
                status["pose_age_ms"] = pose_age_ms;
                status["prediction_ms"] = prediction_ms;
                status["gyro_prediction"] = gyro_prediction;
                status["camera_processing_ms"] = capture_delay_ms;
                status["delivery_ms"] = delivery_ms;
                const auto temporary = session / "arcore-state.json.tmp";
                std::ofstream file(temporary);
                file << status.dump() << '\n';
                file.close();
                if (!file)
                    throw std::runtime_error("cannot publish ARCore handoff state");
                std::filesystem::rename(temporary, session / "arcore-state.json");
                last_state_write = now;
            }
            previous_tracking_visible = tracking_visible;
            if (state != previous_state) {
                std::cout << "VR screen " << state << '\n';
                previous_state = state;
            }
            next_render += period;
            if (next_render < std::chrono::steady_clock::now())
                next_render = std::chrono::steady_clock::now();
            std::this_thread::sleep_until(next_render);
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "framephone-overlay: " << error.what() << '\n';
        return 1;
    }
}
