#!/usr/bin/env python3
"""
verify.py — portable documentation verifier for the doc-suite skills.

Runs a set of checkable rules over the documents you produced, BEFORE presenting them.
It enforces only checkable rules; clarity is still a human/critic judgement.

Usage:
    python3 verify.py <path-to-file-or-dir> [--format md|html]
                      [--skill NAME] [--profile docs/project-profile.md]
                      [--grade-target N] [--scope public|internal] [--license LICENSE]

Resolution order for grade target and scope (most specific wins):
    explicit CLI flag  >  profile value for --skill  >  built-in default.

The --skill name is matched to the profile keys grade_target_<stem> / scope_<stem>, where <stem>
is the skill name with hyphens turned into underscores (e.g. learning-track -> learning_track).
Legacy short stems (faq, architecture, runbook, onboarding) are still accepted.

Examples:
    python3 verify.py docs/learning --format md --skill learning-track --profile docs/project-profile.md
    python3 verify.py outputs/faq.html --format html --skill project-faq --profile docs/project-profile.md

Exit code is 0 if there are no FAIL findings (warnings are allowed), 1 otherwise.
Readability is computed in pure Python. The project profile is parsed with PyYAML when available;
if PyYAML is not installed the profile is skipped (with a notice) and built-in defaults are used.
"""
from __future__ import annotations
import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

try:
    import yaml  # PyYAML
    _HAVE_YAML = True
except Exception:  # pragma: no cover - environment-dependent
    _HAVE_YAML = False

# ---- Rule data -------------------------------------------------------------

BANNED_WORDS = [
    "leverage", "seamless", "robust", "delve", "supercharge", "unlock", "harness",
    "elevate", "cutting-edge", "game-changer", "effortless", "empower",
    "revolutionise", "revolutionize",
]

# Two tiers of internal-reference terms (checked only when --scope public).
#   ALWAYS-FAIL: unambiguous internal artifacts — filenames, acronyms, tool names.
#   REVIEW-WARN: ordinary English words that are *also* internal jargon; flagged for a
#                human to confirm they are used in their plain sense, never auto-failed.
ALWAYS_FAIL_INTERNAL = ["CLAUDE.md", "SKILL.md", "MAANG", "FAANG", "Claude Code", "Cowork"]
REVIEW_WARN_INTERNAL = ["backbone", "handoff"]

AUTHOR_INTENT_TERMS = [
    "hiring", "recruiter", "portfolio", "build-in-public", "build in public",
    "for employers", "land a job", "my career",
]

# Legacy short profile stems -> canonical (skill-name) stems. Keeps old profiles/flags working.
SKILL_KEY_ALIASES = {
    "faq": "project_faq",
    "architecture": "architecture_and_decisions",
    "runbook": "operations_runbook",
    "onboarding": "onboarding_companion",
}

# ---- Helpers ---------------------------------------------------------------

def strip_code_fences(text: str) -> str:
    """Remove fenced code blocks so prose-only checks don't trip on code."""
    out, in_fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def strip_html_tags(text: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", text)


def count_syllables(word: str) -> int:
    """Heuristic syllable count — good enough for a readability estimate."""
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    word = re.sub(r"^y", "", word)
    groups = re.findall(r"[aeiouy]+", word)
    return max(1, len(groups))


def flesch_kincaid_grade(text: str):
    """Return (grade, words, sentences) or (None, ...) if too little text."""
    sentences = max(1, len(re.findall(r"[.!?]+(?:\s|$)", text)))
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
    n_words = len(words)
    if n_words < 30:
        return None, n_words, sentences
    syllables = sum(count_syllables(w) for w in words)
    grade = 0.39 * (n_words / sentences) + 11.8 * (syllables / n_words) - 15.59
    return round(grade, 1), n_words, sentences


def strip_licence_footer_html(raw: str) -> str:
    """Remove the licence <footer> element so its required legal boilerplate does not count toward
    the reading-grade. The footer carries fixed credit/licence text (the © line, 'Provided "as is"',
    the licence name) — page furniture every page must carry, not body prose the reader works through.
    On a short page those ~20 words of legal wording disproportionately raise the Flesch-Kincaid grade
    (the demo reads 8.1 with the footer, 8.0 without). Excluding it makes the grade reflect the body,
    and means adding/adjusting the *required* footer can never trip the readability gate. The © check
    still reads the original raw, so this never weakens the licensing gate. HTML only: the generator
    emits a `<footer class="licence" ...>`; Markdown has no equivalent element and is left unchanged.
    """
    return re.sub(r'<footer\b[^>]*class="[^"]*licence[^"]*"[^>]*>.*?</footer>',
                  " ", raw, flags=re.S | re.I)


# ---- Secret / PII scan (licensing-and-credits.md Section 4) -----------------
# Deterministic backstop for the privacy rule: published docs — public AND internal — must not embed
# secrets or personal data. Designed for LOW FALSE POSITIVES: only high-precision credential shapes
# and email addresses are matched. Real names and phone numbers are deliberately NOT scanned (a
# name/phone scan is high-false-positive; the About & credits privacy bullet plus human review cover
# those). Runs for every scope — a leaked key is a leak regardless of audience. Severity:
#   FAIL  — shapes that are almost never legitimate on a published page (real-credential material).
#   WARN  — softer signals (emails, JWTs, browser API keys, key=<high-entropy>): a human confirms.
# Placeholders are exempt so the suite's own conventions never trip it: the {{key}} profile token,
# example/test domains, and obvious dummy values (your-…, EXAMPLE, REDACTED, xxxx, ****, <…>).

_PLACEHOLDER_VALUE = re.compile(
    r"(?:\{\{.*?\}\}|your[-_]|example|sample|dummy|placeholder|change[-_]?me|redact|"
    r"x{4,}|\*{3,}|<[^>]+>|todo|fixme)", re.I)
_EXAMPLE_EMAIL_DOMAIN = re.compile(
    r"@(?:example\.(?:com|org|net)|sample\.|test(?:\.|$)|localhost|[^@\s]*\.local|your[-_])", re.I)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# Near-certain real-credential shapes -> FAIL (almost never legitimately on a public page).
_SECRET_FAIL = [
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub personal access token", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
]
# Softer signals -> WARN (can appear legitimately; a human confirms).
_GOOGLE_KEY = re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")
_KV_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|access[_-]?key|client[_-]?secret|bearer)\b"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{16,})[\"']?")


def scan_secrets_pii(raw: str):
    """Return (level, message) findings for credential/PII shapes. Scans the raw text INCLUDING code
    fences — a real token pasted into a code block is the classic leak — but exempts placeholders."""
    findings, seen = [], set()

    def add(level: str, msg: str):
        if (level, msg) not in seen:
            seen.add((level, msg)); findings.append((level, msg))

    def line_of(pos: int) -> int:
        return raw[:pos].count("\n") + 1

    for label, rx in _SECRET_FAIL:
        for m in rx.finditer(raw):
            if _PLACEHOLDER_VALUE.search(m.group(0)):
                continue
            add("FAIL", f"possible {label} on the page (line ~{line_of(m.start())}) — redact before "
                       f"publishing (licensing-and-credits.md Section 4)")
    for m in _EMAIL.finditer(raw):
        em = m.group(0)
        if (_EXAMPLE_EMAIL_DOMAIN.search(em) or _PLACEHOLDER_VALUE.search(em)
                or em.lower().startswith(("noreply@", "no-reply@", "donotreply@"))):
            continue
        add("WARN", f"email address '{em}' on the page (line ~{line_of(m.start())}) — confirm it is "
                    f"an intended public contact, not a leaked personal address")
    for m in _GOOGLE_KEY.finditer(raw):
        if _PLACEHOLDER_VALUE.search(m.group(0)):
            continue
        add("WARN", f"Google API key shape on the page (line ~{line_of(m.start())}) "
                    f"— confirm it is not a real, unrestricted key")
    for m in _JWT.finditer(raw):
        if _PLACEHOLDER_VALUE.search(m.group(0)):
            continue
        add("WARN", f"JSON Web Token shape on the page (line ~{line_of(m.start())}) "
                    f"— confirm it is not a real token")
    for m in _KV_SECRET.finditer(raw):
        if _PLACEHOLDER_VALUE.search(m.group(2)) or _PLACEHOLDER_VALUE.search(m.group(0)):
            continue
        add("WARN", f"'{m.group(1)}' set to a long literal value (line ~{line_of(m.start())}) "
                    f"— confirm it is a placeholder, not a real secret")
    return findings


# ---- Staleness / last-reviewed check ---------------------------------------
# A page that answers "what is the current stack / phase" goes stale; for an FAQ or status doc that
# is the most likely real-world failure. The render contract's stamp (primitive P2) carries a
# machine-readable last-reviewed date (ISO YYYY-MM-DD), surfaced as a `<meta name="last-reviewed">`
# in HTML or a "Last reviewed: YYYY-MM-DD" line in either format. This WARNs (never FAILs) when that
# date is older than the threshold or is in the future; an absent date is an INFO nudge, not noise.
# Threshold resolution: CLI --max-age-months > profile max_doc_age_months > built-in 6.

_LAST_REVIEWED = re.compile(
    r"(?:name=[\"']last-reviewed[\"']\s+content=[\"']"   # <meta name="last-reviewed" content="...">
    r"|data-last-reviewed=[\"']"                          # data-last-reviewed="..."
    r"|last[\s_\-]*reviewed[\"'\s:>=*_]*)"               # visible "Last reviewed: ..." (tolerates *,_ markup)
    r"(\d{4}-\d{2}-\d{2})", re.I)
# Note on the trailing char class: it tolerates stray Markdown emphasis (*, _) between the label and
# the date, so BOTH bold forms read — "**Last reviewed: YYYY-MM-DD**" (date inside the bold) AND
# "**Last reviewed:** YYYY-MM-DD" (bold closed before the date). Adding *,_ only widens the allowed
# separators after the literal phrase "last reviewed"; it cannot make the phrase match where it did
# not, so an unrelated bracket/citation still cannot trip it (brackets are not in the class).


def _months_between(d0: _dt.date, d1: _dt.date) -> float:
    return (d1.year - d0.year) * 12 + (d1.month - d0.month) + (d1.day - d0.day) / 30.0


def check_staleness(raw: str, max_age_months: float, today: _dt.date | None = None):
    today = today or _dt.date.today()
    m = _LAST_REVIEWED.search(raw)
    if not m:
        return [("INFO", "no machine-readable last-reviewed date found "
                         "(render-contract.md P2: carry a 'Last reviewed: YYYY-MM-DD' stamp)")]
    try:
        d = _dt.date.fromisoformat(m.group(1))
    except ValueError:
        return [("WARN", f"last-reviewed date '{m.group(1)}' is not a valid YYYY-MM-DD date")]
    if d > today:
        return [("WARN", f"last-reviewed date {d.isoformat()} is in the future — check it")]
    age = _months_between(d, today)
    if age > max_age_months:
        return [("WARN", f"last reviewed {d.isoformat()} (~{age:.0f} months ago, threshold "
                         f"{max_age_months:g}) — re-verify the facts it cites and refresh the stamp")]
    return [("INFO", f"last reviewed {d.isoformat()} (~{age:.0f} months ago) — within the "
                     f"{max_age_months:g}-month window")]


# ---- Profile parsing (real YAML, no hand-rolled regex) ---------------------

def _merge_yaml_blocks(md_text: str) -> dict:
    """Extract every ```yaml ...``` fenced block from a markdown profile, safe_load each,
    and merge the top-level keys into one dict. Returns {} if YAML is unavailable or none parse."""
    if not _HAVE_YAML:
        return {}
    merged: dict = {}
    for block in re.findall(r"```ya?ml\s*\n(.*?)```", md_text, flags=re.S | re.I):
        try:
            data = yaml.safe_load(block)
        except Exception:
            continue
        if isinstance(data, dict):
            merged.update(data)
    return merged


def load_profile(profile_path: Path | None) -> dict:
    """Load the merged profile dict. Supports a markdown profile with embedded ```yaml blocks
    (the suite default) and a plain .yaml/.yml file."""
    if not profile_path or not profile_path.exists():
        return {}
    if not _HAVE_YAML:
        return {}
    text = profile_path.read_text(encoding="utf-8", errors="ignore")
    if profile_path.suffix.lower() in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return _merge_yaml_blocks(text)


def _stem_candidates(skill: str):
    """Candidate profile-key stems for a --skill value, most-specific first.
    Handles hyphen/underscore and legacy short stems in both directions."""
    s = skill.strip().lower().replace("-", "_")
    cands = []
    # canonical alias (e.g. faq -> project_faq), then the normalized form itself
    if s in SKILL_KEY_ALIASES:
        cands.append(SKILL_KEY_ALIASES[s])
    cands.append(s)
    # reverse alias (e.g. project_faq -> faq) so a legacy profile still resolves
    for short, canon in SKILL_KEY_ALIASES.items():
        if canon == s and short not in cands:
            cands.append(short)
    # de-dup, preserve order
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def profile_lookup(profile: dict, prefix: str, skill: str | None):
    """Return profile[prefix+stem] for the first matching stem, or None."""
    if not skill:
        return None
    for stem in _stem_candidates(skill):
        key = f"{prefix}{stem}"
        if key in profile:
            return profile[key]
    return None


def _is_hard_internal(term: str) -> bool:
    """Classify a profile-supplied internal term as always-fail (looks like a filename / acronym /
    named tool) rather than a generic English word that should only warn."""
    t = term.strip()
    if "." in t:                       # filename, e.g. SOMETHING.md
        return True
    if len(t) >= 3 and t.isupper():    # acronym, e.g. MAANG
        return True
    if re.search(r"\b(Claude|Cowork)\b", t):
        return True
    return False


def resolve_internal_terms(profile: dict):
    """Build the two tiers, folding in any profile-supplied internal_reference_terms."""
    hard = list(ALWAYS_FAIL_INTERNAL)
    warn = list(REVIEW_WARN_INTERNAL)
    for term in (profile.get("internal_reference_terms") or []):
        term = str(term).strip()
        if not term:
            continue
        if _is_hard_internal(term):
            if term not in hard:
                hard.append(term)
        else:
            if term not in warn:
                warn.append(term)
    return hard, warn


# ---- Checks ----------------------------------------------------------------

def gather_files(target: Path, fmt: str):
    if target.is_file():
        return [target]
    exts = {"md": [".md"], "html": [".html", ".htm"]}[fmt]
    return sorted(p for p in target.rglob("*") if p.suffix.lower() in exts)


def check_file(path: Path, fmt: str, grade_target: float, scope: str,
               banned_words: list[str], hard_internal: list[str], warn_internal: list[str],
               licence_id: str = "", max_age_months: float = 6.0):
    findings = []  # (level, message)
    raw = path.read_text(encoding="utf-8", errors="ignore")
    prose_src = strip_code_fences(raw) if fmt == "md" else strip_html_tags(raw)
    prose_lower = prose_src.lower()
    # Readability is measured on the body, with the required licence footer excluded (HTML only) so
    # its fixed legal boilerplate cannot push the grade over the gate — see strip_licence_footer_html.
    readability_src = strip_html_tags(strip_licence_footer_html(raw)) if fmt == "html" else prose_src

    # 1. Banned flowery words (built-in list + profile's extra_banned_words)
    for w in banned_words:
        m = re.search(r"\b" + re.escape(w) + r"\b", prose_lower)
        if m:
            line = prose_src[: m.start()].count("\n") + 1
            findings.append(("FAIL", f"banned word '{w}' (line ~{line})"))

    # 2. Internal references / tool names (public scope only) — two tiers
    if scope == "public":
        for term in hard_internal:
            if re.search(r"\b" + re.escape(term) + r"\b", prose_src, re.I):
                findings.append(("FAIL", f"internal reference '{term}' on a public-scope page"))
        for term in warn_internal:
            if re.search(r"\b" + re.escape(term) + r"\b", prose_src, re.I):
                findings.append(("WARN", f"generic internal-reference word '{term}' on a public page "
                                         f"— confirm it is used in its ordinary sense"))

    # 3. Author intent / motivation
    for term in AUTHOR_INTENT_TERMS:
        if re.search(r"\b" + re.escape(term) + r"\b", prose_lower):
            findings.append(("WARN", f"possible author-intent phrasing '{term}'"))

    # 4. Over-long quotes (possible reproduced third-party text)
    for m in re.finditer(r"\"([^\"]{1,600})\"", prose_src):
        if len(m.group(1).split()) > 15:
            findings.append(("WARN", "quoted span over 15 words — check it is not reproduced text"))
            break

    if fmt == "md":
        # 5. Raw HTML outside code fences (only a small allowlist is fine)
        allow = {"details", "summary", "strong", "br", "em", "kbd", "sub", "sup"}
        for m in re.finditer(r"</?([a-zA-Z][a-zA-Z0-9]*)", strip_code_fences(raw)):
            tag = m.group(1).lower()
            if tag not in allow:
                findings.append(("WARN", f"unexpected raw HTML tag <{tag}> outside code fence"))
                break
        # 5b. GitHub-style alert tokens (> [!NOTE] etc.). The module template bans them because
        #     non-GitHub renderers (wikis, plain Markdown) show the raw token; the suite uses
        #     bold-label callouts instead. Fence-stripped first, so a documented example is exempt.
        if re.search(r"(?m)^\s*>\s*\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", strip_code_fences(raw)):
            findings.append(("WARN", "GitHub-style alert token '> [!...]' found — some viewers show "
                                     "the raw token; use a bold-label callout instead"))
        # 5c. Built-vs-designed honesty marker must be the canonical token. The suite (house style,
        #     the architecture NFR/failure-mode methods, the render contract, the module template) uses
        #     exactly "[designed, not yet built]", and the render contract requires it to survive every
        #     publish target verbatim — downstream tools and readers match it literally. A bracketed
        #     near-miss ("[designed but not yet built]", "[designed, not built]", a dropped comma)
        #     silently defeats the built-vs-designed guarantee the whole suite leans on. Fence-stripped
        #     first, so a documented example inside a code block is exempt. WARN, never FAIL: it is a
        #     nudge to the exact wording, not a blocker. The match requires a bracketed span carrying
        #     "designed" plus "built" or "yet", so an unrelated bracket (a citation, "[see above]")
        #     cannot trip it.
        canon_marker = "[designed, not yet built]"
        for m in re.finditer(r"\[[^\[\]\n]*\]", strip_code_fences(raw)):
            low = m.group(0).lower()
            if "designed" in low and ("built" in low or "yet" in low):
                if re.sub(r"\s+", " ", low).strip() != canon_marker:
                    findings.append(("WARN", f"non-canonical built-vs-designed marker {m.group(0)!r} "
                                             f"— use the exact token '[designed, not yet built]' so it "
                                             f"renders and is matched verbatim on every target"))
                    break
        # 6. Relative link / asset resolution
        for m in re.finditer(r"\]\((\.\/[^)#]+)", raw):
            target = (path.parent / m.group(1)).resolve()
            if not target.exists():
                findings.append(("FAIL", f"broken relative link -> {m.group(1)}"))

    if fmt == "html":
        # 5h. Basic structural sanity
        if raw.count("<h1") == 0:
            findings.append(("WARN", "no <h1> found"))
        if not re.search(r"<html[^>]*\blang=", raw, re.I) and "<html" in raw.lower():
            findings.append(("WARN", "no lang attribute on <html> (accessibility)"))
        imgs = re.findall(r"<img\b[^>]*>", raw, re.I)
        missing_alt = [i for i in imgs if not re.search(r"\balt=", i, re.I)]
        if missing_alt:
            findings.append(("WARN", f"{len(missing_alt)} <img> without alt text (accessibility)"))
        # 5i. Canonical link still a placeholder on a published HTML page
        if re.search(r"canonical link wired at publish", raw, re.I):
            findings.append(("WARN", "canonical link placeholder still present "
                                     "— substitute the real published URL at publish"))

    # 7. Readability. A glossary is a definitions list, not continuous prose; the Flesch–Kincaid
    #    grade (designed for prose) over-reports difficulty on it because a glossary must name the
    #    domain's terms. So a high grade on a glossary is a WARN, never a hard FAIL: it must not
    #    block the gate, and stripping necessary terms to lower the number is the wrong fix.
    is_glossary = path.stem.lower() == "glossary"
    grade, n_words, _ = flesch_kincaid_grade(readability_src)
    if grade is None:
        findings.append(("INFO", f"readability skipped (only {n_words} words)"))
    else:
        msg = f"reading grade ~{grade} (target <= {grade_target})"
        if grade > grade_target + 1.5 and not is_glossary:
            findings.append(("FAIL", msg + " — simplify"))
        elif grade > grade_target:
            note = (" — denser than target (expected for a definitions list; keep terms plain, "
                    "do not drop necessary terms)") if is_glossary else " — slightly above target"
            findings.append(("WARN", msg + note))
        else:
            findings.append(("INFO", msg + " — ok"))

    # 8. Licence footer / copyright notice (licensing-and-credits.md rule)
    has_copyright = "©" in raw
    if scope == "public" and not has_copyright:
        findings.append(("FAIL", "public page is missing the licence footer (no © copyright line) "
                                 "— see licensing-and-credits.md"))
    if scope == "public" and licence_id and licence_id not in raw:
        findings.append(("WARN", f"licence id '{licence_id}' not found on the page "
                                 f"— the footer should name it"))

    # 9. Secret / PII shapes (any scope — a leaked credential is a leak regardless of audience).
    findings.extend(scan_secrets_pii(raw))

    # 10. Staleness — last-reviewed older than the threshold (or in the future). WARN-only.
    findings.extend(check_staleness(raw, max_age_months))

    return findings, has_copyright


# ---- LICENSE-file check (opt-in: --license) --------------------------------

# Whitespace-independent anchors for the standard "AS IS" warranty/liability text. Both must be
# present (in any line-wrapping) for the disclaimer to count as included.
DISCLAIMER_ANCHORS = ["WITHOUT WARRANTY OF ANY KIND", "IN NO EVENT SHALL THE"]


def check_license_file(path: Path, licence_id: str, code_licence: str):
    """Confirm a LICENSE carries the warranty/liability disclaimer and names the content licence
    (and, as a warning, the separate code licence). Returns (findings, fail_count)."""
    findings = []
    if not path.exists():
        findings.append(("FAIL", f"--license: file not found: {path}"))
        return findings, 1
    raw = path.read_text(encoding="utf-8", errors="ignore")
    norm = re.sub(r"\s+", " ", raw).upper()
    if not all(a in norm for a in DISCLAIMER_ANCHORS):
        findings.append(("FAIL", f"LICENSE is missing the 'AS IS' warranty/liability disclaimer "
                                 f"({path.name}) — insert the profile's licence_disclaimer verbatim"))
    if licence_id and licence_id.upper() not in norm:
        findings.append(("FAIL", f"LICENSE does not name the content licence '{licence_id}'"))
    if code_licence and not re.search(r"\b" + re.escape(code_licence) + r"\b", raw, re.I):
        findings.append(("WARN", f"LICENSE does not name the separate code licence '{code_licence}' "
                                 f"— state the docs-vs-code separation"))
    fails = sum(1 for lvl, _ in findings if lvl == "FAIL")
    return findings, fails


# ---- Main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Portable documentation verifier.")
    ap.add_argument("target", help="File or directory to verify")
    ap.add_argument("--format", choices=["md", "html"], default="md")
    ap.add_argument("--skill", default=None,
                    help="Skill name, e.g. learning-track. Resolves grade_target_<stem> and "
                         "scope_<stem> from the profile when those flags are not given explicitly.")
    ap.add_argument("--grade-target", type=float, default=None,
                    help="Override the reading-grade target (else profile, else 9).")
    ap.add_argument("--scope", choices=["public", "internal"], default=None,
                    help="Override the audience scope (else profile, else public).")
    ap.add_argument("--profile", default=None, help="Path to project-profile.md (or a .yaml).")
    ap.add_argument("--license", dest="license_path", default=None,
                    help="Path to the LICENSE file. When given, confirm it carries the warranty/"
                         "liability disclaimer and names the content licence (and code licence).")
    ap.add_argument("--max-age-months", type=float, default=None,
                    help="Staleness threshold for the last-reviewed stamp (else profile "
                         "max_doc_age_months, else 6). WARN-only.")
    args = ap.parse_args()

    target = Path(args.target)
    if not target.exists():
        print(f"ERROR: path not found: {target}")
        return 2

    profile_path = Path(args.profile) if args.profile else None
    if args.profile and not _HAVE_YAML:
        print("NOTE: PyYAML not installed — the profile is ignored; using defaults/CLI flags only.")
    profile = load_profile(profile_path)

    # Resolve grade target and scope: explicit flag > profile(skill) > default.
    grade_target = args.grade_target
    src_grade = "flag"
    if grade_target is None:
        v = profile_lookup(profile, "grade_target_", args.skill)
        if v is not None:
            grade_target = float(v); src_grade = "profile"
    if grade_target is None:
        grade_target = 9.0; src_grade = "default"

    scope = args.scope
    src_scope = "flag"
    if scope is None:
        v = profile_lookup(profile, "scope_", args.skill)
        if v in ("public", "internal"):
            scope = v; src_scope = "profile"
    if scope is None:
        scope = "public"; src_scope = "default"

    if args.skill and src_grade == "default" and args.grade_target is None and profile:
        print(f"NOTE: no grade_target match for --skill '{args.skill}' in the profile; using default 9.")

    banned_words = BANNED_WORDS + [str(w).strip() for w in (profile.get("extra_banned_words") or [])]
    hard_internal, warn_internal = resolve_internal_terms(profile)
    licence_id = str(profile.get("licence_id", "") or "")
    code_licence = str(profile.get("code_licence", "") or "")

    # Staleness threshold: CLI flag > profile max_doc_age_months > built-in 6.
    max_age_months = args.max_age_months
    if max_age_months is None:
        pv = profile.get("max_doc_age_months")
        max_age_months = float(pv) if pv is not None else 6.0

    print(f"resolved: grade-target={grade_target} ({src_grade})  scope={scope} ({src_scope})"
          + (f"  skill={args.skill}" if args.skill else "")
          + (f"  (+{len(banned_words) - len(BANNED_WORDS)} profile banned word(s))"
             if len(banned_words) > len(BANNED_WORDS) else ""))

    files = gather_files(target, args.format)
    if not files:
        print(f"No .{args.format} files found under {target}")
        return 0

    total_fail = total_warn = 0
    any_copyright = False
    for f in files:
        findings, has_copyright = check_file(f, args.format, grade_target, scope,
                              banned_words, hard_internal, warn_internal, licence_id, max_age_months)
        any_copyright = any_copyright or has_copyright
        fails = [m for lvl, m in findings if lvl == "FAIL"]
        warns = [m for lvl, m in findings if lvl == "WARN"]
        infos = [m for lvl, m in findings if lvl == "INFO"]
        total_fail += len(fails)
        total_warn += len(warns)
        status = "FAIL" if fails else ("WARN" if warns else "PASS")
        print(f"\n[{status}] {f}")
        for m in fails:
            print(f"   FAIL  {m}")
        for m in warns:
            print(f"   warn  {m}")
        for m in infos:
            print(f"   info  {m}")

    # Internal doc sets must carry a copyright notice somewhere (lighter than per-page).
    if scope == "internal" and files and not any_copyright:
        total_fail += 1
        print("\n[FAIL] <document set>")
        print("   FAIL  internal documents carry no copyright notice (no © anywhere) "
              "— add the internal footer from licensing-and-credits.md")

    # Optional: confirm the LICENSE carries the disclaimer and names the licences.
    if args.license_path:
        lic_findings, lic_fails = check_license_file(Path(args.license_path), licence_id, code_licence)
        total_fail += lic_fails
        total_warn += sum(1 for lvl, _ in lic_findings if lvl == "WARN")
        status = "FAIL" if lic_fails else ("WARN" if lic_findings else "PASS")
        print(f"\n[{status}] LICENSE ({args.license_path})")
        for lvl, m in lic_findings:
            print(f"   {'FAIL' if lvl == 'FAIL' else 'warn'}  {m}")
        if not lic_findings:
            print("   info  disclaimer present; content licence named")

    print(f"\n--- summary: {len(files)} file(s), {total_fail} FAIL, {total_warn} warn ---")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
