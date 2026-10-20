#include "photo_worker.hpp"
#include <arpa/inet.h>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <fcntl.h>
#include <filesystem>
#include <poll.h>
#include <stdexcept>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>

namespace framephone {
namespace {
std::string environment(const char *name, std::string fallback = {}) {
    const auto *value = std::getenv(name);
    return value && *value ? value : std::move(fallback);
}
} // namespace
PhotoWorker::PhotoWorker(std::function<bool()> cancelled) : cancelled_(std::move(cancelled)) {
    std::filesystem::path source = FRAMEPHONE_DESKTOP_DIR;
    auto root = environment("FRAMEPHONE_RUNTIME_ROOT");
    std::filesystem::path desktop =
        root.empty() ? source : std::filesystem::path(root) / "opt/framephone/desktop";
    auto script = environment("FRAMEPHONE_PHOTO_WORKER", (desktop / "learned_worker.py").string());
    auto models = environment(
        "FRAMEPHONE_PHOTO_MODELS",
        root.empty()
            ? (source.parent_path() / "build/models/xfeat").string()
            : (std::filesystem::path(root) / "opt/framephone/share/framephone/xfeat").string());
    std::vector<std::string> args;
    if (!root.empty()) {
        auto loader = environment("FRAMEPHONE_LOADER"),
             libraries = environment("FRAMEPHONE_LIBRARY_PATH");
        if (loader.empty() || libraries.empty())
            throw std::runtime_error("missing packaged Python loader configuration");
        args = {loader, "--library-path", libraries, root + "/usr/bin/python3"};
    } else
        args = {environment("FRAMEPHONE_PYTHON", "python3")};
    args.insert(args.end(), {script, "--models", models});
    std::vector<char *> argv;
    for (auto &arg : args)
        argv.push_back(arg.data());
    argv.push_back(nullptr);
    int to_child[2], from_child[2];
    if (pipe2(to_child, O_CLOEXEC) != 0)
        throw std::runtime_error("cannot create photo worker input pipe");
    if (pipe2(from_child, O_CLOEXEC) != 0) {
        close(to_child[0]);
        close(to_child[1]);
        throw std::runtime_error("cannot create photo worker output pipe");
    }
    auto parent = getpid();
    pid_ = fork();
    if (pid_ == 0) {
        prctl(PR_SET_PDEATHSIG, SIGTERM);
        if (getppid() != parent)
            _exit(1);
        dup2(to_child[0], STDIN_FILENO);
        dup2(from_child[1], STDOUT_FILENO);
        close(to_child[0]);
        close(to_child[1]);
        close(from_child[0]);
        close(from_child[1]);
        execvp(argv[0], argv.data());
        _exit(127);
    }
    close(to_child[0]);
    close(from_child[1]);
    if (pid_ < 0) {
        close(to_child[1]);
        close(from_child[0]);
        throw std::runtime_error("cannot start learned photo worker");
    }
    input_ = to_child[1];
    output_ = from_child[0];
    std::signal(SIGPIPE, SIG_IGN);
    if (fcntl(input_, F_SETFL, O_NONBLOCK) < 0 || fcntl(output_, F_SETFL, O_NONBLOCK) < 0) {
        shutdown();
        throw std::runtime_error("cannot configure learned photo worker pipes");
    }
}
PhotoWorker::~PhotoWorker() {
    shutdown();
}
void PhotoWorker::shutdown() {
    if (input_ >= 0) {
        close(input_);
        input_ = -1;
    }
    if (output_ >= 0) {
        close(output_);
        output_ = -1;
    }
    if (pid_ <= 0)
        return;
    kill(pid_, SIGTERM);
    for (int i = 0; i < 50; ++i) {
        auto status = waitpid(pid_, nullptr, WNOHANG);
        if (status == pid_ || (status < 0 && errno == ECHILD)) {
            pid_ = -1;
            return;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    kill(pid_, SIGKILL);
    while (waitpid(pid_, nullptr, 0) < 0 && errno == EINTR) {
    }
    pid_ = -1;
}
nlohmann::json PhotoWorker::exchange(const nlohmann::json &header,
                                     const std::vector<std::vector<std::uint8_t>> &payload) {
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(120);
    auto transfer = [&](int fd, void *buffer, std::size_t bytes, bool writing) {
        auto *cursor = static_cast<std::uint8_t *>(buffer);
        while (bytes) {
            if ((cancelled_ && cancelled_()) || std::chrono::steady_clock::now() >= deadline)
                throw std::runtime_error("learned photo worker cancelled or timed out");
            pollfd descriptor{fd, short(writing ? POLLOUT : POLLIN), 0};
            auto ready = poll(&descriptor, 1, 100);
            if (ready < 0 && errno == EINTR)
                continue;
            if (ready < 0)
                throw std::runtime_error("learned photo worker poll failed");
            if (!ready)
                continue;
            auto count = writing ? write(fd, cursor, bytes) : read(fd, cursor, bytes);
            if (count < 0 && (errno == EINTR || errno == EAGAIN))
                continue;
            if (count <= 0)
                throw std::runtime_error(
                    "learned photo worker exited; see model/dependency error above");
            cursor += count;
            bytes -= std::size_t(count);
        }
    };
    auto encoded = header.dump();
    if (encoded.size() > 65536)
        throw std::runtime_error("photo worker header too large");
    std::uint32_t size = htonl(std::uint32_t(encoded.size()));
    transfer(input_, &size, sizeof(size), true);
    transfer(input_, encoded.data(), encoded.size(), true);
    for (const auto &part : payload)
        transfer(input_, const_cast<std::uint8_t *>(part.data()), part.size(), true);
    transfer(output_, &size, sizeof(size), false);
    size = ntohl(size);
    if (!size || size > 2 * 1024 * 1024)
        throw std::runtime_error("invalid learned photo worker reply size");
    encoded.resize(size);
    transfer(output_, encoded.data(), encoded.size(), false);
    auto reply = nlohmann::json::parse(encoded);
    if (reply.value("op", "") == "error")
        throw std::runtime_error("learned photo worker: " + reply.value("error", "unknown error"));
    return reply;
}
} // namespace framephone
