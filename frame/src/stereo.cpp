#include "framephone/stereo.hpp"
#include "calibration_json.hpp"

namespace framephone {
namespace {
using calibration_json::require;
void validate_frame(const CameraFrame &f, const RigCamera &c) {
    f.validate();
    const auto &k = c.calibration;
    require(f.camera_id == k.camera_id && f.calibration_id == k.id && f.width == k.width &&
                f.height == k.height,
            "stereo frame camera/calibration identity or dimensions mismatch");
}
} // namespace
std::uint64_t StereoPair::skew_ns() const {
    const auto a = frames[0].capture_time_ns, b = frames[1].capture_time_ns;
    return a > b ? a - b : b - a;
}
StereoFramePairer::StereoFramePairer(StereoRig rig, std::uint64_t max_skew_ns)
    : rig_(std::move(rig)), max_skew_(max_skew_ns) {
    validate_stereo_rig(rig_);
    require(max_skew_ <= 3'000'000, "capture skew limit must be <=3 ms");
}
void StereoFramePairer::push(CameraFrame f) {
    std::size_t index = 2;
    for (std::size_t i = 0; i < 2; ++i)
        if (f.camera_id == rig_.cameras[i].calibration.camera_id)
            index = i;
    require(index < 2, "unexpected stereo camera");
    validate_frame(f, rig_.cameras[index]);
    require(clock_.empty() || clock_ == f.clock_domain,
            "stereo cameras require one verified shared capture clock");
    require(f.capture_time_ns > last_[index], "stereo capture timestamp did not increase");
    clock_ = f.clock_domain;
    last_[index] = f.capture_time_ns;
    auto &q = pending_[index];
    q.push_back(std::move(f));
    if (q.size() > 4) {
        q.pop_front();
        ++dropped_;
    }
}
std::optional<StereoPair> StereoFramePairer::poll() {
    auto &a = pending_[0];
    auto &b = pending_[1];
    while (!a.empty() && !b.empty()) {
        const auto ta = a.front().capture_time_ns, tb = b.front().capture_time_ns;
        const auto skew = ta > tb ? ta - tb : tb - ta;
        if (skew <= max_skew_) {
            StereoPair p{{std::move(a.front()), std::move(b.front())}};
            a.pop_front();
            b.pop_front();
            return p;
        }
        (ta < tb ? a : b).pop_front();
        ++dropped_;
    }
    return {};
}
} // namespace framephone
