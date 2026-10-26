#pragma once
#include <cstdint>
#include <optional>

namespace framephone::surface {
struct WearerState {
    bool available = false;
    bool worn = false;
    bool proximity = false;
};
/** Prefer explicit proximity. When that input is unavailable, SteamVR's HMD
 * activity state provides the same active/idle distinction used by Frametop.
 * This fallback is an activity indication, not a raw wearer measurement. */
class HeadsetPresence {
  public:
    WearerState update(std::uint64_t now, bool connected, std::optional<bool> proximity,
                       std::optional<bool> active) {
        if (!connected || (!proximity && !active)) {
            pending_valid_ = false;
            confirmed_ = false;
            return {};
        }
        if (proximity) {
            pending_valid_ = false;
            confirmed_ = *proximity;
            return {true, confirmed_, true};
        }
        if (!pending_valid_ || pending_active_ != *active || now < since_) {
            pending_active_ = *active;
            pending_valid_ = true;
            since_ = now;
        }
        // Ignore SteamVR's initial idle reading and brief activity transitions.
        if (now - since_ >= 500'000'000)
            confirmed_ = *active;
        return {true, confirmed_, false};
    }

  private:
    bool pending_valid_ = false;
    bool pending_active_ = false;
    std::uint64_t since_ = 0;
    bool confirmed_ = false;
};
} // namespace framephone::surface
