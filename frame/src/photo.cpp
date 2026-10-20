#include "framephone/photo.hpp"
#include <algorithm>
#include <cmath>
#include <map>
#include <numeric>
#include <opencv2/calib3d.hpp>
#include <opencv2/features2d.hpp>
#include <opencv2/imgproc.hpp>
#include <random>
#include <set>

namespace framephone {
namespace {
cv::Vec3d vec(Point3 p) {
    return {p.x, p.y, p.z};
}
Point3 point(cv::Vec3d p) {
    return {p[0], p[1], p[2]};
}
void require(bool ok, const char *why) {
    if (!ok)
        throw std::invalid_argument(why);
}
// RootSIFT: L1 normalize and take the element-wise square root before L2 matching.
// Arandjelovic & Zisserman, CVPR 2012; no new model or runtime dependency.
void root_sift(cv::Mat &descriptors) {
    for (int row = 0; row < descriptors.rows; ++row) {
        auto *values = descriptors.ptr<float>(row);
        double sum = 0;
        for (int col = 0; col < descriptors.cols; ++col)
            sum += values[col];
        for (int col = 0; col < descriptors.cols; ++col)
            values[col] = float(std::sqrt(values[col] / std::max(sum, 1e-12)));
    }
}
void validate(const StereoRig &rig, const StereoPair &pair) {
    require(pair.skew_ns() <= 3'000'000 &&
                pair.frames[0].clock_domain == pair.frames[1].clock_domain,
            "photo stereo clock mismatch or excessive skew");
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &f = pair.frames[v];
        const auto &k = rig.cameras[v].calibration;
        f.validate();
        require(f.camera_id == k.camera_id && f.calibration_id == k.id && f.width == k.width &&
                    f.height == k.height,
                "photo frame/calibration identity or dimensions mismatch");
    }
}
struct Fit {
    cv::Matx33d r;
    cv::Vec3d t;
    double scale{};
};
cv::Vec3d local(const PhotoMatch &m) {
    return {m.reference.x, m.reference.y, 0};
}
std::optional<Fit> fit(const std::vector<PhotoMatch> &m, const std::vector<cv::Vec3d> &p,
                       const std::vector<std::size_t> &ids) {
    cv::Vec3d a{}, b{};
    for (auto i : ids) {
        a += local(m[i]);
        b += p[i];
    }
    a /= double(ids.size());
    b /= double(ids.size());
    cv::Matx33d covariance = cv::Matx33d::zeros();
    double variance = 0;
    for (auto i : ids) {
        auto x = local(m[i]) - a;
        covariance += x * (p[i] - b).t();
        variance += x.dot(x);
    }
    cv::Mat s, u, vt;
    cv::SVD::compute(covariance, s, u, vt);
    if (variance < 1e-8 || s.at<double>(1) < 1e-8 || s.at<double>(1) < s.at<double>(0) * .005)
        return {};
    cv::Mat d = cv::Mat::eye(3, 3, CV_64F);
    d.at<double>(2, 2) = cv::determinant(vt.t() * u.t()) < 0 ? -1 : 1;
    cv::Mat rotation = vt.t() * d * u.t();
    Fit out{cv::Matx33d(rotation.ptr<double>()),
            {},
            (s.at<double>(0) + s.at<double>(1) + d.at<double>(2, 2) * s.at<double>(2)) / variance};
    out.t = b - out.r * a * out.scale;
    return out;
}
bool plausible(const Fit &f, const StereoRig &rig, double aspect) {
    if (!std::isfinite(f.scale) || f.scale < .015 || f.scale > .45 || f.scale * aspect > .8 ||
        cv::norm(f.t) > 3 || cv::norm(f.t) < .08)
        return false;
    const auto normal = f.r * cv::Vec3d(0, 0, 1);
    for (const auto &c : rig.cameras)
        if (normal.dot(cv::Vec3d(c.origin_m.data()) - f.t) <= 0)
            return false;
    return true;
}
double error(const Fit &f, const StereoRig &rig, const PhotoMatch &m) {
    const auto p = point(f.r * local(m) * f.scale + f.t);
    double worst = 0;
    for (std::size_t v = 0; v < 2; ++v) {
        double depth;
        auto uv = rig.cameras[v].project(p, &depth);
        if (depth <= .01)
            return 1e9;
        worst = std::max(worst, std::hypot(uv.x - m.pixels[v].x, uv.y - m.pixels[v].y));
    }
    return worst;
}
double coverage(const std::vector<PhotoMatch> &matches, double aspect) {
    std::vector<cv::Point2f> points, hull;
    for (const auto &m : matches)
        points.emplace_back(float(m.reference.x), float(m.reference.y));
    if (points.size() < 3)
        return 0;
    cv::convexHull(points, hull);
    return std::abs(cv::contourArea(hull)) / aspect;
}
class Residual final : public cv::LMSolver::Callback {
  public:
    Residual(const StereoRig &r, const std::vector<PhotoMatch> &m) : rig(r), matches(m) {}
    bool compute(cv::InputArray input, cv::OutputArray error,
                 cv::OutputArray jacobian) const override {
        auto p = input.getMat();
        cv::Mat e;
        if (!evaluate(p, e))
            return false;
        e.copyTo(error);
        if (jacobian.needed()) {
            jacobian.create(e.rows, 7, CV_64F);
            auto j = jacobian.getMat();
            for (int k = 0; k < 7; ++k) {
                double step = k < 3 || k == 6 ? 1e-6 : 1e-7;
                auto plus = p.clone(), minus = p.clone();
                plus.at<double>(k) += step;
                minus.at<double>(k) -= step;
                cv::Mat ep, em;
                if (!evaluate(plus, ep) || !evaluate(minus, em))
                    return false;
                cv::Mat difference = (ep - em) / (2 * step);
                difference.copyTo(j.col(k));
            }
        }
        return true;
    }
    bool evaluate(const cv::Mat &p, cv::Mat &e) const {
        cv::Matx33d r;
        cv::Rodrigues(cv::Vec3d(p.at<double>(0), p.at<double>(1), p.at<double>(2)), r);
        cv::Vec3d t(p.at<double>(3), p.at<double>(4), p.at<double>(5));
        double scale = std::exp(p.at<double>(6));
        if (!std::isfinite(scale) || scale < .001 || scale > 2)
            return false;
        e.create(int(matches.size() * 4), 1, CV_64F);
        int row = 0;
        for (const auto &m : matches)
            for (std::size_t v = 0; v < 2; ++v) {
                double depth;
                auto uv = rig.cameras[v].project(point(r * local(m) * scale + t), &depth);
                if (depth <= .01)
                    return false;
                e.at<double>(row++) = uv.x - m.pixels[v].x;
                e.at<double>(row++) = uv.y - m.pixels[v].y;
            }
        return cv::checkRange(e);
    }

  private:
    const StereoRig &rig;
    const std::vector<PhotoMatch> &matches;
};
bool refine(Fit &f, const StereoRig &rig, const std::vector<PhotoMatch> &m) {
    cv::Vec3d rv;
    cv::Rodrigues(f.r, rv);
    cv::Mat p =
        (cv::Mat_<double>(7, 1) << rv[0], rv[1], rv[2], f.t[0], f.t[1], f.t[2], std::log(f.scale));
    auto callback = cv::makePtr<Residual>(rig, m);
    auto count = cv::LMSolver::create(callback, 50, 1e-7)->run(p);
    if (count < 0 || count >= 50 || !cv::checkRange(p))
        return false;
    cv::Rodrigues(cv::Vec3d(p.at<double>(0), p.at<double>(1), p.at<double>(2)), f.r);
    f.t = {p.at<double>(3), p.at<double>(4), p.at<double>(5)};
    f.scale = std::exp(p.at<double>(6));
    return true;
}
} // namespace

PhotoPose estimate_photo_pose(const StereoRig &rig, const StereoPair &pair,
                              const std::vector<PhotoMatch> &input, double aspect) {
    validate_stereo_rig(rig);
    validate(rig, pair);
    require(std::isfinite(aspect) && aspect >= .2 && aspect <= 5 && input.size() <= 3000,
            "invalid photo aspect or match count");
    PhotoPose out;
    out.stereo_candidates = input.size();
    std::vector<PhotoMatch> matches;
    std::vector<cv::Vec3d> points;
    for (const auto &m : input) {
        bool valid = std::isfinite(m.reference.x) && std::isfinite(m.reference.y) &&
                     std::abs(m.reference.x) <= .501 &&
                     std::abs(m.reference.y) <= aspect / 2 + .001;
        for (std::size_t v = 0; v < 2; ++v) {
            auto p = m.pixels[v];
            const auto &k = rig.cameras[v].calibration;
            valid &= std::isfinite(p.x) && std::isfinite(p.y) && p.x >= 0 && p.y >= 0 &&
                     p.x < k.width && p.y < k.height;
        }
        if (!valid)
            continue;
        auto p = triangulate_stereo(rig, m.pixels);
        if (p) {
            matches.push_back(m);
            points.push_back(vec(p->point));
        }
    }
    out.triangulated = matches.size();
    if (matches.size() < 12) {
        if (input.size() >= 12)
            out.reason = "stereo_triangulation_rejected";
        return out;
    }
    std::vector<std::size_t> all(matches.size());
    std::iota(all.begin(), all.end(), 0);
    std::vector<PhotoMatch> best;
    Fit winner{};
    double best_error = 1e30;
    std::mt19937 rng(0x50484f54);
    for (int trial = 0; trial < 161; ++trial) {
        std::vector<std::size_t> ids = all;
        if (trial) {
            ids.clear();
            while (ids.size() < 3) {
                auto id = std::size_t(rng()) % matches.size();
                if (std::find(ids.begin(), ids.end(), id) == ids.end())
                    ids.push_back(id);
            }
        }
        auto f = fit(matches, points, ids);
        if (!f || !plausible(*f, rig, aspect))
            continue;
        std::vector<PhotoMatch> accepted;
        double sum = 0;
        for (const auto &m : matches) {
            auto e = error(*f, rig, m);
            if (e <= 3) {
                accepted.push_back(m);
                sum += e;
            }
        }
        if (accepted.size() > best.size() || (accepted.size() == best.size() && sum < best_error)) {
            best = std::move(accepted);
            winner = *f;
            best_error = sum;
        }
    }
    out.reason = "stereo_pose_fit_failed";
    out.pose_inliers = best.size();
    if (best.size() < 12)
        return out;
    for (int iteration = 0; iteration < 2; ++iteration) {
        if (!refine(winner, rig, best) || !plausible(winner, rig, aspect))
            return out;
        best.erase(std::remove_if(best.begin(), best.end(),
                                  [&](const auto &m) { return error(winner, rig, m) > 2.5; }),
                   best.end());
        out.pose_inliers = best.size();
        if (best.size() < 12)
            return out;
    }
    out.coverage = coverage(best, aspect);
    out.reason = "insufficient_spatial_coverage";
    if (out.coverage < .12)
        return out;
    double sum = 0;
    out.pose.max_error_px = 0;
    for (const auto &m : best)
        for (std::size_t v = 0; v < 2; ++v) {
            auto uv = rig.cameras[v].project(point(winner.r * local(m) * winner.scale + winner.t));
            auto e = std::hypot(uv.x - m.pixels[v].x, uv.y - m.pixels[v].y);
            sum += e * e;
            out.pose.max_error_px = std::max(out.pose.max_error_px, e);
        }
    out.pose.rms_px = std::sqrt(sum / double(best.size() * 2));
    if (out.pose.rms_px > 1.8) {
        out.reason = "reprojection_error";
        return out;
    }
    std::copy_n(winner.r.val, 9, out.pose.rotation.begin());
    std::copy_n(winner.t.val, 3, out.pose.translation_m.begin());
    out.width_m = winner.scale;
    out.height_m = winner.scale * aspect;
    out.matches = std::move(best);
    const std::array<cv::Vec3d, 4> corners{
        {{-.5, aspect / 2, 0}, {.5, aspect / 2, 0}, {.5, -aspect / 2, 0}, {-.5, -aspect / 2, 0}}};
    for (std::size_t v = 0; v < 2; ++v)
        for (std::size_t side = 0; side < 4; ++side)
            for (int k = 0; k < 12; ++k) {
                auto p = corners[side] * (1 - k / 12.) + corners[(side + 1) % 4] * (k / 12.);
                out.outline[v].push_back(
                    rig.cameras[v].project(point(winner.r * p * winner.scale + winner.t)));
            }
    out.status = "measured";
    out.reason = "stereo_photo_pose";
    return out;
}

struct PhotoTracker::Impl {
    struct Bank {
        std::vector<cv::KeyPoint> keys;
        std::vector<int> locations;
        cv::Mat descriptors;
        int width{}, height{};
    };
    struct View {
        cv::Mat mapx, mapy, k;
        std::vector<ImagePoint> outline;
    };
    StereoRig rig;
    std::vector<Bank> banks;
    std::array<View, 2> views;
    cv::Ptr<cv::SIFT> sift = cv::SIFT::create(2200, 3, .02, 10, 1.6);
    double aspect;
    Impl(CameraFrame reference, StereoRig r)
        : rig(std::move(r)), aspect(double(reference.height) / reference.width) {
        reference.validate();
        validate_stereo_rig(rig);
        require(reference.width <= 1920 && reference.height <= 1920 && reference.width >= 64 &&
                    reference.height >= 64,
                "reference dimensions must be 64..1920 pixels");
        require(aspect >= .2 && aspect <= 5, "reference aspect outside supported range");
        cv::Mat image(int(reference.height), int(reference.width), CV_8U, reference.pixels.data(),
                      reference.stride_bytes);
        // Include phone-sized images, not just desktop-sized reference features.
        for (int edge : {60, 120, 240, 480, 960}) {
            auto factor = std::min(1., double(edge) / std::max(image.cols, image.rows));
            cv::Mat scaled;
            cv::resize(image, scaled, {}, factor, factor, cv::INTER_AREA);
            if (!banks.empty() && banks.back().width == scaled.cols &&
                banks.back().height == scaled.rows)
                continue;
            Bank b;
            b.width = scaled.cols;
            b.height = scaled.rows;
            sift->detectAndCompute(scaled, cv::noArray(), b.keys, b.descriptors);
            root_sift(b.descriptors);
            // SIFT can emit several orientations at the SAME reference location.
            // They describe one physical point, not competing image locations.
            for (std::size_t i = 0; i < b.keys.size(); ++i) {
                int id = int(i);
                for (std::size_t j = 0; j < i; ++j)
                    if (cv::norm(b.keys[i].pt - b.keys[j].pt) < .001) {
                        id = b.locations[j];
                        break;
                    }
                b.locations.push_back(id);
            }
            if (b.keys.size() >= 12)
                banks.push_back(std::move(b));
        }
        require(!banks.empty(), "photo has too few distinctive features; choose a detailed photo");
        for (std::size_t v = 0; v < 2; ++v) {
            const auto &c = rig.cameras[v].calibration;
            auto &view = views[v];
            // Preserve the front cameras' 1280-pixel detail; a tiny phone already
            // has few usable pixels before any additional resize.
            double scale = std::min(1., 1280. / std::max(c.width, c.height));
            cv::Size size(int(c.width * scale), int(c.height * scale));
            view.k = (cv::Mat_<double>(3, 3) << c.fx * scale, 0, c.cx * scale, 0, c.fy * scale,
                      c.cy * scale, 0, 0, 1);
            cv::Matx33d native(c.fx, 0, c.cx, 0, c.fy, c.cy, 0, 0, 1);
            cv::fisheye::initUndistortRectifyMap(native, c.distortion, cv::Matx33d::eye(), view.k,
                                                 size, CV_32FC1, view.mapx, view.mapy);
            const std::array<cv::Point2d, 4> corners{
                {{0, 0},
                 {double(size.width - 1), 0},
                 {double(size.width - 1), double(size.height - 1)},
                 {0, double(size.height - 1)}}};
            const auto &camera = rig.cameras[v];
            for (std::size_t side = 0; side < 4; ++side)
                for (int i = 0; i < 16; ++i) {
                    auto p = corners[side] * (1 - i / 16.) + corners[(side + 1) % 4] * (i / 16.);
                    cv::Vec3d ray((p.x - view.k.at<double>(0, 2)) / view.k.at<double>(0, 0),
                                  (p.y - view.k.at<double>(1, 2)) / view.k.at<double>(1, 1), 1);
                    view.outline.push_back(
                        camera.project(point(cv::Vec3d(camera.origin_m.data()) +
                                             cv::Matx33d(camera.rotation.data()) * ray)));
                }
        }
    }
};
PhotoTracker::PhotoTracker(CameraFrame reference, StereoRig rig)
    : impl_(std::make_unique<Impl>(std::move(reference), std::move(rig))) {}
PhotoTracker::~PhotoTracker() = default;
const StereoRig &PhotoTracker::rig() const {
    return impl_->rig;
}
PhotoPose PhotoTracker::update(const StereoPair &pair) {
    auto &s = *impl_;
    validate(s.rig, pair);
    std::array<std::vector<cv::KeyPoint>, 2> keys;
    std::array<cv::Mat, 2> descriptors;
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &f = pair.frames[v];
        cv::Mat raw(int(f.height), int(f.width), CV_8U, const_cast<std::uint8_t *>(f.pixels.data()),
                    f.stride_bytes);
        cv::Mat image;
        cv::remap(raw, image, s.views[v].mapx, s.views[v].mapy, cv::INTER_LINEAR);
        s.sift->detectAndCompute(image, cv::noArray(), keys[v], descriptors[v]);
        root_sift(descriptors[v]);
    }
    PhotoPose best;
    cv::BFMatcher matcher(cv::NORM_L2);
    for (const auto &bank : s.banks) {
        struct Observation {
            ImagePoint pixel;
            int scene_id;
        };
        std::array<std::map<int, Observation>, 2> accepted;
        std::array<cv::Mat, 2> homographies;
        std::array<std::size_t, 2> counts{};
        PhotoPose diagnostics;
        diagnostics.reference_features = bank.keys.size();
        for (std::size_t v = 0; v < 2; ++v) {
            diagnostics.scene_features[v] = keys[v].size();
            diagnostics.search_outline[v] = s.views[v].outline;
            if (descriptors[v].rows < 2)
                continue;
            std::vector<std::vector<cv::DMatch>> candidates;
            matcher.knnMatch(descriptors[v], bank.descriptors, candidates,
                             std::min(8, bank.descriptors.rows));
            std::vector<cv::DMatch> good;
            for (const auto &m : candidates) {
                if (m.empty())
                    continue;
                auto id = bank.locations[std::size_t(m[0].trainIdx)];
                auto other = std::find_if(m.begin() + 1, m.end(), [&](auto candidate) {
                    return bank.locations[std::size_t(candidate.trainIdx)] != id;
                });
                if (other != m.end() && m[0].distance < .72f * other->distance)
                    good.emplace_back(m[0].queryIdx, id, m[0].distance);
            }
            std::sort(good.begin(), good.end(),
                      [](auto a, auto b) { return a.distance < b.distance; });
            std::set<int> used;
            std::vector<cv::Point2f> a, b;
            std::vector<int> ids, scene_ids;
            for (auto m : good)
                if (used.insert(m.trainIdx).second) {
                    a.push_back(bank.keys[std::size_t(m.trainIdx)].pt);
                    b.push_back(keys[v][std::size_t(m.queryIdx)].pt);
                    ids.push_back(m.trainIdx);
                    scene_ids.push_back(m.queryIdx);
                }
            diagnostics.descriptor_matches[v] = a.size();
            if (a.size() < 12)
                continue;
            cv::Mat mask;
            auto h = cv::findHomography(a, b, cv::RANSAC, 2.5, mask, 2000, .995);
            if (h.empty())
                continue;
            homographies[v] = h;
            const auto &k = s.views[v].k;
            const auto &camera = s.rig.cameras[v];
            cv::Matx33d rotation(camera.rotation.data());
            cv::Vec3d origin(camera.origin_m.data());
            for (std::size_t i = 0; i < a.size(); ++i)
                if (mask.at<std::uint8_t>(int(i))) {
                    cv::Vec3d ray((b[i].x - k.at<double>(0, 2)) / k.at<double>(0, 0),
                                  (b[i].y - k.at<double>(1, 2)) / k.at<double>(1, 1), 1);
                    accepted[v][ids[i]] = {camera.project(point(origin + rotation * ray)),
                                           scene_ids[i]};
                }
            counts[v] = accepted[v].size();
            for (auto [id, observation] : accepted[v]) {
                if (diagnostics.view_points[v].size() == 256)
                    break;
                diagnostics.view_points[v].push_back(observation.pixel);
            }
        }
        std::vector<PhotoMatch> common;
        if (counts[0] >= 12 && counts[1] >= 12) {
            // Match actual left/right observations. Requiring identical reference
            // descriptor IDs discards valid stereo points when each camera picks
            // a different SIFT orientation/scale at the same image feature.
            std::array<cv::Mat, 2> stereo_descriptors;
            std::array<std::vector<int>, 2> ids;
            for (std::size_t v = 0; v < 2; ++v)
                for (auto [id, observation] : accepted[v]) {
                    ids[v].push_back(id);
                    stereo_descriptors[v].push_back(descriptors[v].row(observation.scene_id));
                }
            std::vector<std::vector<cv::DMatch>> pairs;
            matcher.knnMatch(stereo_descriptors[0], stereo_descriptors[1], pairs, 2);
            std::vector<cv::DMatch> good;
            for (const auto &p : pairs)
                if (p.size() == 2 && p[0].distance < .72f * p[1].distance)
                    good.push_back(p[0]);
            std::sort(good.begin(), good.end(),
                      [](auto a, auto b) { return a.distance < b.distance; });
            std::set<int> used;
            std::vector<cv::Point2f> left_locations, right_locations;
            auto append = [&](int id, const Observation &right) {
                const auto &left = accepted[0].at(id);
                auto p = bank.keys[std::size_t(id)].pt;
                std::vector<cv::Point2f> expected;
                cv::perspectiveTransform(std::vector<cv::Point2f>{p}, expected, homographies[1]);
                auto lp = keys[0][std::size_t(left.scene_id)].pt;
                auto rp = keys[1][std::size_t(right.scene_id)].pt;
                auto duplicate = [](const auto &locations, auto p) {
                    return std::any_of(locations.begin(), locations.end(),
                                       [&](auto q) { return cv::norm(p - q) < .001; });
                };
                if (cv::norm(expected[0] - rp) > 2.5 || duplicate(left_locations, lp) ||
                    duplicate(right_locations, rp))
                    return false;
                left_locations.push_back(lp);
                right_locations.push_back(rp);
                common.push_back(
                    {{(p.x + .5) / bank.width - .5, (.5 - (p.y + .5) / bank.height) * s.aspect},
                     {left.pixel, right.pixel}});
                return true;
            };
            for (auto m : good) {
                if (!used.count(m.trainIdx) &&
                    append(ids[0][std::size_t(m.queryIdx)],
                           accepted[1].at(ids[1][std::size_t(m.trainIdx)])))
                    used.insert(m.trainIdx);
            }
            // Retain independently verified shared-reference observations too;
            // a second ratio test is not required when both views already agree
            // on the same reference location. Never count a scene point twice.
            for (auto [id, observation] : accepted[0])
                if (accepted[1].count(id))
                    append(id, accepted[1].at(id));
        }
        auto result = estimate_photo_pose(s.rig, pair, common, s.aspect);
        result.view_inliers = counts;
        result.reference_features = diagnostics.reference_features;
        result.scene_features = diagnostics.scene_features;
        result.descriptor_matches = diagnostics.descriptor_matches;
        result.view_points = std::move(diagnostics.view_points);
        result.search_outline = std::move(diagnostics.search_outline);
        if (common.size() < 12) {
            if (result.scene_features[0] < 12 || result.scene_features[1] < 12)
                result.reason = "too_few_camera_features";
            else if (result.descriptor_matches[0] < 12 || result.descriptor_matches[1] < 12)
                result.reason = "too_few_descriptor_matches";
            else if (counts[0] < 12 || counts[1] < 12)
                result.reason = "photo_not_verified_in_both_views";
            else
                result.reason = "too_few_stereo_feature_matches";
        }
        auto evidence = [](const PhotoPose &p) {
            return std::array<std::size_t, 5>{
                p.triangulated, p.stereo_candidates, p.view_inliers[0] + p.view_inliers[1],
                p.descriptor_matches[0] + p.descriptor_matches[1], p.reference_features};
        };
        if (result.status == "measured" &&
            (best.status != "measured" || result.matches.size() > best.matches.size()))
            best = std::move(result);
        else if (best.status != "measured" && evidence(result) > evidence(best))
            best = std::move(result);
    }
    return best;
}
} // namespace framephone
