"""
Pick and install the correct bpy wheel from https://download.blender.org/pypi/bpy/.

We don't go through PyPI because the PyPI bpy releases lag the Blender wheel index
(no cp313 on PyPI yet, but Blender hosts cp313 wheels for bpy 5.1.x).

Usage:
    python scripts/install_bpy.py            # install into the running interpreter's pip
    python scripts/install_bpy.py --print    # just print the resolved URL
    python scripts/install_bpy.py --version 5.1.1  # pin a version
"""

from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
import urllib.request

INDEX_URL = "https://download.blender.org/pypi/bpy/"
WHEEL_RE = re.compile(r'href="(bpy-[^"]+\.whl)"')


def detect_platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "win_arm64" if machine in ("arm64", "aarch64") else "win_amd64"
    if system == "darwin":
        return "macosx_11_0_arm64" if machine in ("arm64", "aarch64") else "macosx_11_0_x86_64"
    if system == "linux":
        if machine not in ("x86_64", "amd64"):
            raise SystemExit(f"no bpy wheels for Linux {machine}")
        return "manylinux_2_28_x86_64"
    raise SystemExit(f"unsupported platform: {system}")


def detect_python_tag() -> str:
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def fetch_index() -> list[str]:
    req = urllib.request.Request(INDEX_URL, headers={"User-Agent": "Mozilla/5.0 (bpy-installer)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", errors="replace")
    return WHEEL_RE.findall(body)


def parse_version(name: str) -> tuple[int, ...]:
    m = re.match(r"bpy-([0-9.]+(?:[a-z]\d*)?)-", name)
    if not m:
        return (0,)
    parts: list[int] = []
    for p in re.split(r"\.", m.group(1)):
        n = re.match(r"(\d+)", p)
        parts.append(int(n.group(1)) if n else 0)
    return tuple(parts)


def pick_wheel(wheels: list[str], py_tag: str, plat_tag: str, version: str | None) -> str:
    candidates = [
        w for w in wheels
        if f"-{py_tag}-{py_tag}-" in w and w.endswith(f"-{plat_tag}.whl")
    ]
    if version:
        candidates = [w for w in candidates if w.startswith(f"bpy-{version}-")]
    if not candidates:
        raise SystemExit(
            f"no bpy wheel for python {py_tag} on {plat_tag}"
            + (f" version {version}" if version else "")
            + ".\nSee https://download.blender.org/pypi/bpy/ for the available list."
        )
    candidates.sort(key=parse_version)
    return candidates[-1]


def main() -> int:
    p = argparse.ArgumentParser(description="Install bpy from Blender's wheel index.")
    p.add_argument("--print", action="store_true", help="Print the URL and exit")
    p.add_argument("--version", help="Pin to a specific bpy version (e.g. 5.1.1)")
    p.add_argument("--upgrade", action="store_true", help="Pass --upgrade to pip")
    args = p.parse_args()

    py_tag = detect_python_tag()
    plat_tag = detect_platform_tag()
    print(f"resolving bpy for {py_tag} / {plat_tag} ...")

    wheels = fetch_index()
    chosen = pick_wheel(wheels, py_tag, plat_tag, args.version)
    url = INDEX_URL + chosen
    print(f"selected: {chosen}")
    print(f"url: {url}")

    if args.print:
        return 0

    cmd = [sys.executable, "-m", "pip", "install"]
    if args.upgrade:
        cmd.append("--upgrade")
    cmd.append(url)
    print("running:", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
