#!/usr/bin/env bash
choose_engine() {
    engine=${FRAMEPHONE_CONTAINER_ENGINE:-}
    if [ -z "$engine" ]; then
        if command -v podman >/dev/null 2>&1; then engine=podman
        elif command -v docker >/dev/null 2>&1; then engine=docker
        fi
    fi
    case "$engine" in
        podman|docker) command -v "$engine" >/dev/null 2>&1 && return 0 ;;
    esac
    echo "Install Podman or Docker, then retry. See frame/docs/BUILD.md." >&2
    return 1
}
