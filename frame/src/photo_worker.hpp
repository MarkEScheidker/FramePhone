#pragma once
#include <functional>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

namespace framephone {
// One persistent CPU worker. Only trusted local application paths are executed.
class PhotoWorker {
  public:
    explicit PhotoWorker(std::function<bool()> cancelled);
    ~PhotoWorker();
    PhotoWorker(const PhotoWorker &) = delete;
    PhotoWorker &operator=(const PhotoWorker &) = delete;
    nlohmann::json exchange(const nlohmann::json &, const std::vector<std::vector<std::uint8_t>> &);

  private:
    int pid_{-1}, input_{-1}, output_{-1};
    std::function<bool()> cancelled_;
    void shutdown();
};
} // namespace framephone
