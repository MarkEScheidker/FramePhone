#!/usr/bin/env bash
# Compatibility entry point. Desktop and headset builds now use the same package.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec bash "$root/build.sh" "$@"
