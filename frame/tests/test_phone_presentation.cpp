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
        check(std::abs(model.width() - .082) < 1e-12 && std::abs(model.height() - .182) < 1e-12,
              "1mm bezel must surround actual screen");
        check(faces[2].kind == PhoneFace::screen && faces[2].width == .08 &&
                  faces[2].height == .18 && faces[2].local == identity(),
              "screen size and calibrated pose must remain unchanged");
        check(std::abs(faces[0].local[11] - faces[1].local[11] - .010) < 1e-12,
              "shell must be 10mm deep behind the display");
        check(!facing(faces[1].local, {0, 0, .5}) && facing(faces[1].local, {0, 0, -.5}) &&
                  facing(faces[0].local, {0, 0, .5}),
              "back text must face away from front screen");
        const auto shell = shell_texture(model);
        check(shell.rgba[3] == 0 && shell.rgba[(256 * 256 + 128) * 4 + 3] == 255,
              "rounded corners must be transparent and shell opaque");
        const Image black(1, 1, 0);
        const auto front = shell_texture(model, true);
        check(front.rgba[(256 * 256 + 128) * 4 + 3] == 0,
              "shell must not add a second alpha layer behind the fading screen");
        check(black.rgba == std::vector<std::uint8_t>({0, 0, 0, 255}),
              "screen must default to opaque pure black");
        for (const auto &face : faces) {
            const auto rigid = compose(inverse(face.local), face.local);
            check(near(rigid, identity(), 1e-10, 1e-7),
                  "all shell faces must use rigid transforms");
            if (face.kind != PhoneFace::edge)
                continue;
            check(face.width > 0 && face.height == model.depth, "edge dimensions");
            const double outward = face.local[2] * face.local[3] + face.local[6] * face.local[7];
            check(outward > 0, "edge normals must face out of the phone");
            // Every side endpoint lies on the corresponding rounded contour.
            for (double sign : {-1., 1.}) {
                const double x = face.local[3] + sign * face.width / 2 * face.local[0];
                const double y = face.local[7] + sign * face.width / 2 * face.local[4];
                const double dx = std::max(0., std::abs(x) - (model.width() / 2 - model.radius));
                const double dy = std::max(0., std::abs(y) - (model.height() / 2 - model.radius));
                check(std::abs(std::hypot(dx, dy) - model.radius) < 1e-10,
                      "side walls must follow 1mm corner arcs");
            }
        }
        auto diagnostics = diagnostic_texture(model, {true, true, true, 30, 20, 12, 1});
        auto lost = diagnostic_texture(model, {true, false, false, 0, 300, 0, .5});
        check(diagnostics.rgba != shell.rgba && diagnostics.rgba != lost.rgba,
              "rear diagnostics must reflect live state");

        constexpr std::uint64_t start = 1'000'000'000;
        Matrix world{0, -1, 0, .2, 1, 0, 0, .1, 0, 0, 1, -.6};
        TrackingFade fade;
        check(!fade.update({}, start, Json::array(), false).pose, "no ghost before first pose");
        check(fade.update(world, start, Json::array(), false).opacity == 1, "valid pose opaque");
        const auto first = start + 10'000'000;
        auto held = fade.update({}, first, gyro(first), true);
        check(held.pose && held.opacity == 1 && held.gyro,
              "loss starts full opacity with live gyro");
        auto expected = compose(world, angular_step({0, 1, 0}, .01));
        check(near(*held.pose, expected, 1e-10, 1e-7), "loss gyro must rotate in body axes");
        for (unsigned i = 2; i <= 51; ++i)
            held =
                fade.update({}, start + i * 10'000'000ULL, gyro(start + i * 10'000'000ULL), true);
        check(std::abs(held.opacity - .5) < 1e-12 && held.gyro &&
                  near(*held.pose, compose(world, angular_step({0, 1, 0}, .51)), 1e-10, 1e-7),
              "fresh IMU must continue beyond normal short prediction horizon during fade");
        check((*held.pose)[3] == world[3] && (*held.pose)[7] == world[7] &&
                  (*held.pose)[11] == world[11],
              "gyro must not invent translation");
        auto frozen = fade.update({}, start + 520'000'000, gyro(first), true);
        check(!frozen.gyro && near(*held.pose, *frozen.pose, 1e-10, 1e-7),
              "stale gyro freezes motion");
        auto blocked = fade.update({}, start + 530'000'000, gyro(start + 530'000'000), false);
        check(!blocked.gyro && near(*blocked.pose, *frozen.pose, 1e-10, 1e-7),
              "invalid epoch or clock must not advance orientation");
        check(!fade.update({}, first + TrackingFade::duration_ns, Json::array(), false).pose,
              "phone must disappear at one second, not remain at tiny opacity");
        check(!fade.update({}, first + TrackingFade::duration_ns + 1, gyro(first), true).pose,
              "gyro alone must never resurrect a faded object");
        check(fade.update(world, start + 2'000'000'000, Json::array(), false).opacity == 1,
              "new measured tracking restores opacity");
        fade.reset();
        check(!fade.update({}, start + 2'010'000'000, Json::array(), false).pose,
              "headset origin reset must clear old presentation");
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
