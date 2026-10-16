# ADR-0167: The secret scan reads every file git could commit

## Status

Accepted — 2026-10-14. The work is the owner's choice: CHG-042 (b) put the secret scan fifth,
after W56, W68, W55 and CI pinning (board row W70). The rule for home-directory paths is the
owner's decision CHG-045 ("Rewrite them to ~"). The rest of the design below is the session's.

Revised 2026-10-16, three times, under the owner's decision CHG-050 (2026-10-15): a miss that has a fix
is fixed, test first. Only a miss with no fix is written down, with its reason.

- Round 3 fixed four review findings in the named-secret rule, one slow pattern in
  `env_secret_assignment`, and four home-path misses. Its review then found new defects in the
  named-secret rule.
- Round 3 was the third fix in a row on that rule to add defects, so the stop rule applied
  (CHG-049): stop patching, write the root cause and a smaller plan, and have Codex review it.
  The plan split W70. This branch keeps the file selection, the joined key, the known shapes and
  the home-folder rule. It removes the named-secret rule, which moves to board row W83. Input
  the kept rules cannot read moves to board row W84.
- The split's second review round found more misses and false positives in the home-folder
  rule. The owner chose to fix them before shipping and to record three limits (CHG-053). The
  eight that needed a change are F1 to F8 below.

The home-folder rule's final tests are in `tests/unit/test_security_scan_w70_split.py`. The
other tests of the kept rules are in `tests/unit/test_security_scan.py`,
`tests/unit/test_security_scan_w70.py`, `tests/unit/test_security_scan_w70_round1.py`,
`tests/unit/test_security_scan_w70_round2.py` and `tests/unit/test_security_scan_w70_round3.py`.

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

## Why the named-secret rule moved to W83

`named_secret_assignment` read, one line at a time, the assignment syntax of every kind of file
the repository holds: shell, make, YAML, JSON, Python, JavaScript, Markdown and Dockerfile.
**The root cause:** three fix rounds in a row on this rule (rounds 1 and 2 on 2026-10-14, round 3
on 2026-10-16) each added misses or false positives in a syntax other than the one being fixed.

Round 3's review found these, reproduced against the commits before and after round 3
(`a0ce4ca` and `70080f3`):
- new misses: a secret in a Makefile comment; a continued make recipe line that starts with
  spaces; a value that starts with `+` after an earlier quoted word (`echo "a" DB_PASSWORD="+…"`);
- new false positives: `%DB_HOST%:%DB_PORT%`; help text inside code that shows the form
  of the setting; a Python annotation read as YAML; `SENTRY_DSN=` followed by a space and the
  next name; `process.env.DB_PASSWORD+""`;
- old misses still open: a `"NAME=value"` string over 512 characters in code; `\n` written after
  a value; base64url with `_` after a YAML `:`.

W83 carries these, and the items round 3 listed as having a likely fix: Python item assignment
(`env["X_TOKEN"] = …`), the Dockerfile form `ENV X_TOKEN value`, Python string prefixes
(`f"…"`, `r"…"`, `b"…"`), values in parentheses, JavaScript template literals, a name and its
value in two fragments with no `+` (`"DB_PASSWORD=" "…"`), a type annotation with a space
(`dict[str, str]`) and `vault:` references. The split added one item of its own: lines
continued with a backslash.

The plan for W83 has to choose one of: a reader per syntax, picked by file kind; a maintained
tool with a baseline file (gitleaks was looked at on 2026-09-29, 20 hits over 475 commits and
none real, and not adopted: `docs/analysis/2026-09-29/skills-tools-shortlist.md`); or a narrower
rule with its limits written down. W83 is scheduled work, not a known limit, so CHG-050 binds
it. Until it lands, the only check by name is the older `env_secret_assignment`: the five exact
names above, at the start of a line, outside `tests/`.

## Why some input moved to W84

The kept rules read each line as it is written. Three kinds of input they cannot read:
- a UTF-16 file, or any text with a NUL byte in its first 8192 bytes: it is skipped as binary;
- an encoded key or shape: a JSON `\u002d` or a URL's `%2D` for `-`, or base64;
- quoted fragments joined with backticks.

Each needs a new decoder in front of every rule. When the split was planned, this item had one
review round left under the two-round cap in `.agents/skills/work-item-delivery/SKILL.md`, so a
decoder built then would have shipped without review. W84 is scheduled work, not a known limit, so CHG-050 binds it.

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
   joined for the two value checks: the OpenRouter key (`raw_openrouter_key_pattern`) and the
   known shapes (`known_secret_shape`). Each check reports a line at most once.
3. **`env_secret_assignment`** was on `main` before W70 and stays. Its Python pass-through
   pattern is rewritten so no two neighbouring parts can take the same space (Measurements,
   row 6).
4. **`known_secret_shape`**, under any name and with no exemption: a Fly token, a Google client
   secret (`GOCSPX-`), a Sentry DSN with its 32-hex key, a GitHub token (`gh?_`, `github_pat_`),
   and a Tavily key (`tvly-`). A Fly token uses the prefixes flyctl v0.4.113 itself matches
   (`fo1_`, `fm1a_`, `fm1r_`, `fm2_`): after `FlyV1` (any case, one or more spaces) with 20 or
   more characters, or bare with 40 or more.
5. **`home_directory_path`**, with no exemption (CHG-045). Three forms:
   - **`/Users/<name>`.** A folder directly under the macOS root is a person's home folder,
     wherever its name ends: at `/`, a space, a quote, `)`, any other character that is not a
     name character, or the end of the line. Before the split a `/` after the name was needed,
     so `cd /Users/<name>` at the end of a line was missed.
   - **`/home/<name>/`.** Under the Linux root the `/` after the name is still needed. Without
     it, `WORKDIR /home/app` and `fetch("/home/feed")` were named.
   - **`-Users-<name>-` and `-home-<name>-`.** The dash form a Claude project folder's name
     uses. Its leading `-` may not follow a letter, digit, `_` or combining mark, so the CSS
     class `nav-home-icon-large` is not a home folder. Before `home` it may not follow another
     `-` either, so the option `--home-dir-path` is not one: command-line options are lower
     case. Before `Users`, with its capital `U`, it may: a Claude folder made under another
     folder holds `-private-tmp--Users-<name>-`, one `-` for the `/` that ends the parent
     folder and one for the `/` that starts the root. The name is the slash form's, so `\ `
     counts in it too (F1). It ends at a `-`, or at `/`, a quote, a backtick, whitespace, `)` or
     the end of the line, as in `~/.claude/projects/-Users-<name>/memory/` (F6).

   **Where a slash form starts.** The `/` before the root must start a path. It may not follow
   a word character of any script (a letter, digit or `_`), a combining mark, `.`, `/`, `-` or
   `]`. So a folder called `Users` or `home` inside another path, a URL's path, a host called
   `home`, an IPv6 host (`http://[::1]` then the root) and a host written in another script are
   not home folders. Four more starts count:
   - a `:` before the root (a drive letter `C:`, or a `PATH` list after `bin:`), unless it is a
     URL's port colon: a `:` inside a URL's host, the text from `://` to the next `/` (F4). So
     `https://example.org:` then the root is not a home folder, while a drive letter after the
     host, as in `file:///C:` or `?file=C:`, is;
   - a compiler flag glued to the path: `-` and 1 to 12 ASCII letters at a token start, that
     is the line's start or after whitespace, a quote, `=`, a backtick, `(`, `[`, `,` or `{`
     (`-I`, `-isystem`; F7). `docs-I` and a 13-letter run are not flags;
   - a file URL: `file://` or `file://localhost` directly before the root, when `file:` starts
     a token: the line's start, or after whitespace, a quote, `(`, `=`, `<` or `[`; or when it
     follows the `+` of a scheme such as `git+file:` or `path+file:` (F2). So a `file://`
     inside another URL's path is that URL's path. No other host counts;
   - a system folder directly before the root (F5): macOS's data volume
     `/System/Volumes/Data`, a Windows drive under WSL (`/mnt/` and one letter), or `/var`. The
     system folder must itself start a path.

   **The name** may hold a word character of any script, `-`, any combining mark (an accent or
   vowel sign written as its own character: all of Unicode's category M, read from Python's
   Unicode tables at import), and, after its first character, `.` and `$`. So `/home/$USER/` is
   still a placeholder, and a name that starts with `.` is a hidden file, not a person (F8). A
   space counts only when written `\ ` (a shell escape). The line is first cut so no run of
   combining marks is longer than 30 (Unicode's stream-safe text format, UAX #15, allows no more
   than 30 in a row; F3), then put into Unicode's composed form (NFC), so a base and a combining mark are judged as
   the one character they compose: `=` followed by U+0338 is `≠`, which may stand before a
   path, and the Kelvin sign is the letter `K`, so `-I` and it make a flag.

   **Not names:** an empty name (the bare root), `<you>` and `<user>` (angle brackets are not
   name characters), a name that starts with `.` (`...` is this repository's placeholder), and
   `Shared`, the macOS system folder, which names no person.

   **What was rewritten.** On 2026-10-14, of the 48 existing lines, the 38 in docs became
   `~/...`; the 9 in `tests/unit/test_claude_settings_portability.py` now build the path at run
   time; and the 1 in the `scripts/validate_claude_settings.py` docstring now reads
   `/Users/<you>/`. `scripts/session_hygiene.py` prints a worktree under the home folder as
   `~/...`, so `make handoff` stops writing one into `docs/session-handoff.md`. On 2026-10-16
   the dash form named 8 more committed lines in 4 files under `docs/analysis/`. In each, the
   session replaced the owner's name with `<user>`, its reading of CHG-045 for a name inside a
   folder name, and the rest of the line is unchanged.

## Measurements

Rows 1 to 5 on 2026-10-14; rows 6 to 14 on 2026-10-16, on the owner's Mac.

| # | Fact | Value | Command |
|---|---|---|---|
| 1 | The miss | 14 planted files: the same key in 11 (1 named, `k.py`), a key split over two quoted strings on one line in 1 (missed), and named secrets in 2 (missed) | the session's plant in a `git archive` copy of `b604c69`, then `python3 scripts/security_scan.py` |
| 2 | Files read | 1582 before, 1684 after, 0 findings; no file read before is dropped. The 102 added include 55 `.ts`, 10 `.gitkeep`, 6 `.js`, plus `Makefile`, `Dockerfile`, `uv.lock` and one `.sh` file | `python3 scripts/security_scan.py` before and after; reported by the builder; the orchestrator's re-run printed `1685 files scanned, 0 findings` with this ADR added |
| 3 | The file list matches git | the scanned set equals git's committable list minus binary and missing files, in both directions | `tests/unit/test_security_scan_w70.py::test_the_real_tree_is_read_exactly_as_git_would_commit_it` |
| 4 | Home paths rewritten | 48 lines in 31 files before, 0 after: 29 docs files (38 lines), `tests/unit/test_claude_settings_portability.py` (9) and `scripts/validate_claude_settings.py` (1). The question to the owner said 35 files; the other 4 hold only the `/Users/.../` placeholder | the new rule over the tree; `git grep -n -E '/(Users\|home)/[A-Za-z0-9._-]+/'` |
| 5 | The rewrite changed nothing else | each rewritten doc equals its `main` copy with only the home prefix replaced | `git show HEAD:<file>` with the same substitution, compared with `cmp` (by the builder) |
| 6 | The Python pass-through pattern | before: 0.12 s, 0.49 s and 1.96 s for 4,000, 8,000 and 16,000 spaces after `token = <identifier>`, four times longer for each doubling. After: under 1 s on 1 MB lines | `_contains_env_secret_assignment(..., is_python=True)` timed directly; `tests/unit/test_security_scan_w70_round3.py::test_step6_the_passthrough_pattern_is_fast_on_a_1mb_run_of_spaces` |
| 7 | The kept checks stay fast | under 2 s for each check on each adversarial 1 MB line, in a child process killed at 120 s, and each check still names its own planted line | `tests/unit/test_security_scan_w70_round2.py::test_every_line_check_finishes_quickly_on_a_1mb_adversarial_line`; for the split's new home forms, `tests/unit/test_security_scan_w70_split.py::test_the_home_rule_finishes_quickly_on_1mb_lines_of_its_new_forms` |
| 8 | The dash form in the tree | 8 committed lines in 4 files, each a Claude project folder name holding the owner's name; 0 after the rewrite | `git grep -n -E -- '-Users-[A-Za-z0-9._]+-'`; `tests/unit/test_security_scan_w70.py::test_every_committed_dash_encoded_home_folder_is_named` |
| 9 | The split's home rule, before and after, by lines named | the tree: 0, then 8 (row 8), then 0 after the rewrite. The installed Python packages of the main checkout's virtual environment: 34, then 334. The e2e suite's installed JavaScript packages: 32, then 45. No line named before is lost. The files read in each are counted in row 13 | each line of every file read under the folder (a file with a NUL byte in its first 8192 bytes is not read), given to `_contains_home_directory_path` of commit `3d42751` and then of `6f42052` |
| 10 | What the new lines outside the tree are | the 300 new Python-package lines are all `path+file://` URLs to the CI runner account's home folder under the macOS root, in 8 packages' CycloneDX files under `.dist-info`; they need the file-URL start. Of the 13 new JavaScript-package lines, 10 are `file://` URLs to a `user` folder under the Linux root, in code comments of one package (5 lines in each of two builds of one file), and 3 are a package author's own folder under the macOS root, in example output; they need the no-`/` form. Each is a home folder; none is prose. They stay named after round 2 (row 13) | the same read, each new line run again with one of the new forms turned off |
| 11 | The whole tree | 1712 files scanned, 0 findings | `uv run python scripts/security_scan.py` |
| 12 | Each part bites | with one part turned off at a time, this many tests in `tests/unit/test_security_scan_w70_split.py` turn red: the escaped space 10, the dash form 18, a `-` allowed before `-Users-` 2, the no-`/` form 11, the port-colon rule 5, the file-URL start 10, the NFC step 2, all combining marks in a name 1, combining marks in the boundary 2; F1 1, F2 2, F3 1, F4 4, F5 3, F6 7, F7 5, F8 2. Measured at commit `b144ef2`, 111 tests passing before each change. At the next commit, removing `+` from the file-URL start turns 3 of 114 tests red | the scanner copied aside, one part put back to its earlier form, the test file run, the copy put back and compared with `diff -q` |
| 13 | Round 2 (F1 to F8), before and after, by lines named | the tree: 1712 files read, 0 new lines, 0 lost. The installed Python packages: 5477 files read, 0 new, 0 lost. The first build of F2 lost the 300 `path+file://` lines of row 10, where `file:` follows `+`; F2 now allows that `+`, and they are named again. The e2e suite's JavaScript packages: 2049 files read, 4 new, 0 lost: a `file:///C:` URL to a `foo` folder under the macOS root in one package's code comments (2 lines in each of two builds of one file), named by F4 | the read of row 9, with the scanner of commit `710bf43` and then this commit's; each new line run again with one fix turned off |
| 14 | Long runs of combining marks | before F3, 0.014 s, 0.055 s and 0.22 s for one run of 8,000, 16,000 and 32,000 marks of two combining classes, time growing with the square of the run. After: under 2 s on each 1 MB line of mark runs | `_contains_home_directory_path` of commit `710bf43` timed directly; `tests/unit/test_security_scan_w70_split.py::test_f3_a_1mb_line_of_combining_mark_runs_finishes_quickly` |

## Rejected alternatives

- **Walk every file on disk.** The owner's checkout holds a gitignored `.env`. A walk would read
  a real key in it and turn the local scan red over a file that can never be committed.
- **Add more suffixes to the list.** A new kind of file would again be unread until someone
  noticed. Reading what git could commit has no list to fall behind.
- **Freeze the existing home paths in an allow-list.** This was the session's recommendation;
  the owner chose to rewrite them (CHG-045).
- **Catch a key split across two lines.** Joining lines would need a parser per language. A
  pasted key arrives on one line; a split across lines is deliberate. It is a known limit.
- **A fourth fix round on the named-secret rule.** The stop rule (CHG-049) forbids it after two
  failed fixes in a row; W83 starts from a new plan instead.
- **Let a home folder's name take an unescaped space.** Three rules were tried, and each named
  prose after a `/home` path: a single space between two parts of a name
  (`copy /home/app to ../backup`), a space only before a capital letter
  (`copy /home/app To ../backup`), and a space only inside quotes
  (`help_text = "/home/app To ../backup"`).

## Consequences

- An untracked, not-ignored file is scanned too. A real key in a new file fails the local scan
  before it is ever staged.
- Mutmut's `./mutants/` copy sits in an ignored folder. There the scan walks the folder, and
  `tests/unit/test_security_scan_w70.py` is deselected from the mutant run
  (`tests/unit/test_mutation_test_set_integrity.py`). It tests `scripts/`, which mutmut does not
  mutate.
- A named secret, under a name ending in `_API_KEY`, `_TOKEN`, `_SECRET`, `_DSN` or
  `_PASSWORD`, is not found until W83 lands. That is scheduled work, not a limit.
- Known limits of the kept rules, each with no fix found and its reason (CHG-050):
  - a secret under a name that does not end in one of the five suffixes, with none of the
    known shapes: nothing on the line says it is a secret;
  - a key split across lines: joining lines needs a parser per language; a pasted key
    arrives on one line, and a split across lines is deliberate;
  - fragments joined with commas: `["a", "b"]` is two strings, and joining across commas
    would read every list as one string;
  - a Linux home folder with no `/` after the name: that form names `WORKDIR /home/app` and
    `fetch("/home/feed")`, and a person's name cannot be told from a folder's;
  - a name with an unescaped space under the Linux root (`open "/home/Jane Doe/notes.txt"`):
    each of the three rules tried named prose (Rejected alternatives). Under the macOS root the
    folder before the space is still named;
  - a home folder inside a longer path, other than after the system folders F5 allows: a
    folder called `Users` or `home` inside another path is not a home folder, and the two read
    the same;
  - a `PATH` entry that is a URL with an empty port
    (`PATH=/usr/bin:https://example.org:/home/alice/bin`): it reads the same as a URL whose
    path is that home folder. Telling them apart needs the shell's `PATH` split, and the same
    text in prose is a URL (CHG-053);
  - a web path under the macOS root with no `/` after it, such as the current-user endpoint
    `me` fetched by a web page, or a SCIM `/Users/<id>`: it is named, because a folder called
    `me` reads the same (CHG-053);
  - a Windows path written with backslashes (`C:\Users\<name>\`): CHG-045 names the
    `/Users/<name>/` and `/home/<name>/` forms, and the owner's choice records this one as a
    limit (CHG-053);
  - git history: the rewritten paths remain in earlier commits of this public repository,
    and removing them means rewriting published history with a force-push, which the
    work-item process forbids.
- Advisory, not built: the independent listing in
  `tests/unit/test_security_scan_w70.py::test_the_real_tree_is_read_exactly_as_git_would_commit_it`
  keeps a path only when it is a regular file, following links, while the scan reads every
  symbolic link as its link text. The repository has no tracked links today
  (`git ls-files -s | grep -c ^120000` prints 0). A committed link that dangles or points to
  a folder would turn that test red on a correct scan, and its helper would then need to
  keep links too.
