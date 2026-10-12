CXX ?= c++
CXXFLAGS ?= -std=c++20 -O2 -Wall -Wextra -Wpedantic
INCLUDES = -Iinclude
CAMERA_SOURCES = src/camera_source.cpp src/frametop_ring.cpp
BUILD_DIR ?= build/portable

.PHONY: all test clean
all: $(BUILD_DIR)/framephone-frame $(BUILD_DIR)/framephone-diagnostic

$(BUILD_DIR):
	mkdir -p "$@"

$(BUILD_DIR)/framephone-frame: src/tracker_main.cpp src/camera_source.cpp include/framephone/camera_source.hpp include/framephone/apriltag_detector.hpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(INCLUDES) src/tracker_main.cpp src/camera_source.cpp -o "$@"

$(BUILD_DIR)/framephone-camera-tests: tests/test_camera_source.cpp src/camera_source.cpp include/framephone/camera_source.hpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(INCLUDES) tests/test_camera_source.cpp src/camera_source.cpp -o "$@"

$(BUILD_DIR)/framephone-diagnostic: src/diagnostic_main.cpp src/diagnostic.cpp $(CAMERA_SOURCES) include/framephone/diagnostic.hpp include/framephone/camera_source.hpp include/framephone/apriltag_detector.hpp include/framephone/frametop_ring.hpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(INCLUDES) src/diagnostic_main.cpp src/diagnostic.cpp $(CAMERA_SOURCES) -o "$@"

$(BUILD_DIR)/framephone-diagnostic-tests: tests/test_diagnostic.cpp src/diagnostic.cpp src/camera_source.cpp include/framephone/diagnostic.hpp include/framephone/camera_source.hpp include/framephone/apriltag_detector.hpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(INCLUDES) tests/test_diagnostic.cpp src/diagnostic.cpp src/camera_source.cpp -o "$@"

$(BUILD_DIR)/framephone-ring-tests: tests/test_frametop_ring.cpp $(CAMERA_SOURCES) include/framephone/frametop_ring.hpp include/framephone/camera_source.hpp | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(INCLUDES) tests/test_frametop_ring.cpp $(CAMERA_SOURCES) -o "$@"

test: $(BUILD_DIR)/framephone-camera-tests $(BUILD_DIR)/framephone-diagnostic-tests $(BUILD_DIR)/framephone-ring-tests all
	"$(BUILD_DIR)/framephone-camera-tests"
	"$(BUILD_DIR)/framephone-diagnostic-tests"
	"$(BUILD_DIR)/framephone-ring-tests"
	python3 tests/test_diagnostic_cli.py "$(BUILD_DIR)/framephone-diagnostic" "$(BUILD_DIR)/framephone-frame"

clean:
	rm -rf "$(BUILD_DIR)"
