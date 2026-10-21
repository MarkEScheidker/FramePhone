#include "framephone/learned_photo.hpp"
#include "photo_worker.hpp"
#include <algorithm>
#include <cmath>
#include <map>
#include <opencv2/calib3d.hpp>
#include <opencv2/imgproc.hpp>

namespace framephone {
namespace {
using Json = nlohmann::json;
constexpr int edge = 640;
void require(bool ok, const char *reason) {
    if (!ok)
        throw std::invalid_argument(reason);
}
std::vector<std::uint8_t> pixels(const CameraFrame &f) {
    std::vector<std::uint8_t> out;
    out.reserve(std::size_t(f.width) * f.height);
    for (unsigned y = 0; y < f.height; ++y)
        out.insert(out.end(), f.pixels.begin() + std::size_t(y) * f.stride_bytes,
                   f.pixels.begin() + std::size_t(y) * f.stride_bytes + f.width);
    return out;
}
struct Observation {
    ImagePoint reference, pixel;
};
std::optional<cv::Point2f> correlate(const cv::Mat &anchor, const cv::Mat &current,
                                     cv::Point2f source, cv::Point2f expected, int radius) {
    constexpr int patch = 15, half = patch / 2;
    if (!std::isfinite(source.x) || !std::isfinite(source.y) || !std::isfinite(expected.x) ||
        !std::isfinite(expected.y))
        return {};
    if (expected.x < -radius || expected.y < -radius || expected.x > edge + radius ||
        expected.y > edge + radius)
        return {};
    if (source.x < half || source.y < half || source.x >= edge - half || source.y >= edge - half)
        return {};
    cv::Mat pattern;
    cv::getRectSubPix(anchor, {patch, patch}, source, pattern, CV_32F);
    cv::Scalar mean, deviation;
    cv::meanStdDev(pattern, mean, deviation);
    if (deviation[0] < 4)
        return {};
    int x0 = std::max(0, int(std::floor(expected.x)) - radius - half);
    int y0 = std::max(0, int(std::floor(expected.y)) - radius - half);
    int x1 = std::min(edge, int(std::ceil(expected.x)) + radius + half + 1);
    int y1 = std::min(edge, int(std::ceil(expected.y)) + radius + half + 1);
    if (x1 - x0 < patch || y1 - y0 < patch)
        return {};
    cv::Mat scores, region;
    current(cv::Rect(x0, y0, x1 - x0, y1 - y0)).convertTo(region, CV_32F);
    cv::matchTemplate(region, pattern, scores, cv::TM_CCOEFF_NORMED);
    double value;
    cv::Point peak;
    cv::minMaxLoc(scores, nullptr, &value, nullptr, &peak);
    if (!std::isfinite(value) || value < .82)
        return {};
    // Sample both images at fractional coordinates. A parabola through integer
    // correlation scores biases locations when the anchor itself is fractional.
    pattern -= mean[0];
    const auto norm = cv::norm(pattern);
    auto score = [&](cv::Point2f center) {
        if (center.x < half || center.y < half || center.x >= edge - half ||
            center.y >= edge - half)
            return -1.;
        cv::Mat candidate;
        cv::getRectSubPix(current, {patch, patch}, center, candidate, CV_32F);
        candidate -= cv::mean(candidate)[0];
        auto divisor = norm * cv::norm(candidate);
        return divisor > 1e-8 ? pattern.dot(candidate) / divisor : -1.;
    };
    cv::Point2f best(float(x0 + peak.x + half), float(y0 + peak.y + half));
    value = score(best);
    for (float step : {.5f, .25f, .125f, .0625f, .03125f}) {
        auto center = best;
        for (int y = -1; y <= 1; ++y)
            for (int x = -1; x <= 1; ++x) {
                auto candidate = center + cv::Point2f(x * step, y * step);
                auto s = score(candidate);
                if (s > value) {
                    value = s;
                    best = candidate;
                }
            }
    }
    return value >= .82 ? std::optional<cv::Point2f>(best) : std::nullopt;
}
} // namespace
struct LearnedPhotoTracker::Impl {
    struct View {
        cv::Mat mapx, mapy;
        std::vector<std::uint8_t> mask;
        cv::Matx33d head_rotation;
        double focal{};
    };
    StereoRig rig;
    PhotoWorker worker;
    double aspect;
    std::vector<std::array<View, 2>> views;
    std::size_t next_view{}, sequence{};
    int active{-1}, misses{};
    std::optional<PhotoPose> previous;
    std::array<cv::Mat, 2> anchor_images;
    std::vector<PhotoMatch> anchors;
    std::size_t patch_frames{};
    Impl(CameraFrame reference, StereoRig r, std::function<bool()> cancelled)
        : rig(std::move(r)), worker(std::move(cancelled)),
          aspect(double(reference.height) / reference.width) {
        reference.validate();
        validate_stereo_rig(rig);
        require(reference.width >= 64 && reference.height >= 64 && reference.width <= 1920 &&
                    reference.height <= 1920 && aspect >= .2 && aspect <= 5,
                "invalid learned photo reference dimensions");
        auto ready = worker.exchange(
            {{"op", "init"}, {"width", reference.width}, {"height", reference.height}},
            {pixels(reference)});
        require(ready.at("op") == "ready" && ready.at("backend") == "xfeat_lighterglue",
                "unexpected learned photo worker initialization");
        // The same virtual head-space directions in each physical camera keep
        // the stereo search regions comparable despite non-parallel extrinsics.
        const cv::Matx33d head_camera(1, 0, 0, 0, -1, 0, 0, 0, -1);
        const std::array<std::array<double, 2>, 9> directions{{{0, 0},
                                                               {-40, 0},
                                                               {40, 0},
                                                               {0, -30},
                                                               {0, 30},
                                                               {-40, -30},
                                                               {40, -30},
                                                               {-40, 30},
                                                               {40, 30}}};
        for (auto direction : directions) {
            std::array<View, 2> pair;
            bool usable = true;
            cv::Matx33d yaw, pitch;
            cv::Rodrigues(cv::Vec3d(0, direction[0] * CV_PI / 180, 0), yaw);
            cv::Rodrigues(cv::Vec3d(direction[1] * CV_PI / 180, 0, 0), pitch);
            for (std::size_t v = 0; v < 2; ++v) {
                auto &view = pair[v];
                const auto &camera = rig.cameras[v];
                const auto &c = camera.calibration;
                view.head_rotation = yaw * pitch * head_camera;
                view.focal = std::max(std::min(c.fx, c.fy), 240.);
                cv::Matx33d native(c.fx, 0, c.cx, 0, c.fy, c.cy, 0, 0, 1);
                cv::Matx33d target(view.focal, 0, (edge - 1) / 2., 0, view.focal, (edge - 1) / 2.,
                                   0, 0, 1);
                auto rotation = view.head_rotation.t() * cv::Matx33d(camera.rotation.data());
                cv::fisheye::initUndistortRectifyMap(native, c.distortion, rotation, target,
                                                     {edge, edge}, CV_32FC1, view.mapx, view.mapy);
                view.mask.resize(edge * edge);
                cv::Mat mask(edge, edge, CV_8U, view.mask.data());
                for (int y = 0; y < edge; ++y)
                    for (int x = 0; x < edge; ++x) {
                        auto u = view.mapx.at<float>(y, x), w = view.mapy.at<float>(y, x);
                        mask.at<std::uint8_t>(y, x) =
                            u >= 8 && w >= 8 && u < c.width - 8 && w < c.height - 8 ? 255 : 0;
                    }
                cv::erode(mask, mask, cv::Mat(), {-1, -1}, 4);
                usable &= cv::countNonZero(mask) >= edge * edge / 8;
            }
            if (usable)
                views.push_back(std::move(pair));
        }
        require(!views.empty(), "front cameras have no usable shared calibrated search views");
    }
    static ImagePoint project(const RigCamera &camera, const View &view, ImagePoint p) {
        auto ray = view.head_rotation * cv::Vec3d((p.x - (edge - 1) / 2.) / view.focal,
                                                  (p.y - (edge - 1) / 2.) / view.focal, 1);
        auto h = cv::Vec3d(camera.origin_m.data()) + ray;
        return camera.project({h[0], h[1], h[2]});
    }
    cv::Point2f in_view(std::size_t v, const View &view, ImagePoint native) const {
        auto native_ray = rig.cameras[v].ray(native);
        auto ray = view.head_rotation.t() * cv::Vec3d(native_ray.x, native_ray.y, native_ray.z);
        return {float((edge - 1) / 2. + view.focal * ray[0] / ray[2]),
                float((edge - 1) / 2. + view.focal * ray[1] / ray[2])};
    }
    PhotoPose stereo_patches(const StereoPair &pair, const std::array<View, 2> &views,
                             const std::vector<std::vector<std::uint8_t>> &payload,
                             const std::vector<Observation> &left, const cv::Mat &right_h) const {
        // Independent reference matches can choose different landmark IDs in
        // each camera. Use their homographies only as search hints, then measure
        // actual left/right image correspondences with bidirectional NCC.
        std::vector<PhotoMatch> matches;
        std::vector<cv::Point2f> used;
        cv::Mat images[2] = {
            cv::Mat(edge, edge, CV_8U, const_cast<std::uint8_t *>(payload[0].data())),
            cv::Mat(edge, edge, CV_8U, const_cast<std::uint8_t *>(payload[1].data()))};
        std::size_t attempts = 0;
        for (const auto &o : left) {
            if (++attempts > 256)
                break;
            if (std::abs(o.reference.x) > .45 || std::abs(o.reference.y) > .45 * aspect)
                continue;
            auto source = in_view(0, views[0], o.pixel);
            std::vector<cv::Point2f> expected;
            cv::perspectiveTransform(
                std::vector<cv::Point2f>{{float(o.reference.x), float(o.reference.y)}}, expected,
                right_h);
            auto found = correlate(images[0], images[1], source, expected[0], 12);
            if (!found || found->x < 0 || found->y < 0 || found->x >= edge || found->y >= edge ||
                !payload[3][std::size_t(int(found->y)) * edge + std::size_t(int(found->x))])
                continue;
            auto back = correlate(images[1], images[0], *found, source, 3);
            if (!back || cv::norm(*back - source) > .8)
                continue;
            if (std::any_of(used.begin(), used.end(),
                            [&](auto p) { return cv::norm(p - *found) < 1.; }))
                continue;
            used.push_back(*found);
            matches.push_back(
                {o.reference, {o.pixel, project(rig.cameras[1], views[1], {found->x, found->y})}});
        }
        auto result = estimate_photo_pose(rig, pair, matches, aspect);
        result.pose_method = "stereo_patch_refinement";
        if (matches.size() < 12)
            result.reason = "too_few_stereo_feature_matches";
        return result;
    }
    PhotoPose track_patches(const StereoPair &pair, const std::array<View, 2> &view,
                            const std::vector<std::vector<std::uint8_t>> &payload) const {
        std::vector<PhotoMatch> matches;
        if (!previous || anchors.size() < 12)
            return {};
        cv::Matx33d r(previous->pose.rotation.data());
        cv::Vec3d t(previous->pose.translation_m.data());
        for (const auto &anchor : anchors) {
            PhotoMatch candidate{anchor.reference, {}};
            bool valid = true;
            for (std::size_t v = 0; v < 2; ++v) {
                auto original = in_view(v, view[v], anchor.pixels[v]);
                auto position = r * cv::Vec3d(anchor.reference.x * previous->width_m,
                                              anchor.reference.y * previous->width_m, 0) +
                                t;
                auto ray = view[v].head_rotation.t() *
                           (position - cv::Vec3d(rig.cameras[v].origin_m.data()));
                if (ray[2] <= .01) {
                    valid = false;
                    break;
                }
                cv::Point2f expected(float((edge - 1) / 2. + view[v].focal * ray[0] / ray[2]),
                                     float((edge - 1) / 2. + view[v].focal * ray[1] / ray[2]));
                cv::Mat current(edge, edge, CV_8U, const_cast<std::uint8_t *>(payload[v].data()));
                auto found = correlate(anchor_images[v], current, original, expected, 12);
                if (!found || found->x < 0 || found->y < 0 || found->x >= edge ||
                    found->y >= edge ||
                    !payload[2 + v]
                            [std::size_t(int(found->y)) * edge + std::size_t(int(found->x))]) {
                    valid = false;
                    break;
                }
                auto back = correlate(current, anchor_images[v], *found, original, 3);
                if (!back || cv::norm(*back - original) > .8) {
                    valid = false;
                    break;
                }
                candidate.pixels[v] = project(rig.cameras[v], view[v], {found->x, found->y});
            }
            if (valid)
                matches.push_back(candidate);
        }
        if (matches.size() < std::max(std::size_t(12), anchors.size() / 4))
            return {};
        auto result = estimate_photo_pose(rig, pair, matches, aspect, &*previous);
        result.tracking_method = "normalized_patches";
        result.reference_features = anchors.size();
        result.scene_features = {matches.size(), matches.size()};
        result.descriptor_matches = result.scene_features;
        result.view_inliers = result.scene_features;
        for (const auto &match : matches)
            for (std::size_t v = 0; v < 2; ++v)
                if (result.view_points[v].size() < 256)
                    result.view_points[v].push_back(match.pixels[v]);
        return result;
    }
    void remember(const PhotoPose &result, const std::vector<std::vector<std::uint8_t>> &payload) {
        if (result.tracking_method == "feature_matching") {
            anchors.clear();
            for (const auto &match : result.matches)
                if (std::abs(match.reference.x) < .45 && std::abs(match.reference.y) < .45 * aspect)
                    anchors.push_back(match);
            for (std::size_t v = 0; v < 2; ++v)
                anchor_images[v] =
                    cv::Mat(edge, edge, CV_8U, const_cast<std::uint8_t *>(payload[v].data()))
                        .clone();
            patch_frames = 0;
        }
        previous = result;
    }
    std::vector<std::uint8_t> search_mask(std::size_t v, const View &view) const {
        auto bytes = view.mask;
        if (!previous || active < 0)
            return bytes;
        cv::Matx33d r(previous->pose.rotation.data());
        cv::Vec3d t(previous->pose.translation_m.data()), origin(rig.cameras[v].origin_m.data());
        double x0 = edge, y0 = edge, x1 = 0, y1 = 0;
        for (double x : {-.5, .5})
            for (double y : {-aspect / 2, aspect / 2}) {
                auto p =
                    view.head_rotation.t() *
                    (r * cv::Vec3d(x * previous->width_m, y * previous->width_m, 0) + t - origin);
                if (p[2] <= .01)
                    return bytes;
                auto u = (edge - 1) / 2. + view.focal * p[0] / p[2];
                auto w = (edge - 1) / 2. + view.focal * p[1] / p[2];
                x0 = std::min(x0, u);
                x1 = std::max(x1, u);
                y0 = std::min(y0, w);
                y1 = std::max(y1, w);
            }
        auto padding = std::max(32., .35 * std::max(x1 - x0, y1 - y0));
        for (int y = 0; y < edge; ++y)
            for (int x = 0; x < edge; ++x)
                if (x < x0 - padding || x > x1 + padding || y < y0 - padding || y > y1 + padding)
                    bytes[std::size_t(y) * edge + std::size_t(x)] = 0;
        return bytes;
    }
};
LearnedPhotoTracker::LearnedPhotoTracker(CameraFrame reference, StereoRig rig,
                                         std::function<bool()> cancelled)
    : impl_(std::make_unique<Impl>(std::move(reference), std::move(rig), std::move(cancelled))) {}
LearnedPhotoTracker::~LearnedPhotoTracker() = default;
PhotoPose LearnedPhotoTracker::update(const StereoPair &pair) {
    auto &s = *impl_;
    // This also validates exact camera/calibration identities, dimensions and skew.
    PhotoPose best = estimate_photo_pose(s.rig, pair, {}, s.aspect);
    auto index = s.active >= 0 ? std::size_t(s.active) : s.next_view++ % s.views.size();
    const auto &views = s.views[index];
    std::vector<std::vector<std::uint8_t>> payload;
    for (std::size_t v = 0; v < 2; ++v) {
        const auto &f = pair.frames[v];
        cv::Mat raw(int(f.height), int(f.width), CV_8U, const_cast<std::uint8_t *>(f.pixels.data()),
                    f.stride_bytes),
            image;
        cv::remap(raw, image, views[v].mapx, views[v].mapy, cv::INTER_LINEAR);
        payload.emplace_back(image.data, image.data + image.total());
    }
    std::array<std::vector<ImagePoint>, 2> boundaries;
    for (std::size_t v = 0; v < 2; ++v) {
        payload.push_back(s.search_mask(v, views[v]));
        cv::Mat mask(edge, edge, CV_8U, payload.back().data());
        std::vector<std::vector<cv::Point>> contours;
        cv::findContours(mask.clone(), contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_NONE);
        if (!contours.empty()) {
            const auto &contour = *std::max_element(
                contours.begin(), contours.end(), [](const auto &a, const auto &b) {
                    return cv::contourArea(a) < cv::contourArea(b);
                });
            auto step = std::max(std::size_t(1), (contour.size() + 95) / 96);
            for (std::size_t i = 0; i < contour.size(); i += step) {
                auto p = contour[i];
                boundaries[v].push_back({views[v].mapx.at<float>(p), views[v].mapy.at<float>(p)});
            }
        }
    }
    auto tracked = s.track_patches(pair, views, payload);
    if (tracked.status == "measured" && ++s.patch_frames < 10) {
        tracked.backend = "xfeat_lighterglue";
        tracked.search_view = index;
        tracked.search_view_count = s.views.size();
        tracked.search_outline = boundaries;
        s.remember(tracked, payload);
        s.misses = 0;
        return tracked;
    }
    auto response = s.worker.exchange(
        {{"op", "match"}, {"sequence", ++s.sequence}, {"width", edge}, {"height", edge}}, payload);
    require(response.at("op") == "matches" && response.at("sequence") == s.sequence,
            "learned photo worker sequence mismatch");
    require(response.at("banks").is_array() && !response.at("banks").empty() &&
                response.at("banks").size() <= 4 && response.at("scene_features").size() == 2,
            "invalid learned feature reply");
    for (const auto &bank : response.at("banks")) {
        std::array<std::map<int, Observation>, 2> accepted;
        std::array<cv::Mat, 2> homographies;
        PhotoPose diagnostic;
        diagnostic.reference_features = bank.at("reference_features").get<std::size_t>();
        require(diagnostic.reference_features >= 12 && diagnostic.reference_features <= 4096 &&
                    bank.at("matches").size() == 2,
                "learned photo feature limit exceeded");
        for (std::size_t v = 0; v < 2; ++v) {
            diagnostic.scene_features[v] = response.at("scene_features").at(v).get<std::size_t>();
            diagnostic.search_outline[v] = boundaries[v];
            const auto &matches = bank.at("matches").at(v);
            require(matches.is_array() && matches.size() <= 4096 &&
                        diagnostic.scene_features[v] <= 4096,
                    "invalid learned match count");
            std::vector<cv::Point2f> a, b;
            std::vector<int> ids;
            std::map<int, bool> used;
            for (const auto &match : matches) {
                require(match.is_array() && match.size() == 6, "invalid learned match record");
                auto id = match.at(0).get<int>();
                double x = match.at(1), y = match.at(2), u = match.at(3), w = match.at(4),
                       score = match.at(5);
                require(id >= 0 && std::size_t(id) < diagnostic.reference_features &&
                            std::isfinite(x) && std::isfinite(y) && std::isfinite(u) &&
                            std::isfinite(w) && std::isfinite(score) && std::abs(x) <= .501 &&
                            std::abs(y) <= s.aspect / 2 + .001 && u >= 0 && w >= 0 && u < edge &&
                            w < edge && score >= 0 && score <= 1,
                        "invalid learned match coordinates");
                if (used.emplace(id, true).second &&
                    views[v].mask[std::size_t(int(w)) * edge + std::size_t(int(u))]) {
                    a.emplace_back(float(x), float(y));
                    b.emplace_back(float(u), float(w));
                    ids.push_back(id);
                }
            }
            diagnostic.descriptor_matches[v] = a.size();
            if (a.size() < 12)
                continue;
            cv::Mat mask;
            auto h = cv::findHomography(a, b, cv::RANSAC, 2.5, mask, 2000, .995);
            if (h.empty())
                continue;
            homographies[v] = h;
            for (std::size_t i = 0; i < a.size(); ++i)
                if (mask.at<std::uint8_t>(int(i))) {
                    Observation observation{
                        {a[i].x, a[i].y},
                        Impl::project(s.rig.cameras[v], views[v], {b[i].x, b[i].y})};
                    accepted[v].emplace(ids[i], observation);
                    if (diagnostic.view_points[v].size() < 256)
                        diagnostic.view_points[v].push_back(observation.pixel);
                }
            diagnostic.view_inliers[v] = accepted[v].size();
        }
        std::vector<PhotoMatch> common;
        for (const auto &[id, left] : accepted[0])
            if (auto right = accepted[1].find(id); right != accepted[1].end()) {
                require(std::hypot(left.reference.x - right->second.reference.x,
                                   left.reference.y - right->second.reference.y) < 1e-6,
                        "learned reference feature identity changed between cameras");
                common.push_back({left.reference, {left.pixel, right->second.pixel}});
            }
        auto result = estimate_photo_pose(s.rig, pair, common, s.aspect);
        if (result.status != "measured" && accepted[0].size() >= 12 && accepted[1].size() >= 12) {
            std::vector<Observation> left;
            for (const auto &[id, o] : accepted[0])
                left.push_back(o);
            auto stereo = s.stereo_patches(pair, views, payload, left, homographies[1]);
            if (stereo.status == "measured" ||
                std::array<std::size_t, 2>{stereo.triangulated, stereo.stereo_candidates} >
                    std::array<std::size_t, 2>{result.triangulated, result.stereo_candidates})
                result = std::move(stereo);
        }
        result.reference_features = diagnostic.reference_features;
        result.scene_features = diagnostic.scene_features;
        result.descriptor_matches = diagnostic.descriptor_matches;
        result.view_inliers = diagnostic.view_inliers;
        result.view_points = std::move(diagnostic.view_points);
        result.search_outline = std::move(diagnostic.search_outline);
        if (result.status != "measured" && common.size() < 12 &&
            result.pose_method != "stereo_patch_refinement") {
            if (result.scene_features[0] < 12 || result.scene_features[1] < 12)
                result.reason = "too_few_camera_features";
            else if (result.descriptor_matches[0] < 12 || result.descriptor_matches[1] < 12)
                result.reason = "too_few_descriptor_matches";
            else if (result.view_inliers[0] < 12 || result.view_inliers[1] < 12)
                result.reason = "photo_not_verified_in_both_views";
            else
                result.reason = "too_few_stereo_feature_matches";
        }
        auto evidence = [](const PhotoPose &p) {
            return std::array<std::size_t, 4>{p.triangulated, p.stereo_candidates,
                                              p.view_inliers[0] + p.view_inliers[1],
                                              p.descriptor_matches[0] + p.descriptor_matches[1]};
        };
        if ((result.status == "measured" &&
             (best.status != "measured" || result.matches.size() > best.matches.size())) ||
            (best.status != "measured" && evidence(result) >= evidence(best)))
            best = std::move(result);
    }
    if (best.status != "measured" && tracked.status == "measured") {
        best = std::move(tracked);
        best.search_outline = boundaries;
        s.patch_frames = 0;
    }
    best.backend = "xfeat_lighterglue";
    best.search_view = index;
    best.search_view_count = s.views.size();
    if (best.status == "measured") {
        s.remember(best, payload);
        s.active = int(index);
        s.misses = 0;
    } else if (s.active >= 0 && ++s.misses >= 3) {
        s.active = -1;
        s.previous.reset();
        s.anchors.clear();
    }
    return best;
}
} // namespace framephone
