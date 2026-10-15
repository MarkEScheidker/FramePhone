CXX ?= c++
CXXFLAGS ?= -std=c++20 -O2 -Wall -Wextra -Wpedantic
BUILD_DIR ?= build/portable
SOURCES = src/camera_source.cpp src/frametop_ring.cpp
HEADERS = include/framephone/camera_source.hpp include/framephone/frametop_ring.hpp
.PHONY: all test clean
all: $(BUILD_DIR)/camera-tests $(BUILD_DIR)/ring-tests
$(BUILD_DIR):
	mkdir -p "$@"
$(BUILD_DIR)/camera-tests: tests/test_camera_source.cpp $(SOURCES) $(HEADERS) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -Iinclude $< $(SOURCES) -o "$@"
$(BUILD_DIR)/ring-tests: tests/test_frametop_ring.cpp $(SOURCES) $(HEADERS) | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -Iinclude $< $(SOURCES) -o "$@"
test: all
	"$(BUILD_DIR)/camera-tests"
	"$(BUILD_DIR)/ring-tests"
clean:
	rm -rf "$(BUILD_DIR)"
