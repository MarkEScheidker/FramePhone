#pragma once
#include "arcore_handoff.hpp"
#include <iomanip>
#include <sstream>
#include <string_view>
#include <vector>

namespace framephone::surface {
enum class PhoneFace { body, back, screen, edge };
struct Surface {
    Matrix local;
    double width, height;
    PhoneFace kind;
};

/** Screen center and +Z front normal match the optical/ARCore pose. The shell
 * extends behind this plane; it never changes the calibrated screen size. */
struct PhoneModel {
    Geometry screen;
    static constexpr double bezel = .001, radius = .001, depth = .010;
    static constexpr double front_z = -.00005;
    double width() const {
        return screen.width + 2 * bezel;
    }
    double height() const {
        return screen.height + 2 * bezel;
    }
    std::vector<Surface> surfaces() const {
        auto front = identity(), back = identity();
        front[11] = front_z;
        back[0] = back[10] = -1;
        back[11] = front_z - depth;
        std::vector<Surface> result{{front, width(), height(), PhoneFace::body},
                                    {back, width(), height(), PhoneFace::back},
                                    {identity(), screen.width, screen.height, PhoneFace::screen}};
        std::vector<std::array<double, 2>> outline;
        constexpr double pi = 3.14159265358979323846;
        for (int corner = 0; corner < 4; ++corner) {
            const double cx = (corner == 0 || corner == 3 ? 1 : -1) * (width() / 2 - radius);
            const double cy = (corner < 2 ? 1 : -1) * (height() / 2 - radius);
            for (int step = 0; step <= 4; ++step) {
                const double angle = (corner + step / 4.) * pi / 2;
                outline.push_back({cx + radius * std::cos(angle), cy + radius * std::sin(angle)});
            }
        }
        for (std::size_t i = 0; i < outline.size(); ++i) {
            const auto &a = outline[i], &b = outline[(i + 1) % outline.size()];
            const double dx = b[0] - a[0], dy = b[1] - a[1], length = std::hypot(dx, dy);
            Matrix edge{dx / length,
                        0,
                        dy / length,
                        (a[0] + b[0]) / 2,
                        dy / length,
                        0,
                        -dx / length,
                        (a[1] + b[1]) / 2,
                        0,
                        1,
                        0,
                        front_z - depth / 2};
            result.push_back({edge, length, depth, PhoneFace::edge});
        }
        return result;
    }
};

inline bool facing(const Matrix &surface, const std::array<double, 3> &eye) {
    double dot = 0;
    for (int r = 0; r < 3; ++r)
        dot += surface[r * 4 + 2] * (eye[r] - surface[r * 4 + 3]);
    return dot > 0;
}

struct Image {
    unsigned width, height;
    std::vector<std::uint8_t> rgba;
    Image(unsigned w, unsigned h, std::uint8_t grey) : width(w), height(h), rgba(w * h * 4) {
        for (std::size_t i = 0; i < rgba.size(); i += 4) {
            rgba[i] = rgba[i + 1] = rgba[i + 2] = grey;
            rgba[i + 3] = 255;
        }
    }
};

inline Image shell_texture(const PhoneModel &model, bool screen_opening = false) {
    Image image(256, 512, 48);
    for (unsigned y = 0; y < image.height; ++y)
        for (unsigned x = 0; x < image.width; ++x) {
            const double px = std::abs((x + .5) / image.width - .5) * model.width();
            const double py = std::abs((y + .5) / image.height - .5) * model.height();
            if (screen_opening && px < model.screen.width / 2 && py < model.screen.height / 2) {
                image.rgba[(y * image.width + x) * 4 + 3] = 0;
                continue; // One alpha layer under the screen, including during fades.
            }
            const double dx = std::max(0., std::abs((x + .5) / image.width - .5) * model.width() -
                                               (model.width() / 2 - model.radius));
            const double dy = std::max(0., std::abs((y + .5) / image.height - .5) * model.height() -
                                               (model.height() / 2 - model.radius));
            const double coverage = std::clamp(
                .5 + (model.radius - std::hypot(dx, dy)) / (model.width() / image.width), 0., 1.);
            image.rgba[(y * image.width + x) * 4 + 3] = std::uint8_t(255 * coverage);
        }
    return image;
}

// Small built-in bitmap alphabet keeps the diagnostic back independent of font
// services, graphics contexts and additional runtime packages.
inline std::array<unsigned, 7> glyph(char c) {
    switch (c) {
    case 'A':
        return {14, 17, 17, 31, 17, 17, 17};
    case 'B':
        return {30, 17, 17, 30, 17, 17, 30};
    case 'C':
        return {14, 17, 16, 16, 16, 17, 14};
    case 'D':
        return {30, 17, 17, 17, 17, 17, 30};
    case 'E':
        return {31, 16, 16, 30, 16, 16, 31};
    case 'F':
        return {31, 16, 16, 30, 16, 16, 16};
    case 'G':
        return {14, 17, 16, 23, 17, 17, 15};
    case 'H':
        return {17, 17, 17, 31, 17, 17, 17};
    case 'I':
        return {14, 4, 4, 4, 4, 4, 14};
    case 'J':
        return {7, 2, 2, 2, 18, 18, 12};
    case 'K':
        return {17, 18, 20, 24, 20, 18, 17};
    case 'L':
        return {16, 16, 16, 16, 16, 16, 31};
    case 'M':
        return {17, 27, 21, 21, 17, 17, 17};
    case 'N':
        return {17, 25, 21, 19, 17, 17, 17};
    case 'O':
        return {14, 17, 17, 17, 17, 17, 14};
    case 'P':
        return {30, 17, 17, 30, 16, 16, 16};
    case 'Q':
        return {14, 17, 17, 17, 21, 18, 13};
    case 'R':
        return {30, 17, 17, 30, 20, 18, 17};
    case 'S':
        return {15, 16, 16, 14, 1, 1, 30};
    case 'T':
        return {31, 4, 4, 4, 4, 4, 4};
    case 'U':
        return {17, 17, 17, 17, 17, 17, 14};
    case 'V':
        return {17, 17, 17, 17, 17, 10, 4};
    case 'W':
        return {17, 17, 17, 21, 21, 21, 10};
    case 'X':
        return {17, 17, 10, 4, 10, 17, 17};
    case 'Y':
        return {17, 17, 10, 4, 4, 4, 4};
    case 'Z':
        return {31, 1, 2, 4, 8, 16, 31};
    case '0':
        return {14, 17, 19, 21, 25, 17, 14};
    case '1':
        return {4, 12, 4, 4, 4, 4, 14};
    case '2':
        return {14, 17, 1, 2, 4, 8, 31};
    case '3':
        return {30, 1, 1, 14, 1, 1, 30};
    case '4':
        return {2, 6, 10, 18, 31, 2, 2};
    case '5':
        return {31, 16, 16, 30, 1, 1, 30};
    case '6':
        return {14, 16, 16, 30, 17, 17, 14};
    case '7':
        return {31, 1, 2, 4, 8, 8, 8};
    case '8':
        return {14, 17, 17, 14, 17, 17, 14};
    case '9':
        return {14, 17, 17, 15, 1, 1, 14};
    case '-':
        return {0, 0, 0, 31, 0, 0, 0};
    case '.':
        return {0, 0, 0, 0, 0, 12, 12};
    case '%':
        return {25, 25, 2, 4, 8, 19, 19};
    default:
        return {};
    }
}
inline void text(Image &image, unsigned x, unsigned y, std::string_view value) {
    for (char c : value) {
        const auto rows = glyph(c);
        for (unsigned r = 0; r < 7; ++r)
            for (unsigned col = 0; col < 5; ++col)
                if (rows[r] & (1 << (4 - col)))
                    for (unsigned dy = 0; dy < 2; ++dy)
                        for (unsigned dx = 0; dx < 2; ++dx) {
                            const unsigned px = x + col * 2 + dx, py = y + r * 2 + dy;
                            if (px < image.width && py < image.height) {
                                const auto offset = (py * image.width + px) * 4;
                                image.rgba[offset] = image.rgba[offset + 1] =
                                    image.rgba[offset + 2] = 220;
                            }
                        }
        x += 12;
    }
}
struct PhoneDiagnostics {
    bool arcore = false, tracking = false, gyro = false;
    double pose_hz = 0, age_ms = 0, prediction_ms = 0, opacity = 1;
};
inline Image diagnostic_texture(const PhoneModel &model, const PhoneDiagnostics &d) {
    auto image = shell_texture(model);
    unsigned y = 44;
    auto line = [&](const std::string &value) {
        text(image, 20, y, value);
        y += 32;
    };
    auto number = [](double value) {
        std::ostringstream out;
        out << std::fixed << std::setprecision(0) << std::clamp(value, 0., 9999.);
        return out.str();
    };
    line("FRAMEPHONE");
    y += 16;
    line(d.tracking ? (d.arcore ? "ARCORE LIVE" : "OPTICAL LIVE") : "TRACKING LOST");
    line("POSE " + number(d.pose_hz) + " HZ");
    line("AGE " + number(d.age_ms) + " MS");
    line("PRED " + number(d.prediction_ms) + " MS");
    line(d.gyro ? "GYRO ON" : "GYRO HOLD");
    line("VISIBLE " + number(d.opacity * 100) + " %");
    y += 16;
    line(number(model.screen.width * 1000) + " X " + number(model.screen.height * 1000) + " MM");
    return image;
}
} // namespace framephone::surface
