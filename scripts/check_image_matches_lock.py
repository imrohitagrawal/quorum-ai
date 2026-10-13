#!/usr/bin/env python3
"""Check that a built image holds exactly the runtime packages uv.lock pins (W68, ADR-0164).

Compares ``uv export --frozen --no-dev --no-emit-project --no-hashes`` (markers
evaluated for the Linux CPython 3.12 image, not for the machine running this)
with the distributions the image's ``/opt/venv/bin/python`` can see. The image's
listing is read verbatim, with no marker evaluation: every installed
distribution is importable, whatever its metadata says.

Exit codes:
  0  same packages at the same versions
  1  a package is missing, extra, at another version, or installed twice
     (two versions of one distribution: Python imports only one of them),
     or a line of the image's listing is not ``name==version``; each is
     printed
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
#: so nothing falls back to the machine running the check, and every value is
#: hard-coded rather than read from the image. Three of them are guesses that
#: change no locked marker today: ``platform_machine`` is x86_64 (``grep -c
#: platform_machine uv.lock`` is 0); ``platform_release`` and
#: ``platform_version`` are "" (``grep -c platform_release uv.lock`` and
#: ``grep -c platform_version uv.lock`` are both 0); and the patch level is
#: 3.12.0, where every ``python_full_version`` marker in uv.lock compares
#: against 3.13, 3.14 or 3.15, so 3.12.0 and any other 3.12 release give the
#: same answer.
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

#: Run inside the image: one ``name==version`` line per installed distribution.
LISTING = (
    "import importlib.metadata as m\n"
    "for d in m.distributions():\n"
    "    print(f\"{d.metadata['Name']}=={d.version}\")\n"
)


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_pairs(text: str, env: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """``(normalized name, version)`` for each pinned line whose marker holds in
    ``env`` (the image's by default), in order, duplicates kept."""
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        requirement, _, marker = line.partition(";")
        requirement = requirement.strip()
        if not requirement or requirement.startswith(("#", "-")) or "==" not in requirement:
            continue
        if marker.strip() and not Marker(marker.strip()).evaluate(env or IMAGE_ENV):
            continue
        name, _, version = requirement.partition("==")
        pairs.append((normalize(name.strip()), version.strip()))
    return pairs


#: A distribution name as PEP 508 allows it.
NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")


def installed_pairs(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Read the image's listing with no marker evaluation.

    Returns ``(normalized name, version)`` for each ``name==version`` line, in
    order, duplicates kept, where the version is everything after the first
    ``==``, verbatim (so ``9.9 ; os_name == "nt"`` is a version that matches no
    pin, not a marker that hides the package); and one difference line for each
    non-blank line that is not ``name==version``.
    """
    pairs: list[tuple[str, str]] = []
    unreadable: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        name, separator, version = line.strip().partition("==")
        if separator and version and NAME.fullmatch(name):
            pairs.append((normalize(name), version))
        else:
            unreadable.append(f"not a name==version line in the image's listing: {line!r}")
    return pairs, unreadable


def parse_pins(text: str, env: dict[str, str] | None = None) -> dict[str, str]:
    """``{normalized name: version}`` for each pinned line whose marker holds in ``env``."""
    return dict(pinned_pairs(text, env))


def duplicates(pairs: list[tuple[str, str]]) -> list[str]:
    """One line per name listed more than once, with every version it has."""
    versions: dict[str, list[str]] = {}
    for name, version in pairs:
        versions.setdefault(name, []).append(version)
    return [
        f"installed more than once: {name} ({', '.join(found)})"
        for name, found in sorted(versions.items())
        if len(found) > 1
    ]


def compare(locked: dict[str, str], installed: dict[str, str]) -> list[str]:
    """One line per missing, extra or different-version package."""
    diffs = []
    for name in sorted(locked.keys() | installed.keys()):
        if name not in installed:
            diffs.append(f"missing from the image: {name}=={locked[name]}")
        elif name not in locked:
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
    listed, unreadable = installed_pairs(listing.stdout) if listing.returncode == 0 else ([], [])
    installed = dict(listed)
    print(f"image-lock-check: locked {len(locked)}, installed {len(installed)}")
    if not locked or not installed:
        print(
            "image-lock-check: refusing: nothing to compare "
            f"(uv export exited {export.returncode}, docker run exited {listing.returncode})\n"
            f"{export.stderr}{listing.stderr}",
            file=sys.stderr,
        )
        return 2
    diffs = unreadable + duplicates(listed) + compare(locked, installed)
    for line in diffs:
        print(f"image-lock-check: {line}")
    if diffs:
        print(f"image-lock-check: {len(diffs)} differences between {image} and uv.lock")
        return 1
    print(f"image-lock-check: {image} matches uv.lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
