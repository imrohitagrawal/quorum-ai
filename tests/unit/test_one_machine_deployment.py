"""W87-3 (ADR-0176): the operator command ends sessions on ONE machine's
volume, and every app process there reads the same file. That holds only
while production runs one worker on one machine with one volume, so both
are pinned here. Neither was pinned by any test before W87-3 (grep).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

#: The Dockerfile and fly.toml beside this tree's tests (a copy reads its own).
ROOT = Path(__file__).resolve().parents[2]


def _cmd_args() -> list[str]:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^CMD\s*\[(.*?)\]", text, re.DOTALL | re.MULTILINE)
    assert match, "the Dockerfile declares a CMD"
    return re.findall(r'"([^"]*)"', match.group(1).replace("\\\n", " "))


def test_the_image_runs_exactly_one_worker() -> None:
    """Red when: the CMD's ``--workers`` is changed from ``1`` or removed.
    Partner: the CMD starts uvicorn on ``product_app.main:app``."""
    args = _cmd_args()
    assert args[:2] == ["uvicorn", "product_app.main:app"], args
    assert args.count("--workers") == 1
    assert args[args.index("--workers") + 1] == "1"


def test_fly_mounts_exactly_one_volume() -> None:
    """Red when: ``fly.toml`` gains a second ``[[mounts]]`` or loses the one
    (sessions would then live on a volume the command does not reach).
    Partner: the one mount is at ``/data``, where ``SESSION_DB_PATH``
    points."""
    config = tomllib.loads((ROOT / "fly.toml").read_text(encoding="utf-8"))
    mounts = config.get("mounts")
    assert isinstance(mounts, list) and len(mounts) == 1, mounts
    assert mounts[0]["destination"] == "/data"
    assert config["env"]["SESSION_DB_PATH"].startswith("/data/")
