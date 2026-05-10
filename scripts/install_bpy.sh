#!/usr/bin/env bash
# Install bpy from https://download.blender.org/pypi/bpy/ (not PyPI).
# Picks the wheel matching the venv's Python version + your CPU.
# Then runs render.py --help as a smoke test.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"

if [[ -x "$root/.venv/bin/python3" ]]; then
    py="$root/.venv/bin/python3"
elif [[ -x "$root/.venv/bin/python" ]]; then
    py="$root/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    py="$(command -v python3)"
else
    py="$(command -v python)"
fi

echo "Using Python: $py"
"$py" "$root/scripts/install_bpy.py" "$@"

echo
echo "Smoke test: render.py --help"
"$py" "$root/render.py" --help

echo
echo "bpy install finished. Try:"
echo "    $py scripts/make_test_model.py"
echo "    $py render.py test_model -o render.png -v"
