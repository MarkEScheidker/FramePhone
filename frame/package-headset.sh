#!/usr/bin/env bash
# Source handoff using the same reviewed file selection as the public export.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ "$#" -gt 0 ]; then
    echo "Usage: bash frame/package-headset.sh" >&2
    exit 2
fi
archive="$root/build/dist/framephone-headset-src.tar.gz"
python3 "$root/../scripts/package-source.py" --output "$archive"
echo "Extract on the headset, then follow frame/docs/HEADSET_TEST.md."
