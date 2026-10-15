#include "framephone/frametop_ring.hpp"
#include "framephone/stereo.hpp"
#include <iostream>
#include <set>

int main(int argc, char **argv) {
    using namespace framephone;
    try {
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout << "FramePhone camera discovery\n"
                         "  --list-ring FILE\n"
                         "  --list-cameras --calibration-id ID [--factory-root ROOT]\n";
            return 0;
        }
        if (argc == 3 && std::string(argv[1]) == "--list-ring") {
            for (const auto &c : list_frametop_cameras(argv[2]))
                std::cout << c.name << " sensor=" << c.sensor << " video" << c.node << ' '
                          << c.width << 'x' << c.height << " flags=" << c.flags << '\n';
            return 0;
        }
        bool list = false;
        std::string id;
        std::filesystem::path root{"/"};
        std::set<std::string> seen;
        for (int i = 1; i < argc; ++i) {
            const std::string key = argv[i];
            if (!seen.insert(key).second)
                throw std::invalid_argument("duplicate option");
            if (key == "--list-cameras")
                list = true;
            else if ((key == "--factory-root" || key == "--calibration-id") && i + 1 < argc) {
                if (key == "--factory-root")
                    root = argv[++i];
                else
                    id = argv[++i];
            } else
                throw std::invalid_argument("unknown or incomplete option: " + key);
        }
        if (!list || id.empty())
            throw std::invalid_argument("use --list-cameras with --calibration-id; see --help");
        for (const auto &[name, c] : load_frametop_calibration(root, id)) {
            std::cout << name << ' ' << c.calibration.width << 'x' << c.calibration.height
                      << " KB4 origin_H_m=";
            for (auto x : c.origin_m)
                std::cout << x << ' ';
            std::cout << '\n';
        }
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "framephone-camera: " << e.what() << '\n';
        return 1;
    }
}
