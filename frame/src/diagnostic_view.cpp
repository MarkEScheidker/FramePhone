#include "framephone/diagnostic_view.hpp"

#include <SDL.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace framephone {
namespace {
constexpr int kWidth = 1120;
constexpr int kHeight = 720;
constexpr SDL_Color kText{220, 229, 239, 255};
constexpr SDL_Color kMuted{139, 157, 179, 255};
constexpr SDL_Color kGreen{70, 237, 157, 255};
constexpr SDL_Color kAmber{255, 197, 92, 255};

void check(int result, const char *operation) {
    if (result < 0)
        throw std::runtime_error(std::string(operation) + ": " + SDL_GetError());
}

// Small built-in bitmap alphabet keeps the diagnostic independent of font files.
std::array<unsigned char, 7> glyph(char ch) {
    switch (ch) {
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
        return {17, 25, 25, 21, 19, 19, 17};
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
    case '.':
        return {0, 0, 0, 0, 0, 6, 6};
    case ':':
        return {0, 6, 6, 0, 6, 6, 0};
    case '/':
        return {1, 2, 2, 4, 8, 8, 16};
    case '%':
        return {17, 2, 4, 4, 8, 16, 17};
    case '-':
        return {0, 0, 0, 31, 0, 0, 0};
    case '_':
        return {0, 0, 0, 0, 0, 0, 31};
    case '=':
        return {0, 0, 31, 0, 31, 0, 0};
    case ' ':
        return {};
    default:
        return {14, 17, 1, 2, 4, 0, 4};
    }
}

void text(SDL_Renderer *renderer, int x, int y, std::string_view value, SDL_Color color = kText,
          int scale = 2) {
    SDL_SetRenderDrawColor(renderer, color.r, color.g, color.b, color.a);
    for (char ch : value) {
        if (ch >= 'a' && ch <= 'z')
            ch = static_cast<char>(ch - 'a' + 'A');
        const auto rows = glyph(ch);
        for (int row = 0; row < 7; ++row)
            for (int col = 0; col < 5; ++col)
                if ((rows[static_cast<std::size_t>(row)] & (1 << (4 - col))) != 0) {
                    SDL_Rect pixel{x + col * scale, y + row * scale, scale, scale};
                    SDL_RenderFillRect(renderer, &pixel);
                }
        x += 6 * scale;
    }
}

std::string number(double value) {
    std::ostringstream output;
    output << std::fixed << std::setprecision(2) << value;
    return output.str();
}
} // namespace

struct DiagnosticView::Impl {
    bool initialized{};
    SDL_Window *window{};
    SDL_Renderer *renderer{};
    SDL_Texture *texture{};
    std::uint32_t width{}, height{};
    std::vector<std::uint32_t> rgba;
    std::string snapshot;
    ~Impl() {
        if (texture)
            SDL_DestroyTexture(texture);
        if (renderer)
            SDL_DestroyRenderer(renderer);
        if (window)
            SDL_DestroyWindow(window);
        if (initialized)
            SDL_Quit();
    }
};

DiagnosticView::DiagnosticView() : impl_(std::make_unique<Impl>()) {
    check(SDL_Init(SDL_INIT_VIDEO), "SDL video initialization");
    impl_->initialized = true;
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "0");
    impl_->window = SDL_CreateWindow("FramePhone - fiducial diagnostic", SDL_WINDOWPOS_CENTERED,
                                     SDL_WINDOWPOS_CENTERED, kWidth, kHeight,
                                     SDL_WINDOW_RESIZABLE | SDL_WINDOW_ALLOW_HIGHDPI);
    if (!impl_->window)
        throw std::runtime_error(SDL_GetError());
    impl_->renderer = SDL_CreateRenderer(impl_->window, -1, SDL_RENDERER_ACCELERATED);
    if (!impl_->renderer)
        impl_->renderer = SDL_CreateRenderer(impl_->window, -1, SDL_RENDERER_SOFTWARE);
    if (!impl_->renderer)
        throw std::runtime_error(SDL_GetError());
    check(SDL_RenderSetLogicalSize(impl_->renderer, kWidth, kHeight), "SDL logical size");
}
DiagnosticView::~DiagnosticView() = default;

ViewCommands DiagnosticView::poll() {
    ViewCommands commands;
    SDL_Event event;
    while (SDL_PollEvent(&event)) {
        if (event.type == SDL_QUIT)
            commands.quit = true;
        if (event.type == SDL_WINDOWEVENT)
            commands.redraw = true;
        if (event.type != SDL_KEYDOWN || event.key.repeat)
            continue;
        switch (event.key.keysym.sym) {
        case SDLK_ESCAPE:
        case SDLK_q:
            commands.quit = true;
            break;
        case SDLK_SPACE:
            commands.toggle_pause = true;
            break;
        case SDLK_RIGHT:
            commands.step = true;
            break;
        case SDLK_r:
            commands.restart = true;
            break;
        default:
            break;
        }
    }
    return commands;
}

void DiagnosticView::show(const CameraFrame &frame, const DetectionBatch &batch,
                          const CameraDiagnostics &stats, bool detection_enabled,
                          const std::string &source_label, bool paused, bool ended,
                          double processing_ms, const std::string &pose_summary) {
    auto *renderer = impl_->renderer;
    if (impl_->width != frame.width || impl_->height != frame.height) {
        if (impl_->texture)
            SDL_DestroyTexture(impl_->texture);
        impl_->texture =
            SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING,
                              static_cast<int>(frame.width), static_cast<int>(frame.height));
        if (!impl_->texture)
            throw std::runtime_error(SDL_GetError());
        impl_->width = frame.width;
        impl_->height = frame.height;
        impl_->rgba.resize(static_cast<std::size_t>(frame.width) * frame.height);
    }
    for (std::uint32_t y = 0; y < frame.height; ++y)
        for (std::uint32_t x = 0; x < frame.width; ++x) {
            const auto gray = frame.pixels[static_cast<std::size_t>(y) * frame.stride_bytes + x];
            impl_->rgba[static_cast<std::size_t>(y) * frame.width + x] =
                0xff000000U | static_cast<std::uint32_t>(gray) * 0x010101U;
        }
    check(SDL_UpdateTexture(impl_->texture, nullptr, impl_->rgba.data(),
                            static_cast<int>(frame.width * 4)),
          "SDL texture update");
    SDL_SetRenderDrawColor(renderer, 15, 22, 33, 255);
    SDL_RenderClear(renderer);
    text(renderer, 24, 24, "FRAMEPHONE / FIDUCIAL DIAGNOSTIC", kText, 3);
    text(renderer, 24, 62, source_label, kAmber);

    const double scale = std::min(720.0 / frame.width, 540.0 / frame.height);
    SDL_Rect image{24 + (720 - static_cast<int>(frame.width * scale)) / 2,
                   96 + (540 - static_cast<int>(frame.height * scale)) / 2,
                   static_cast<int>(frame.width * scale), static_cast<int>(frame.height * scale)};
    check(SDL_RenderCopy(renderer, impl_->texture, nullptr, &image), "SDL image render");
    // Use actual destination dimensions after integer rounding to keep corners aligned.
    const auto mapped = [&](const ImagePoint &point) {
        return SDL_Point{image.x + static_cast<int>(std::lround(point.x * image.w / frame.width)),
                         image.y + static_cast<int>(std::lround(point.y * image.h / frame.height))};
    };
    SDL_RenderSetClipRect(renderer, &image);
    for (const auto &tag : batch.detections) {
        std::array<SDL_Point, 5> points{};
        int left = image.x + image.w, top = image.y + image.h;
        for (std::size_t i = 0; i < 4; ++i) {
            points[i] = mapped(tag.corners[i]);
            left = std::min(left, points[i].x);
            top = std::min(top, points[i].y);
        }
        points[4] = points[0];
        SDL_SetRenderDrawColor(renderer, kGreen.r, kGreen.g, kGreen.b, 255);
        SDL_RenderDrawLines(renderer, points.data(), static_cast<int>(points.size()));
        SDL_SetRenderDrawColor(renderer, kAmber.r, kAmber.g, kAmber.b, 255);
        SDL_Rect corner{points[0].x - 3, points[0].y - 3, 7, 7};
        SDL_RenderFillRect(renderer, &corner);
        // Put the ID above the tag so the label does not cover its payload.
        SDL_Rect label{left, std::max(image.y, top - 21), 20, 18};
        SDL_SetRenderDrawColor(renderer, 15, 22, 33, 255);
        SDL_RenderFillRect(renderer, &label);
        text(renderer, label.x + 4, label.y + 2, std::to_string(tag.id), kGreen);
    }
    SDL_RenderSetClipRect(renderer, nullptr);

    const std::string status = !detection_enabled         ? "PREVIEW ONLY / NO DETECTOR"
                               : batch.detections.empty() ? "NO TAGS DETECTED"
                                                          : "TAGS VISIBLE";
    text(renderer, 768, 100, status,
         detection_enabled && !batch.detections.empty() ? kGreen : kAmber);
    int y = 140;
    const auto row = [&](const std::string &value) {
        text(renderer, 768, y, value);
        y += 27;
    };
    row("CAM " + frame.camera_id.substr(0, 22));
    row(std::to_string(frame.width) + " X " + std::to_string(frame.height) + " GRAY8");
    row("FRAMES " + std::to_string(stats.frames));
    row(detection_enabled ? "WITH TAGS " + std::to_string(stats.frames_with_tags)
                          : "WITH TAGS N/A");
    row(detection_enabled ? "COVERAGE " +
                                number(100.0 * static_cast<double>(stats.frames_with_tags) /
                                       static_cast<double>(stats.frames)) +
                                "%"
                          : "COVERAGE N/A");
    row(detection_enabled ? "MISSING " + std::to_string(stats.missing_streak) : "MISSING N/A");
    row(detection_enabled ? "REACQUIRED " + std::to_string(stats.reacquisitions)
                          : "REACQUIRED N/A");
    row(detection_enabled
            ? "DETECT MS " +
                  number(std::chrono::duration<double, std::milli>(batch.detection_time).count())
            : "DETECT MS N/A");
    row("PROCESS MS " + number(processing_ms));
    row("WORK FPS " + number(processing_ms > 0 ? 1000.0 / processing_ms : 0));
    std::string ids = "IDS";
    for (const auto id : stats.current_ids)
        ids += " " + std::to_string(id);
    row(ids);
    row("NS " + std::to_string(frame.capture_time_ns));
    text(renderer, 768, 485, pose_summary.empty() ? "IMAGE-SPACE DETECTION ONLY" : pose_summary,
         kMuted);
    text(renderer, 768, 512, "YELLOW = CANONICAL CORNER 0", kMuted);
    text(renderer, 768, 550, ended ? "END / R TO REPLAY" : paused ? "PAUSED" : "PLAYING", kAmber);
    if (!batch.detections.empty()) {
        const auto weakest = std::min_element(
            batch.detections.begin(), batch.detections.end(),
            [](const auto &a, const auto &b) { return a.decision_margin < b.decision_margin; });
        text(renderer, 768, 588, "MIN MARGIN " + number(weakest->decision_margin), kMuted);
    }
    text(renderer, 24, 662, "SPACE PAUSE   RIGHT STEP   R RESTART   ESC QUIT", kText);
    text(renderer, 24, 689,
         "COVERAGE = FRAMES WITH ANY TAG / ALL PROCESSED FRAMES IN THIS CAMERA CLOCK", kMuted);
    // Read the backbuffer before presenting: its contents after Present are undefined.
    if (!impl_->snapshot.empty()) {
        int width{}, height{};
        check(SDL_GetRendererOutputSize(renderer, &width, &height), "SDL output size");
        auto *surface =
            SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, SDL_PIXELFORMAT_ARGB8888);
        if (!surface)
            throw std::runtime_error(SDL_GetError());
        const std::unique_ptr<SDL_Surface, decltype(&SDL_FreeSurface)> owner(surface,
                                                                             SDL_FreeSurface);
        check(SDL_RenderReadPixels(renderer, nullptr, surface->format->format, surface->pixels,
                                   surface->pitch),
              "SDL snapshot read");
        check(SDL_SaveBMP(surface, impl_->snapshot.c_str()), "SDL snapshot save");
        impl_->snapshot.clear();
    }
    SDL_RenderPresent(renderer);
}

void DiagnosticView::save_snapshot(const std::string &path) {
    impl_->snapshot = path;
}

} // namespace framephone
