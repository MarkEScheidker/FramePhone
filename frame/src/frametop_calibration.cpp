// Adapted from Frametop hands/track/calib.cpp, commit
// 24a86dc02669caaef8386ea5bfeb08fcb2819944. Copyright (c) 2026 DeeJanuz.
// MIT license: ../third_party/frametop/LICENSE. See that directory's README.
#include "calibration_json.hpp"
#include "framephone/stereo.hpp"
#include <algorithm>
#include <numbers>
#include <opencv2/core.hpp>

namespace framephone {
namespace {
using namespace calibration_json;
cv::Vec3d vec(Point3 p) {
    return {p.x, p.y, p.z};
}
Point3 point(cv::Vec3d p) {
    return {p[0], p[1], p[2]};
}
cv::Vec3d origin(const RigCamera &c) {
    return cv::Vec3d(c.origin_m.data());
}
cv::Matx33d camera_rotation(const RigCamera &c) {
    return cv::Matx33d(c.rotation.data());
}
cv::Vec3d vector3(const Json &j) {
    array(j, 3);
    return {number(j[0]), number(j[1]), number(j[2])};
}
cv::Matx44d pose(const Json &j, double scale) {
    // Upstream: axes are columns, y = z cross x. Never normalize corrupt data.
    const auto x = vector3(j.at("plus_x")), z = vector3(j.at("plus_z"));
    require(std::abs(cv::norm(x) - 1) < 1e-4 && std::abs(cv::norm(z) - 1) < 1e-4 &&
                std::abs(x.dot(z)) < 1e-4,
            "factory pose axes are not orthonormal");
    const auto y = z.cross(x), t = vector3(j.at("position")) * scale;
    return {x[0], y[0], z[0], t[0], x[1], y[1], z[1], t[1], x[2], y[2], z[2], t[2], 0, 0, 0, 1};
}
cv::Matx44d invert_rigid(const cv::Matx44d &a) {
    auto b = cv::Matx44d::eye();
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            b(i, j) = a(j, i);
    for (int i = 0; i < 3; ++i)
        b(i, 3) = -(b(i, 0) * a(0, 3) + b(i, 1) * a(1, 3) + b(i, 2) * a(2, 3));
    return b;
}
double theta_d(const CameraCalibration &c, double t) {
    const double t2 = t * t;
    const auto &k = c.distortion;
    return t * (1 + t2 * (k[0] + t2 * (k[1] + t2 * (k[2] + t2 * k[3]))));
}
double derivative(const CameraCalibration &c, double t) {
    const double t2 = t * t;
    const auto &k = c.distortion;
    return 1 + t2 * (3 * k[0] + t2 * (5 * k[1] + t2 * (7 * k[2] + t2 * 9 * k[3])));
}
void validate_camera(const RigCamera &c) {
    const auto &k = c.calibration;
    require(!k.id.empty() && !k.camera_id.empty() && k.model == "fisheye_kb4" &&
                k.distortion.size() == 4,
            "stereo requires identified KB4 cameras");
    require(k.width > 0 && k.width <= 16384 && k.height > 0 && k.height <= 16384 &&
                std::isfinite(k.fx) && std::isfinite(k.fy) && k.fx > 0 && k.fy > 0 && k.cx >= 0 &&
                k.cx < k.width && k.cy >= 0 && k.cy < k.height,
            "invalid factory intrinsics");
    for (double d : k.distortion)
        require(std::isfinite(d), "nonfinite factory distortion");
    for (double d : c.rotation)
        require(std::isfinite(d), "nonfinite factory rotation");
    for (double d : c.origin_m)
        require(std::isfinite(d), "nonfinite factory position");
    const auto r = camera_rotation(c);
    require(cv::norm(r.t() * r - cv::Matx33d::eye()) < 1e-3 &&
                std::abs(cv::determinant(r) - 1) < 1e-3,
            "invalid camera-to-head rotation");
    // This tracker uses the forward optical hemisphere. Check invertibility
    // there and reject pixels outside it rather than silently clamping rays.
    for (int i = 0; i <= 256; ++i)
        require(derivative(k, double(i) / 256 * std::numbers::pi / 2) > 1e-6,
                "nonmonotonic KB4 forward model");
}
} // namespace

std::map<std::string, RigCamera> load_frametop_calibration(const std::filesystem::path &root,
                                                           const std::string &id) {
    require(!id.empty() && id.size() <= 256, "provide a factory calibration revision ID");
    const auto rig = read_json(root / "persist/xrservice.json");
    const auto dev = read_json(root / "persist/device_config.json");
    const auto head_from_cam0 =
        invert_rigid(pose(dev.at("head"), 1)) * pose(dev.at("cv").at("cad_from_cal"), 1);
    require(rig.at("cameras").is_array() && rig.at("cameras").size() <= 32,
            "invalid factory camera array");
    std::map<std::string, RigCamera> out;
    std::set<std::string> names;
    for (const auto &camera : rig.at("cameras")) {
        const auto name = string(camera.at("sourceCamera"));
        require(names.insert(name).second, "duplicate factory camera name");
        require(camera.at("intrinsics").is_array(), "invalid factory intrinsics array");
        const Json *kb = nullptr;
        for (const auto &in : camera.at("intrinsics"))
            if (in.at("cameraModel") == "kb") {
                require(!kb, "multiple KB models for factory camera");
                kb = &in;
            }
        if (!kb)
            continue; // e.g. a color camera with another model is not a mono candidate.
        RigCamera c;
        auto &k = c.calibration;
        k.id = id;
        k.camera_id = name;
        c.factory_camera_id = name;
        k.model = "fisheye_kb4";
        k.status = "factory_imported";
        k.width = static_cast<std::uint32_t>(integer(camera.at("width"), 1, 16384));
        k.height = static_cast<std::uint32_t>(integer(camera.at("height"), 1, 16384));
        k.fx = number(kb->at("fx"));
        k.fy = number(kb->at("fy"));
        k.cx = number(kb->at("cx"));
        k.cy = number(kb->at("cy"));
        for (const auto *key : {"k1", "k2", "k3", "k4"})
            k.distortion.push_back(number(kb->at(key)));
        // Factory extrinsics are millimeters; CAD/head positions are meters.
        const auto hc = head_from_cam0 * pose(camera.at("extrinsics"), 1e-3);
        for (int i = 0; i < 3; ++i) {
            c.origin_m[std::size_t(i)] = hc(i, 3);
            for (int j = 0; j < 3; ++j)
                c.rotation[std::size_t(3 * i + j)] = hc(i, j);
        }
        validate_camera(c);
        out.emplace(name, std::move(c));
    }
    require(!out.empty(), "no factory KB4 cameras found");
    return out;
}

Point3 RigCamera::ray(ImagePoint uv) const {
    const auto &c = calibration;
    const double mx = (uv.x - c.cx) / c.fx, my = (uv.y - c.cy) / c.fy, td = std::hypot(mx, my);
    if (!std::isfinite(td))
        throw std::invalid_argument("nonfinite image point");
    double t = std::min(td, std::numbers::pi / 2);
    for (int i = 0; i < 12; ++i) {
        const double df = derivative(c, t);
        if (!std::isfinite(df) || df <= 1e-9)
            throw std::invalid_argument("KB4 inverse failed");
        t = std::clamp(t - (theta_d(c, t) - td) / df, 0.0, std::numbers::pi / 2);
    }
    if (std::abs(theta_d(c, t) - td) > 1e-9 || t >= std::numbers::pi / 2)
        throw std::invalid_argument("pixel outside invertible forward KB4 model");
    const double s = td > 1e-12 ? std::sin(t) / td : 1;
    return point(camera_rotation(*this) * cv::Vec3d(mx * s, my * s, std::cos(t)));
}
ImagePoint RigCamera::project(Point3 head, double *depth) const {
    const auto c = camera_rotation(*this).t() * (vec(head) - origin(*this));
    if (depth)
        *depth = c[2];
    const double r = std::hypot(c[0], c[1]);
    const double s = r > 1e-12 ? theta_d(calibration, std::atan2(r, c[2])) / r : 0;
    return {calibration.fx * c[0] * s + calibration.cx, calibration.fy * c[1] * s + calibration.cy};
}
void validate_stereo_rig(const StereoRig &rig) {
    for (const auto &c : rig.cameras)
        validate_camera(c);
    require(rig.cameras[0].calibration.camera_id != rig.cameras[1].calibration.camera_id,
            "stereo cameras must differ");
    const double baseline = cv::norm(origin(rig.cameras[0]) - origin(rig.cameras[1]));
    require(baseline > 0.001 && baseline < 0.5, "implausible stereo baseline in meters");
}
std::optional<TriangulatedPoint> triangulate_stereo(const StereoRig &rig,
                                                    const std::array<ImagePoint, 2> &pixels) {
    std::array<cv::Vec3d, 2> dirs, origins;
    try {
        for (std::size_t v = 0; v < 2; ++v) {
            dirs[v] = vec(rig.cameras[v].ray(pixels[v]));
            origins[v] = origin(rig.cameras[v]);
        }
    } catch (const std::invalid_argument &) {
        return {};
    }
    const double angle = std::acos(std::clamp(dirs[0].dot(dirs[1]), -1.0, 1.0));
    if (angle < 0.01 || angle > std::numbers::pi - 0.01)
        return {};
    // Frametop's sum w*(I-dd^T) ray intersection, equal weights here: tag
    // decision margin is not the neural landmark presence probability.
    cv::Matx33d a = cv::Matx33d::zeros();
    cv::Vec3d b{};
    for (std::size_t v = 0; v < 2; ++v) {
        const auto p = cv::Matx33d::eye() - dirs[v] * dirs[v].t();
        a += p;
        b += p * origins[v];
    }
    cv::Vec3d singular;
    cv::SVD::compute(a, singular);
    if (singular[2] < singular[0] * 1e-5)
        return {};
    cv::Vec3d p;
    if (!cv::solve(a, b, p, cv::DECOMP_SVD) || !cv::checkRange(p))
        return {};
    double square{};
    for (std::size_t v = 0; v < 2; ++v) {
        const auto off = p - origins[v];
        const double distance = off.dot(dirs[v]);
        if (distance <= 0.001)
            return {};
        const auto perp = off - dirs[v] * distance;
        square += perp.dot(perp);
    }
    const double rms = std::sqrt(square / 2);
    if (rms > 0.01)
        return {};
    return TriangulatedPoint{point(p), rms, angle};
}
} // namespace framephone
