#pragma once
#include <cmath>
#include <filesystem>
#include <fstream>
#include <nlohmann/json.hpp>
#include <set>

namespace framephone::calibration_json {
using Json = nlohmann::json;
inline void require(bool condition, const std::string &reason) {
    if (!condition)
        throw std::invalid_argument(reason);
}
inline Json read_json(const std::filesystem::path &path) {
    require(std::filesystem::file_size(path) <= 4 * 1024 * 1024,
            "calibration/layout JSON exceeds 4 MiB");
    std::ifstream stream(path);
    require(bool(stream), "cannot read JSON: " + path.string());
    // Reject duplicate keys rather than silently accepting the last calibration.
    std::vector<std::set<std::string>> keys;
    auto callback = [&](int, Json::parse_event_t event, Json &value) {
        if (event == Json::parse_event_t::object_start)
            keys.emplace_back();
        if (event == Json::parse_event_t::key)
            require(keys.back().insert(value.get<std::string>()).second, "duplicate JSON key");
        if (event == Json::parse_event_t::object_end)
            keys.pop_back();
        return true;
    };
    return Json::parse(stream, callback);
}
inline double number(const Json &v) {
    require(v.is_number(), "expected numeric calibration value");
    double result = v.get<double>();
    require(std::isfinite(result), "nonfinite calibration value");
    return result;
}
inline int integer(const Json &v, int min, int max) {
    require(v.is_number_integer(), "expected integer calibration value");
    const auto n = v.get<std::int64_t>();
    require(n >= min && n <= max, "calibration integer out of range");
    return static_cast<int>(n);
}
inline std::string string(const Json &v) {
    require(v.is_string(), "expected calibration string");
    auto s = v.get<std::string>();
    require(!s.empty() && s.size() <= 256, "empty or oversized calibration identity");
    return s;
}
inline void array(const Json &v, std::size_t n) {
    require(v.is_array() && v.size() == n, "incorrect calibration array length");
}
} // namespace framephone::calibration_json
