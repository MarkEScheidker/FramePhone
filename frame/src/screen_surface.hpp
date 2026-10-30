#pragma once
#include "screen_frames.hpp"
#include "tracking_fade.hpp"
#include <openvr.h>

namespace framephone::surface {
/** A permanent black fallback and two asynchronous upload buffers. The old
 * image stays visible until ImageLoaded; stale sessions can be blacked instantly. */
class ScreenSurface {
  public:
    ScreenSurface(vr::IVROverlay *api, Geometry geometry, const std::filesystem::path &metadata)
        : api_(api), geometry_(geometry), frames_(metadata) {}
    ~ScreenSurface() {
        for (auto handle : handles_)
            if (handle != vr::k_ulOverlayHandleInvalid) {
                api_->HideOverlay(handle);
                api_->DestroyOverlay(handle);
            }
    }
    std::string error;
    std::uint64_t uploads = 0;
    void create() {
        for (std::size_t i = 0; i < handles_.size(); ++i) {
            const auto key =
                "framephone.screen." + std::to_string(getpid()) + "." + std::to_string(i);
            check(api_->CreateOverlay(key.c_str(), "FramePhone screen", &handles_[i]));
            check(api_->SetOverlayFlag(handles_[i], vr::VROverlayFlags_VisibleInDashboard, true));
            check(api_->SetOverlayWidthInMeters(handles_[i], float(geometry_.width)));
            check(api_->SetOverlaySortOrder(handles_[i], 1));
        }
        Image black(1, 1, 0);
        check(upload(handles_[0], black));
    }
    void update(const PhonePresentation &presentation, bool world, const Matrix &head,
                std::uint64_t now) {
        const Vertex eye = world ? Vertex{head[3], head[7], head[11]} : Vertex{0, 0, 0};
        const bool show =
            presentation.pose && presentation.opacity > 0 && facing(*presentation.pose, eye);
        std::optional<Image> next;
        try {
            next = frames_.poll(now, show && !pending_ && !ready_);
        } catch (const std::exception &) {
            error = "Screen publication unavailable";
        }
        const bool valid = frames_.active(now);
        if (!valid || active_epoch_ != frames_.epoch)
            active_ = 0;
        for (int slot = 1; slot <= 2; ++slot) {
            vr::VREvent_t event{};
            while (api_->PollNextOverlayEvent(handles_[slot], &event, sizeof(event))) {
                if (pending_ == slot && event.eventType == vr::VREvent_ImageLoaded) {
                    ready_ = slot;
                    pending_ = 0;
                } else if (pending_ == slot && event.eventType == vr::VREvent_ImageFailed) {
                    pending_ = 0;
                    error = "Screen texture upload failed";
                }
            }
        }
        if (ready_ && (!valid || pending_epoch_ != frames_.epoch))
            ready_ = 0;
        if (ready_ && presentation.opacity == 1) {
            active_ = ready_;
            ready_ = 0;
            active_epoch_ = frames_.epoch;
            ++uploads;
            error.clear();
        }
        if (show && next && !pending_ && !ready_) {
            const int slot = active_ == 1 ? 2 : 1;
            vr::VREvent_t old{};
            while (api_->PollNextOverlayEvent(handles_[slot], &old, sizeof(old))) {
            }
            const auto result = upload(handles_[slot], *next);
            if (result == vr::VROverlayError_None) {
                pending_ = slot;
                pending_epoch_ = frames_.epoch;
            } else
                error = "Screen upload rejected: " + std::to_string(int(result));
        }
        if (!show) {
            hide();
            return;
        }
        vr::HmdMatrix34_t transform{};
        for (int r = 0; r < 3; ++r)
            for (int c = 0; c < 4; ++c)
                transform.m[r][c] = float((*presentation.pose)[r * 4 + c]);
        const auto selected = handles_[active_];
        if (world)
            check(api_->SetOverlayTransformAbsolute(selected, vr::TrackingUniverseStanding,
                                                    &transform));
        else
            check(api_->SetOverlayTransformTrackedDeviceRelative(
                selected, vr::k_unTrackedDeviceIndex_Hmd, &transform));
        check(api_->SetOverlayAlpha(selected, float(presentation.opacity)));
        if (shown_ != selected) {
            check(api_->ShowOverlay(selected));
            if (shown_ != vr::k_ulOverlayHandleInvalid)
                check(api_->HideOverlay(shown_));
            shown_ = selected;
        }
    }

  private:
    vr::EVROverlayError upload(vr::VROverlayHandle_t handle, const Image &image) {
        auto result = api_->SetOverlayTexelAspect(
            handle, float(geometry_.width / geometry_.height * image.height / image.width));
        if (result != vr::VROverlayError_None)
            return result;
        return api_->SetOverlayRaw(handle, const_cast<std::uint8_t *>(image.rgba.data()),
                                   image.width, image.height, 4);
    }
    void check(vr::EVROverlayError result) {
        if (result != vr::VROverlayError_None)
            throw std::runtime_error("VR screen: " +
                                     std::string(api_->GetOverlayErrorNameFromEnum(result)));
    }
    void hide() {
        if (shown_ != vr::k_ulOverlayHandleInvalid) {
            check(api_->HideOverlay(shown_));
            shown_ = vr::k_ulOverlayHandleInvalid;
        }
    }
    vr::IVROverlay *api_;
    Geometry geometry_;
    ScreenFrames frames_;
    std::array<vr::VROverlayHandle_t, 3> handles_{
        vr::k_ulOverlayHandleInvalid, vr::k_ulOverlayHandleInvalid, vr::k_ulOverlayHandleInvalid};
    vr::VROverlayHandle_t shown_ = vr::k_ulOverlayHandleInvalid;
    int active_ = 0, pending_ = 0, ready_ = 0;
    std::uint64_t active_epoch_ = 0, pending_epoch_ = 0;
};
} // namespace framephone::surface
