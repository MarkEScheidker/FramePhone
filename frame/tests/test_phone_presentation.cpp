#include "../src/phone_model.hpp"
#include "../src/tracking_fade.hpp"
#include <iostream>

using namespace framephone::surface;
using Json = nlohmann::json;
namespace {
void check(bool ok, const char *message) {
    if (!ok)
        throw std::runtime_error(message);
}
Json gyro(std::uint64_t end, double speed = 1) {
    Json samples = Json::array();
    for (int i = 4; i >= 0; --i)
        samples.push_back({{"host_t_ns", end - i * 5'000'000ULL}, {"w_rad_s", {0, speed, 0}}});
    return samples;
}
} // namespace
int main() {
    try {
        PhoneModel model{{.08, .18}};
        const auto faces = model.surfaces();
        check(std::abs(model.width() - .085) < 1e-12 && std::abs(model.height() - .185) < 1e-12,
              "2mm curves and a narrow flat bezel must surround the actual screen");
        check(faces.size() + 1 < 128,
              "rounded shell and diagnostic buffers must fit overlay budget");
        check(faces[2].kind == PhoneFace::screen && faces[2].width == .08 &&
                  faces[2].height == .18 && faces[2].local == identity(),
              "screen size and calibrated pose must remain unchanged");
        check(std::abs(faces[0].local[11] - faces[1].local[11] - .010) < 1e-12,
              "shell must remain 10mm deep behind the display");
        check(!facing(faces[1].local, {0, 0, .5}) && facing(faces[1].local, {0, 0, -.5}) &&
                  facing(faces[0].local, {0, 0, .5}),
              "back text faces away from the screen");
        const auto front = surface_texture(model, faces[0]);
        check(front.rgba[3] == 255 && front.rgba[(256 * 256 + 128) * 4 + 3] == 0,
              "flat bezel must not add a second alpha layer behind the fading screen");
        const Image black(1, 1, 0);
        check(black.rgba == std::vector<std::uint8_t>({0, 0, 0, 255}),
              "screen is opaque pure black");
        const auto core = model.core_size();
        std::array<bool, 12> rounded_edges{};
        for (const auto &face : faces) {
            check(near(compose(inverse(face.local), face.local), identity(), 1e-10, 1e-7),
                  "all faces use proper rigid transforms");
            if (face.kind == PhoneFace::screen)
                continue;
            check(face.width > 0 && face.height > 0, "positive face dimensions");
            const Vertex normal{face.local[2], face.local[6], face.local[10]};
            const Vertex center{face.local[3], face.local[7],
                                face.local[11] - model.front_z + model.depth / 2};
            check(dot(normal, center) > 0, "all shell normals face outward");
            const auto uv = face.mask.empty()
                                ? std::vector<std::array<double, 2>>{{0, 0}, {1, 0}, {1, 1}, {0, 1}}
                                : face.mask;
            for (const auto &p : uv) {
                Vertex distance{};
                for (int k = 0; k < 3; ++k) {
                    const double value = face.local[k * 4 + 3] +
                                         (p[0] - .5) * face.width * face.local[k * 4] +
                                         (.5 - p[1]) * face.height * face.local[k * 4 + 1] -
                                         (k == 2 ? model.front_z - model.depth / 2 : 0);
                    distance[k] = std::max(0., std::abs(value) - core[k]);
                }
                check(std::abs(std::sqrt(dot(distance, distance)) - .002) < 1e-10,
                      "every curve vertex must lie on the true 2mm rounded box");
            }
            for (int axis = 0; axis < 3; ++axis) {
                const int u = (axis + 1) % 3, v = (axis + 2) % 3;
                if (std::abs(normal[axis]) > 1e-9 || std::abs(normal[u]) < .1 ||
                    std::abs(normal[v]) < .1)
                    continue;
                const int signs = (normal[u] > 0 ? 2 : 0) + (normal[v] > 0 ? 1 : 0);
                rounded_edges[axis * 4 + signs] = true;
            }
            if (!face.mask.empty()) {
                check(face.mask.size() == 3, "corner facet must have three mask vertices");
                const auto image = surface_texture(model, face);
                unsigned visible = 0;
                for (std::size_t i = 3; i < image.rgba.size(); i += 4)
                    visible += image.rgba[i] > 0;
                check(visible > 0 && visible < image.width * image.height,
                      "spherical corner facets must use triangle masks, not overlapping quads");
            }
        }
        for (bool edge : rounded_edges)
            check(edge, "all twelve edges must be curved");
        const auto diagnostics = diagnostic_texture(model, {true, true, true, 30, 20, 12, 1});
        const auto lost = diagnostic_texture(model, {true, false, false, 0, 300, 0, .5});
        check(diagnostics.rgba != lost.rgba, "rear diagnostics must reflect live state");

        constexpr std::uint64_t start = 1'000'000'000;
        Matrix world{0, -1, 0, .2, 1, 0, 0, .1, 0, 0, 1, -.6};
        TrackingFade fade;
        check(!fade.update({}, start, Json::array(), false).pose, "no ghost before first pose");
        check(fade.update(world, start - 250'000'000, Json::array(), false).opacity == 0,
              "new tracking starts transparent");
        check(std::abs(fade.update(world, start - 125'000'000, Json::array(), false).opacity - .5) <
                  1e-12,
              "fade-in midpoint must be 125ms");
        check(fade.update(world, start, Json::array(), false).opacity == 1,
              "tracking reaches full opacity at 250ms");
        const auto first = start + 10'000'000;
        auto held = fade.update({}, first, gyro(first), true);
        check(held.pose && held.opacity == 1 && held.gyro,
              "loss starts full opacity with live gyro");
        auto expected = compose(world, angular_step({0, 1, 0}, .01));
        check(near(*held.pose, expected, 1e-10, 1e-7), "loss gyro must rotate in body axes");
        for (unsigned i = 2; i <= 26; ++i)
            held =
                fade.update({}, start + i * 10'000'000ULL, gyro(start + i * 10'000'000ULL), true);
        check(std::abs(held.opacity - .5) < 1e-12 && held.gyro &&
                  near(*held.pose, compose(world, angular_step({0, 1, 0}, .26)), 1e-10, 1e-7),
              "fresh IMU must continue beyond normal short prediction horizon during fade");
        check((*held.pose)[3] == world[3] && (*held.pose)[7] == world[7] &&
                  (*held.pose)[11] == world[11],
              "gyro must not invent translation");
        auto frozen = fade.update({}, start + 270'000'000, gyro(first), true);
        check(!frozen.gyro && near(*held.pose, *frozen.pose, 1e-10, 1e-7),
              "stale gyro freezes motion");
        auto blocked = fade.update({}, start + 280'000'000, gyro(start + 280'000'000), false);
        check(!blocked.gyro && near(*blocked.pose, *frozen.pose, 1e-10, 1e-7),
              "invalid epoch or clock must not advance orientation");
        check(!fade.update({}, first + TrackingFade::duration_ns, Json::array(), false).pose,
              "phone must disappear at half a second, not remain at tiny opacity");
        check(!fade.update({}, first + TrackingFade::duration_ns + 1, gyro(first), true).pose,
              "gyro alone must never resurrect a faded object");
        check(fade.update(world, start + 2'000'000'000, Json::array(), false).opacity == 0,
              "new measured tracking fades in again");
        fade.update(world, start + 2'250'000'000, Json::array(), false);
        fade.update({}, start + 2'260'000'000, Json::array(), false);
        const auto dim = fade.update({}, start + 2'510'000'000, Json::array(), false);
        check(std::abs(dim.opacity - .5) < 1e-12, "second loss starts a fresh fade");
        check(std::abs(fade.update(world, start + 2'510'000'000, Json::array(), false).opacity -
                       .5) < 1e-12,
              "recovery mid-fade must preserve opacity without a flash");
        check(fade.update(world, start + 2'760'000'000, Json::array(), false).opacity == 1,
              "recovery completes its quarter-second fade-in");
        fade.reset();
        check(!fade.update({}, start + 2'010'000'000, Json::array(), false).pose,
              "headset origin reset must clear old presentation");
        fade.update(world, start - 250'000'000, Json::array(), false);
        fade.update(world, start, Json::array(), false);
        auto gap = gyro(start + 40'000'000);
        gap.erase(gap.begin() + 1, gap.end() - 1);
        check(!fade.update({}, start + 40'000'000, gap, true).gyro,
              "missing IMU coverage must not be integrated");
        std::cout
            << "Phone geometry, face orientation, textures, diagnostics and loss fade passed.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
