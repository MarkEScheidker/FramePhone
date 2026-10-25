"""Prove the entire camera directory can be copied without the FramePhone tree."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

source = Path(__file__).resolve().parents[1]
cmake = os.environ.get("CMAKE_COMMAND", "cmake")
ctest = os.environ.get("CTEST_COMMAND", "ctest")


def run(*command):
    subprocess.run(command, check=True)


with tempfile.TemporaryDirectory(prefix="framephone-camera-module-") as directory:
    root = Path(directory)
    copied = root / "camera"
    shutil.copytree(source, copied, ignore=shutil.ignore_patterns("build", "__pycache__", ".git"))
    build = root / "standalone"
    run(cmake, "-S", str(copied), "-B", str(build), "-DBUILD_TESTING=ON",
        "-DFRAMEPHONE_CAMERA_BUILD_BROKER=ON", "-DFRAMEPHONE_CAMERA_STATIC_BROKER=ON",
        "-DCMAKE_INSTALL_PREFIX=" + str(root / "install"))
    run(cmake, "--build", str(build), "--parallel", "2")
    run(ctest, "--test-dir", str(build), "--output-on-failure")
    run(cmake, "--install", str(build))
    assert (root / "install/include/framephone/frametop_ring.hpp").is_file()
    assert (root / "install/lib/libframephone_camera.a").is_file()
    assert (root / "install/share/framephone/modules/camera/broker/LICENSE.Frametop").is_file()
    consumer = root / "consumer"
    consumer.mkdir()
    # Compile from a sibling project. No FramePhone source/include directories
    # or image-processing dependencies are available through this copied tree.
    (consumer / "CMakeLists.txt").write_text("""
cmake_minimum_required(VERSION 3.20)
project(camera_consumer LANGUAGES CXX)
set(BUILD_TESTING OFF)
add_subdirectory("../camera" camera)
add_executable(consumer main.cpp)
target_link_libraries(consumer PRIVATE FramePhone::Camera)
""")
    (consumer / "main.cpp").write_text("""
#include <framephone/frametop_ring.hpp>
int main() {
    framephone::CameraFrame image;
    image.camera_id = "example";
    image.width = image.height = image.stride_bytes = 1;
    image.capture_time_ns = 1;
    image.clock_domain = "example-clock";
    image.calibration_id = "example-calibration";
    image.pixels = {42};
    image.validate();
    return image.pixels[0] == 42 ? 0 : 1;
}
""")
    run(cmake, "-S", str(consumer), "-B", str(root / "consumer-build"))
    run(cmake, "--build", str(root / "consumer-build"), "--parallel", "2")
    run(str(root / "consumer-build/consumer"))
print("Copied camera module builds, tests, installs and links into an independent project.")
