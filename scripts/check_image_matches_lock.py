#!/usr/bin/env python3
"""Check that a built image holds exactly the runtime packages uv.lock pins (W68, ADR-0164).

Compares ``uv export --frozen --no-dev --no-emit-project --no-hashes`` (markers
evaluated for the Linux CPython 3.12 image, not for the machine running this)
with the distributions the image's ``/opt/venv/bin/python`` can see.

Exit codes:
  0  same packages at the same versions
  1  a package is missing, extra or at another version; each is printed
  2  refusing: either side lists nothing (no image, a failed export)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any

from packaging.markers import Marker

Run = Callable[..., Any]

EXPORT = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes"]

#: The image: python:3.12-slim (Debian, CPython). Every marker variable is set,
#: so nothing falls back to the machine running the check.
IMAGE_ENV: dict[str, str] = {
    "sys_platform": "linux",
    "platform_system": "Linux",
    "os_name": "posix",
    "platform_machine": "x86_64",
    "platform_release": "",
    "platform_version": "",
    "python_version": "3.12",
    "python_full_version": "3.12.0",
    "implementation_name": "cpython",
    "implementation_version": "3.12.0",
    "platform_python_implementation": "CPython",
}

#: Installer tooling a base image may carry; not runtime libraries.
TOOLING = {"pip", "setuptools", "wheel"}

#: Run inside the image: one ``name==version`` line per installed distribution.
LISTING = (
    "import importlib.metadata as m\n"
    "for d in m.distributions():\n"
    "    print(f\"{d.metadata['Name']}=={d.version}\")\n"
)


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(text: str, env: dict[str, str] | None = None) -> dict[str, str]:
    """``{normalized name: version}`` for each pinned line whose marker holds in ``env``."""
    pins: dict[str, str] = {}
    for line in text.splitlines():
        requirement, _, marker = line.partition(";")
        requirement = requirement.strip()
        if not requirement or requirement.startswith(("#", "-")) or "==" not in requirement:
            continue
        if marker.strip() and not Marker(marker.strip()).evaluate(env or IMAGE_ENV):
            continue
        name, _, version = requirement.partition("==")
        pins[_normalize(name.strip())] = version.strip()
    return pins


def compare(locked: dict[str, str], installed: dict[str, str]) -> list[str]:
    """One line per missing, extra or different-version package."""
    diffs = []
    for name in sorted(locked.keys() | installed.keys()):
        if name not in installed:
            diffs.append(f"missing from the image: {name}=={locked[name]}")
        elif name not in locked:
            if name not in TOOLING:
                diffs.append(f"in the image but not in uv.lock: {name}=={installed[name]}")
        elif locked[name] != installed[name]:
            diffs.append(f"{name}: uv.lock pins {locked[name]}, the image has {installed[name]}")
    return diffs


def main(argv: Sequence[str] | None = None, run: Run = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", default="quorum-ai:local")
    image = parser.parse_args(argv).image

    export = run(EXPORT, capture_output=True, text=True, check=False)
    listing = run(
        [
            *["docker", "run", "--rm", "--pull", "never"],
            *["--entrypoint", "/opt/venv/bin/python", image, "-c", LISTING],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    locked = parse_pins(export.stdout) if export.returncode == 0 else {}
    installed = parse_pins(listing.stdout) if listing.returncode == 0 else {}
    print(f"image-lock-check: locked {len(locked)}, installed {len(installed)}")
    if not locked or not installed:
        print(
            "image-lock-check: refusing: nothing to compare "
            f"(uv export exited {export.returncode}, docker run exited {listing.returncode})\n"
            f"{export.stderr}{listing.stderr}",
            file=sys.stderr,
        )
        return 2
    diffs = compare(locked, installed)
    for line in diffs:
        print(f"image-lock-check: {line}")
    if diffs:
        print(f"image-lock-check: {len(diffs)} differences between {image} and uv.lock")
        return 1
    print(f"image-lock-check: {image} matches uv.lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
