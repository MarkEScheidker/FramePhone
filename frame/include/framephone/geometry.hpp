#pragma once

#include "framephone/camera_source.hpp"
#include <array>
#include <map>

namespace framephone {
struct ImagePoint {
    double x{}, y{};
};
struct Point3 {
    double x{}, y{}, z{};
};
struct CameraCalibration {
    std::string id, camera_id, model, status;
    std::uint32_t width{}, height{};
    double fx{}, fy{}, cx{}, cy{};
    std::vector<double> distortion;
};
} // namespace framephone
