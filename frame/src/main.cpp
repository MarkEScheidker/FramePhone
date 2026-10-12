#include <openvr.h>

#include <array>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

namespace {

constexpr uint32_t kImageWidth = 480;
constexpr uint32_t kImageHeight = 1024;
constexpr uint32_t kBytesPerPixel = 4;
constexpr float kScreenWidthMeters = 0.076F;
constexpr float kPhoneAspect = 0.475F;
constexpr float kScreenMarginX = 24.0F / kImageWidth;
constexpr float kOverlayWidthMeters = kScreenWidthMeters / (1.0F - 2.0F * kScreenMarginX);
constexpr int kScreenLeft = 24;
constexpr int kScreenRight = static_cast<int>(kImageWidth) - 24;
constexpr int kScreenHeightPixels = static_cast<int>((kScreenRight - kScreenLeft) / kPhoneAspect);
constexpr int kScreenTop = (static_cast<int>(kImageHeight) - kScreenHeightPixels) / 2;
constexpr int kScreenBottom = kScreenTop + kScreenHeightPixels;

struct Color {
    uint8_t r;
    uint8_t g;
    uint8_t b;
    uint8_t a;
};

std::atomic_bool running{true};

void handle_signal(int) {
    running.store(false);
}

void pixel(std::vector<uint8_t> &image, int x, int y, Color color) {
    if (x < 0 || y < 0 || x >= static_cast<int>(kImageWidth) || y >= static_cast<int>(kImageHeight))
        return;
    const size_t offset =
        (static_cast<size_t>(y) * kImageWidth + static_cast<size_t>(x)) * kBytesPerPixel;
    image[offset] = color.r;
    image[offset + 1] = color.g;
    image[offset + 2] = color.b;
    image[offset + 3] = color.a;
}

void line(std::vector<uint8_t> &image, int x0, int y0, int x1, int y1, Color color,
          int thickness = 3) {
    const int dx = std::abs(x1 - x0);
    const int sx = x0 < x1 ? 1 : -1;
    const int dy = -std::abs(y1 - y0);
    const int sy = y0 < y1 ? 1 : -1;
    int error = dx + dy;
    while (true) {
        for (int oy = -thickness / 2; oy <= thickness / 2; ++oy)
            for (int ox = -thickness / 2; ox <= thickness / 2; ++ox)
                pixel(image, x0 + ox, y0 + oy, color);
        if (x0 == x1 && y0 == y1)
            break;
        const int twice_error = 2 * error;
        if (twice_error >= dy) {
            error += dy;
            x0 += sx;
        }
        if (twice_error <= dx) {
            error += dx;
            y0 += sy;
        }
    }
}

void rectangle(std::vector<uint8_t> &image, int left, int top, int right, int bottom, Color color,
               int thickness = 3) {
    line(image, left, top, right, top, color, thickness);
    line(image, right, top, right, bottom, color, thickness);
    line(image, right, bottom, left, bottom, color, thickness);
    line(image, left, bottom, left, top, color, thickness);
}

void tag_box(std::vector<uint8_t> &image, int center_x, int center_y, Color color) {
    constexpr int half = 42;
    rectangle(image, center_x - half, center_y - half, center_x + half, center_y + half, color, 6);
    // A center cross makes the expected tag center visible at headset distance.
    line(image, center_x - 11, center_y, center_x + 11, center_y, color, 4);
    line(image, center_x, center_y - 11, center_x, center_y + 11, color, 4);
}

std::vector<uint8_t> make_demo_image() {
    std::vector<uint8_t> image(static_cast<size_t>(kImageWidth) * kImageHeight * kBytesPerPixel, 0);
    const Color predicted_screen{40, 255, 120, 255};
    const Color expected_fiducial{255, 180, 20, 255};
    rectangle(image, kScreenLeft, kScreenTop, kScreenRight, kScreenBottom, predicted_screen, 5);

    // Illustrative six-marker layout: four corners and the two side centers.
    constexpr int margin = 82;
    tag_box(image, kScreenLeft + margin, kScreenTop + margin, expected_fiducial);
    tag_box(image, kScreenRight - margin, kScreenTop + margin, expected_fiducial);
    tag_box(image, kScreenRight - margin, kScreenBottom - margin, expected_fiducial);
    tag_box(image, kScreenLeft + margin, kScreenBottom - margin, expected_fiducial);
    tag_box(image, kScreenLeft + margin, (kScreenTop + kScreenBottom) / 2, expected_fiducial);
    tag_box(image, kScreenRight - margin, (kScreenTop + kScreenBottom) / 2, expected_fiducial);
    return image;
}

void check_overlay(vr::IVROverlay *overlay, vr::EVROverlayError result, const char *operation) {
    if (result == vr::VROverlayError_None)
        return;
    std::cerr << operation << " failed: " << overlay->GetOverlayErrorNameFromEnum(result) << '\n';
    std::exit(EXIT_FAILURE);
}

class OpenVrOverlay {
  public:
    OpenVrOverlay() {
        vr::EVRInitError init_error = vr::VRInitError_None;
        vr::VR_Init(&init_error, vr::VRApplication_Overlay);
        if (init_error != vr::VRInitError_None) {
            std::cerr << "OpenVR initialization failed: "
                      << vr::VR_GetVRInitErrorAsEnglishDescription(init_error) << '\n';
            std::exit(EXIT_FAILURE);
        }

        overlay_ = vr::VROverlay();
        if (overlay_ == nullptr) {
            std::cerr << "SteamVR did not provide the OpenVR overlay interface\n";
            vr::VR_Shutdown();
            std::exit(EXIT_FAILURE);
        }

        const auto created =
            overlay_->CreateOverlay("framephone.debug", "FramePhone Debug", &handle_);
        check_overlay(overlay_, created, "CreateOverlay");
        overlay_created_ = true;

        const auto width = overlay_->SetOverlayWidthInMeters(handle_, kOverlayWidthMeters);
        check_overlay(overlay_, width, "SetOverlayWidthInMeters");

        vr::HmdMatrix34_t pose{};
        pose.m[0][0] = 1.0F;
        pose.m[1][1] = 1.0F;
        pose.m[2][2] = 1.0F;
        pose.m[1][3] = -0.08F;
        pose.m[2][3] = -0.65F;
        check_overlay(overlay_,
                      overlay_->SetOverlayTransformTrackedDeviceRelative(
                          handle_, vr::k_unTrackedDeviceIndex_Hmd, &pose),
                      "SetOverlayTransformTrackedDeviceRelative");

        image_ = make_demo_image();
        check_overlay(overlay_,
                      overlay_->SetOverlayRaw(handle_, image_.data(), kImageWidth, kImageHeight,
                                              kBytesPerPixel),
                      "SetOverlayRaw");
        check_overlay(overlay_, overlay_->ShowOverlay(handle_), "ShowOverlay");
    }

    ~OpenVrOverlay() {
        if (overlay_created_) {
            overlay_->HideOverlay(handle_);
            overlay_->DestroyOverlay(handle_);
        }
        vr::VR_Shutdown();
    }

    void wait() const {
        vr::VREvent_t event{};
        while (running.load()) {
            while (vr::VRSystem()->PollNextEvent(&event, sizeof(event))) {
                if (event.eventType == vr::VREvent_Quit)
                    running.store(false);
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
    }

  private:
    vr::IVROverlay *overlay_ = nullptr;
    vr::VROverlayHandle_t handle_ = vr::k_ulOverlayHandleInvalid;
    bool overlay_created_ = false;
    std::vector<uint8_t> image_;
};

} // namespace

int main(int argc, char **argv) {
    if (argc != 2 || std::string(argv[1]) != "--demo") {
        std::cerr << "Usage: framephone-openvr-demo --demo\n"
                  << "This renderer-only demo shows the expected screen outline and six fiducial "
                     "positions.\n";
        return EXIT_FAILURE;
    }

    std::signal(SIGINT, handle_signal);
    std::signal(SIGTERM, handle_signal);
    std::cout << "Showing renderer demo only: no camera frames or tracked pose are being used. "
                 "Press Ctrl+C to close the overlay.\n";
    OpenVrOverlay overlay;
    overlay.wait();
    return EXIT_SUCCESS;
}
