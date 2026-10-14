# ADR-0167: The secret scan reads every file git could commit

## Status

Accepted — 2026-10-14. The work is the owner's choice: CHG-042 (b) put the secret scan fifth,
after W56, W68, W55 and CI pinning (board row W70). The rule for home-directory paths is the
owner's decision CHG-045 ("Rewrite them to ~"). The rest of the design below is the session's.

## Context

Finding S5 of `docs/analysis/2026-10-13-security-review.md`, reproduced on 2026-10-14 in a
`git archive` copy of `main`. The plant was 14 files: the same fake 64-character OpenRouter key
in 11, a key split into two quoted strings in 1, and named secrets in 2.
`scripts/security_scan.py` named only the `.py` one of the 11. It read a fixed list of nine
suffixes (`TEXT_SUFFIXES`), so a key in a `.js`, `.ts`, `.mjs`, `.cjs`, `.sh`, `.cfg`, `.ini`,
`.example` or `.env.example` file, or in a `Dockerfile`, was never read.

The same plant showed three more gaps the review's agents had reported:
- the key split into two quoted strings on one line was missed;
- `FLY_API_TOKEN`, `GOOGLE_CLIENT_SECRET` and `SENTRY_DSN` values in a `.yml` file were missed.
  The old named rule matched only five exact names (`api_key`, `openrouter_key`, `tavily_key`,
  `secret`, `token`), and only at the start of a line;
- nothing checked for a home-directory path. This repository is public, and the
  work-item process says to remove one before committing a new file.

## Decision

1. **Which files.** At the top of a git work tree, the scan reads exactly what
   `git ls-files -z --cached --others --exclude-standard` lists. That is every tracked file,
   plus every untracked file that is not ignored: what could be committed. Anywhere else, it
   walks the folder as before. That covers mutmut's `./mutants/` copy and a `git archive` copy.
   In both modes:
   - there is no suffix list;
   - a file with a NUL byte in its first 8192 bytes is treated as binary and skipped;
   - a listed path missing on disk is skipped;
   - a symbolic link is read as its link text, the path git commits, and never followed: a
     dangling link is still read, and a link to a file outside the repository does not report
     that file's contents;
   - `mutmut-stats.json` stays excluded, and the walk also skips `.hypothesis`, the test
     library's example cache, which holds the scanner's own test strings.

   A gitignored file, such as a local `.env`, is not read.
2. **Joined fragments.** Adjacent quoted fragments on one line (`"a" "b"`, `'a' + 'b'`) are
   joined, for every value check: the OpenRouter key (`raw_openrouter_key_pattern`), the known
   shapes (`known_secret_shape`) and a named secret's value (`named_secret_assignment`). Each
   check reports a line at most once.
3. **`named_secret_assignment`.**
   - **What it matches:** a name ending in `_API_KEY`, `_TOKEN`, `_SECRET`, `_DSN` or
     `_PASSWORD` (any case), assigned a value of 12 or more characters. Shell, make, YAML,
     TOML, JSON, Python and JS/TS forms all count.
   - **What it skips:**
     - placeholders: words such as `example`, `changeme`, `your-`, `xxxx`, and anything with
       `$ < > { }`, which covers `${{ secrets.X }}`, `$(...)` and `<...>`;
     - values with a space;
     - lower-case word phrases such as `race-test-token`;
     - an unquoted value that starts with `#` (a comment);
     - in code files, an unquoted value (a variable handed on, such as `settings.x_token`);
     - a name inside a string whose closing quote follows its `:` or `=`
       (`"client_secret:"`, a label in the bundled API page).
   - **Which characters.** A quoted value may hold any printable character but a space, so a
     password such as `"Tr0ub4dor&3xyzQ"` counts. An unquoted value may hold letters, digits,
     `_-+/=.:@` and the password punctuation `!#%&*?^~`; any other character ends it.
   - **Exceptions:** the name `confirmation_token`, an expiring cost-confirmation value that is
     not a credential; and files under `tests/`, for this rule only. That is the same
     exemption the old named rule had.
4. **`known_secret_shape`**, under any name and with no exemption: a Fly token, a Google client
   secret (`GOCSPX-`), a Sentry DSN with its 32-hex key, a GitHub token (`gh?_`, `github_pat_`),
   and a Tavily key (`tvly-`). A Fly token uses the prefixes flyctl v0.4.113 itself matches
   (`fo1_`, `fm1a_`, `fm1r_`, `fm2_`): after `FlyV1` (any case, one or more spaces) with 20 or
   more characters, or bare with 40 or more.
5. **`home_directory_path`**, with no exemption (CHG-045): `/Users/<name>` or `/home/<name>`,
   with or without a `/` after the name (a path that ends at the name counts). `/Users/.../`,
   `/Users/<you>/` and the bare `/Users/` and `/home/` are placeholders and pass, and so does
   `/Users/Shared`, the macOS system folder, which names no person. Of the 48 existing lines,
   the 38 in docs became `~/...`; the 9 in `tests/unit/test_claude_settings_portability.py` now
   build the path at run time; and the 1 in the `scripts/validate_claude_settings.py`
   docstring now reads `/Users/<you>/`.
   `scripts/session_hygiene.py` now prints a worktree under the home folder as `~/...`, so
   `make handoff` stops writing one into `docs/session-handoff.md`.

## Measurements

All on 2026-10-14.

| # | Fact | Value | Command |
|---|---|---|---|
| 1 | The miss | 14 planted files: the same key in 11 (1 named, `k.py`), a key split over two quoted strings on one line in 1 (missed), and named secrets in 2 (missed) | the session's plant in a `git archive` copy of `b604c69`, then `python3 scripts/security_scan.py` |
| 2 | Files read | 1582 before, 1684 after, 0 findings; no file read before is dropped. The 102 added include 55 `.ts`, 10 `.gitkeep`, 6 `.js`, plus `Makefile`, `Dockerfile`, `uv.lock` and one `.sh` file | `python3 scripts/security_scan.py` before and after; reported by the builder; the orchestrator's re-run printed `1685 files scanned, 0 findings` with this ADR added |
| 3 | The file list matches git | the scanned set equals git's committable list minus binary and missing files, in both directions | `tests/unit/test_security_scan_w70.py::test_the_real_tree_is_read_exactly_as_git_would_commit_it` |
| 4 | Home paths rewritten | 48 lines in 31 files before, 0 after: 29 docs files (38 lines), `tests/unit/test_claude_settings_portability.py` (9) and `scripts/validate_claude_settings.py` (1). The question to the owner said 35 files; the other 4 hold only the `/Users/.../` placeholder | the new rule over the tree; `git grep -n -E '/(Users\|home)/[A-Za-z0-9._-]+/'` |
| 5 | The rewrite changed nothing else | each rewritten doc equals its `main` copy with only the home prefix replaced | `git show HEAD:<file>` with the same substitution, compared with `cmp` (by the builder) |

## Rejected alternatives

- **Walk every file on disk.** The owner's checkout holds a gitignored `.env`. A walk would read
  a real key in it and turn the local scan red over a file that can never be committed.
- **Add more suffixes to the list.** A new kind of file would again be unread until someone
  noticed. Reading what git could commit has no list to fall behind.
- **Freeze the existing home paths in an allow-list.** This was the session's recommendation;
  the owner chose to rewrite them (CHG-045).
- **Catch a key split across two lines.** Joining lines would need a parser per language. A
  pasted key arrives on one line; a split across lines is deliberate. It is a known limit.

## Consequences

- An untracked, not-ignored file is scanned too. A real key in a new file fails the local scan
  before it is ever staged.
- Mutmut's `./mutants/` copy sits in an ignored folder. There the scan walks the folder, and
  `tests/unit/test_security_scan_w70.py` is deselected from the mutant run
  (`tests/unit/test_mutation_test_set_integrity.py`). It tests `scripts/`, which mutmut does not
  mutate.
- Known limits, recorded and not built:
  - a key split across lines;
  - a passphrase written as a lower-case word phrase;
  - a secret under a name that does not end in one of the five suffixes and has none of the six
    known shapes;
  - dash-encoded paths such as `-Users-<name>-Projects-...`;
  - a UTF-16 file, or any text with a NUL byte in its first 8192 bytes: it is skipped as binary;
  - an encoded key (a JSON `\u002d` for `-`, base64, `%2D`), and fragments joined with
    backticks or commas, which are not joined;
  - Python item assignment (`env["X_TOKEN"] = "..."`) and the Dockerfile space form
    (`ENV X_TOKEN value`), which are not named assignments;
  - git history: the rewritten paths remain in earlier commits of this public repository.
- The `tests/` exemption is narrow, and a test pins it: the same named secret under
  `e2e/tests/`, `.github/workflows/`, `src/`, `docs/`, `scripts/` or `tests_extra/` is named
  (`tests/unit/test_security_scan_w70_round1.py`).
