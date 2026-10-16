# ADR-0167: The secret scan reads every file git could commit

## Status

Accepted — 2026-10-14. The work is the owner's choice: CHG-042 (b) put the secret scan fifth,
after W56, W68, W55 and CI pinning (board row W70). The rule for home-directory paths is the
owner's decision CHG-045 ("Rewrite them to ~"). The rest of the design below is the session's.

Revised 2026-10-16 under the owner's decision CHG-050 (2026-10-15): a miss that has a fix is
fixed, test first, and only a miss with no fix is written down, with its reason. Round 3 fixed
four review findings in `named_secret_assignment` (D1 to D4), two misses found while planning
(base64 padding, and `NAME: <base64>` read only as a type annotation), one slow pattern in
`env_secret_assignment`, and four home-path misses. The tests are in
`tests/unit/test_security_scan_w70_round3.py`.

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
     - a value that is one whole Windows `%NAME%` reference; and Python `%(name)s` templates,
       which hold `(`. A `%` inside a value does not make it a placeholder: while any
       `%NAME%` look-alike in the value counted, a password such as `Kx9%vQ2%w7zPq` and a
       URL holding percent-encoded UTF-8 (`%C3%A9`) were missed (D1);
     - an unquoted value that starts with `#` after a space (YAML `KEY: #note`, `KEY= #x`),
       which is a comment. Directly after `=`, a `#` is part of the value: shell
       `KEY=#abc` assigns `#abc`;
     - in a make file (`Makefile`, `GNUmakefile`, `makefile` or `*.mk`), make's own comment:
       a `#` starts one anywhere, quotes or not, unless an odd number of backslashes stand
       before it, and `\#` is read as `#`. With shell's rule, `KEY=#ConfigureInDeployment`
       in a Makefile was named (D3). A recipe line, which starts with a tab, is run by the
       shell and keeps shell's rule;
     - an unquoted value that is the next assignment's name (`SENTRY_DSN= UV_CACHE_DIR=/tmp/x`),
       but only when a space stands after the `=`. Shell reads `A=B=` as `A` set to `B=`, so
       an unspaced value is always the value, and a spaced value that is base64 with its `=`
       padding (no `_`, a multiple of 4 characters, at least 12) is a value too. Before,
       `KEY=<base64>=` was read as an empty value and the next name;
     - in code files, an unquoted value (a variable handed on, such as `settings.x_token`),
       unless a quote directly follows it: in `"export DB_PASSWORD=<value>"` the value ends
       a string, so it counts as quoted and is checked;
     - a name whose string ends at its `=`. When a quote opens the string the name sits in
       (looking back over only word characters, spaces, `.` and `-`), the `=` follows the
       name directly, and the same quote closes the string straight after it, followed by
       `+`, one of `, ; ) ] }` or the end of the line, the `=` is the string's last
       character. The value is then empty, unless `+` and a quoted literal follow, which is
       the value (`"DB_PASSWORD=" + "<value>"`). No quote is tracked across the line: that
       misreads JSON keys, comments and regular-expression literals (Codex's plan review,
       2026-10-16).
   - **Two readings of `:`.** `NAME: <text> = <value>` is read both as a type annotation and
     as YAML `NAME: <value>`, and either reading can name the line. Read only as an
     annotation, `NAME: <base64>=` was a type followed by `=` and an empty value.
   - **Which characters.** Quoted and unquoted values share ONE set, ASCII only: letters,
     digits, `_-+/=.:@` and the password punctuation `!#%&*?^~`. A value holding any other
     character is not a secret value, so a password such as `"Tr0ub4dor&3xyzQ"` counts, and
     `"Optional[str]"` and a translation such as `"Bestätigungskennwort"` do not. The set
     alone did not keep out the text between two strings in bundled JavaScript:
     `const label="DB_PASSWORD="+publicLabelText+";";` was named, its value read as
     `+publicLabelText+`, which holds only set characters (D2). The string-end rule above is
     what passes that line now. An unquoted value ends at whitespace, a quote, a backtick, or
     one of `, ; ( ) ] }`.
   - **How much is read.** At most 512 characters after the `=` or `:`. A longer value is
     judged on those 512, and that holds for a value in adjacent fragments too: a fragment
     the 512 cut adds its characters up to the cut. Before, the cut fragment had no closing
     quote and was dropped, so the value was only the fragments before it. On a 3/3/594
     split that left 6 characters, under the 12-character floor, and the secret was missed
     (D4). Reading to the end of the line for every name took time growing
     with the square of the line's length: 8.96 s for 200 KB of `A_TOKEN=`, measured by
     review; after the change no line check took over 0.3 s on any of 19 adversarial 1 MB
     lines (the session's timing script, on the owner's Mac). Round 3's rules were timed the
     same way (Measurements, row 9).
   - **Exceptions:** the name `confirmation_token`, an expiring cost-confirmation value that is
     not a credential; and files under `tests/`, for this rule only. That is the same
     exemption the old named rule had.
4. **`known_secret_shape`**, under any name and with no exemption: a Fly token, a Google client
   secret (`GOCSPX-`), a Sentry DSN with its 32-hex key, a GitHub token (`gh?_`, `github_pat_`),
   and a Tavily key (`tvly-`). A Fly token uses the prefixes flyctl v0.4.113 itself matches
   (`fo1_`, `fm1a_`, `fm1r_`, `fm2_`): after `FlyV1` (any case, one or more spaces) with 20 or
   more characters, or bare with 40 or more.
5. **`home_directory_path`**, with no exemption (CHG-045): `/Users/<name>/` or
   `/home/<name>/`, the form the question to the owner named, with the `/` after the name.
   The first `/` must start a path: it may not follow a word character of any script (a
   letter, digit or `_`), a combining mark, `.`, `/`, `-` or `]`. So a folder called `Users`
   or `home` inside another path, a URL's path, a host called `home`, an IPv6 host
   (`http://[::1]` then the root) and a host written in another script pass; the rule before
   round 3 named those last two. A drive letter's `:` does start a path
   (`C:` then `/Users/<name>/` is named), and so does a compiler flag glued to the path:
   `-` and 1 to 12 ASCII letters at a token start, that is the line's start or after
   whitespace, a quote or `=` (`-I`, `-isystem`). `docs-I` and a 13-letter run are not
   flags. The name may hold a word character of any script, `.`, `-`, any combining mark
   (an accent or vowel sign written as its own character: all of Unicode's category M, read
   from Python's Unicode tables at import), `$` after its first character (so
   `/home/$USER/` is still a placeholder), and single spaces between its parts
   (`Jane Doe`). So a name with a separate combining accent is named as its composed form
   is. The plan also put the line into Unicode's composed form (NFC) first; with every mark
   allowed that step decided nothing (turning it off left every test green), so it was not
   kept. Before round 3 the name
   was ASCII letters, digits, `.`, `_` and `-`
   only, and the boundary before the root was ASCII only, so `José`, `Jane Doe`, `svc$`
   and `-I` then a home path were missed. A name with no `/` after it is not named: that
   form also matched `WORKDIR /home/app` and `fetch("/home/feed")`, so it is a known limit
   below.
   `/Users/.../`, `/Users/<you>/` and the bare `/Users/` and `/home/` are placeholders and
   pass, and so does `/Users/Shared/`, the macOS system folder, which names no person.
   Of the 48 existing lines, the 38 in docs became `~/...`; the 9 in
   `tests/unit/test_claude_settings_portability.py` now build the path at run time; and the
   1 in the `scripts/validate_claude_settings.py` docstring now reads `/Users/<you>/`.
   `scripts/session_hygiene.py` now prints a worktree under the home folder as `~/...`, so
   `make handoff` stops writing one into `docs/session-handoff.md`.

## Measurements

Rows 1 to 5 on 2026-10-14; rows 6 to 10 on 2026-10-16, on the owner's Mac.

| # | Fact | Value | Command |
|---|---|---|---|
| 1 | The miss | 14 planted files: the same key in 11 (1 named, `k.py`), a key split over two quoted strings on one line in 1 (missed), and named secrets in 2 (missed) | the session's plant in a `git archive` copy of `b604c69`, then `python3 scripts/security_scan.py` |
| 2 | Files read | 1582 before, 1684 after, 0 findings; no file read before is dropped. The 102 added include 55 `.ts`, 10 `.gitkeep`, 6 `.js`, plus `Makefile`, `Dockerfile`, `uv.lock` and one `.sh` file | `python3 scripts/security_scan.py` before and after; reported by the builder; the orchestrator's re-run printed `1685 files scanned, 0 findings` with this ADR added |
| 3 | The file list matches git | the scanned set equals git's committable list minus binary and missing files, in both directions | `tests/unit/test_security_scan_w70.py::test_the_real_tree_is_read_exactly_as_git_would_commit_it` |
| 4 | Home paths rewritten | 48 lines in 31 files before, 0 after: 29 docs files (38 lines), `tests/unit/test_claude_settings_portability.py` (9) and `scripts/validate_claude_settings.py` (1). The question to the owner said 35 files; the other 4 hold only the `/Users/.../` placeholder | the new rule over the tree; `git grep -n -E '/(Users\|home)/[A-Za-z0-9._-]+/'` |
| 5 | The rewrite changed nothing else | each rewritten doc equals its `main` copy with only the home prefix replaced | `git show HEAD:<file>` with the same substitution, compared with `cmp` (by the builder) |
| 6 | Round 3 over the tree | 1711 files, 0 findings. The D1 change named 1 committed line: the D1 fixture quoted whole in `docs/analysis/2026-10-14-session-handoff-2.md`, now written as two code spans | `uv run python scripts/security_scan.py` |
| 7 | Home-path widening, before and after | lines named by the old rule, then by the new: the tree 0 and 0 (1711 files), the virtual environment's site-packages 34 and 34 (8080 files), the e2e suite's installed JavaScript packages 32 and 32 (2047 files). Each widened form on its own adds 0 lines and loses 0 in every corpus | the session's read-only measuring script, which also checked that each form names its own test line and the old rule does not |
| 8 | The Python pass-through pattern | before: 0.12 s, 0.49 s and 1.96 s for 4,000, 8,000 and 16,000 spaces after `token = <identifier>`, four times longer for each doubling. After: under 1 s on 1 MB lines | `_contains_env_secret_assignment(..., is_python=True)` timed directly; `tests/unit/test_security_scan_w70_round3.py::test_step6_the_passthrough_pattern_is_fast_on_a_1mb_run_of_spaces` |
| 9 | Round 3's rules stay linear | on 20 adversarial 1 MB lines aimed at the new parts (look-back, string end, make comments, spaced names, flags, non-ASCII names), every line check together took at most 0.641 s per line (0.631 s on the final rule); doubling the two slowest lines from 1 MB to 2 MB and 4 MB doubled their time | the session's timing script |
| 10 | D4's cause | on the 3/3/594 fixture cut at 512, the old `_assigned_value` returned `Kx9vQ2` (6 characters); the new returns 505 | the old and new scanner on the same window |

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
- Fixed in round 3 and so no longer a limit: a `"NAME=value"` string inside a code file
  (`["-e", "DB_PASSWORD=…"]` in `.py`, `.js` or `.ts`), by the quote-closes-the-value rule;
  and a value in adjacent fragments crossing the 512-character window (D4).
- Known limits with no fix, each with its reason (CHG-050):
  - a key split across lines: joining lines needs a parser per language; a pasted key
    arrives on one line, and a split across lines is deliberate;
  - a passphrase written as a lower-case word phrase: it cannot be told from the readable
    names the rule must pass, such as `race-test-token` and `mutation-baseline`;
  - a secret under a name that does not end in one of the five suffixes and has none of the
    six known shapes: nothing on the line says it is a secret;
  - fragments joined with commas: `["a", "b"]` is two strings, and joining across commas
    would read every list as one string;
  - a password holding a character outside the set (`|`, `[`, `\`, a space, a letter outside
    ASCII): those characters are what tell code, types, prose and translations from a
    secret, and with any printable character allowed, `"Optional[str]"` and
    `"Bestätigungskennwort"` were named;
  - a home folder written without a `/` after the name (`cd /Users/<name>` at the end of a
    line): that form names `WORKDIR /home/app` and `fetch("/home/feed")`, and a person's
    name cannot be told from a folder's;
  - a home folder inside a longer path: a folder called `Users` or `home` inside another
    path is not a home folder, and the two read the same;
  - a value that starts with `+`, `,`, `;`, `)`, `]` or `}` straight after its quote, when
    another quote stands before the name over only word characters and spaces
    (`echo "a" DB_PASSWORD="+…"`). The string-end rule reads it as the end of a string, as
    it must for `"DB_PASSWORD="+label`, and telling the two apart needs quote tracking
    across the line, which misreads JSON keys, comments and regular-expression literals.
    The old scanner named this line; round 3 does not;
  - git history: the rewritten paths remain in earlier commits of this public repository,
    and removing them means rewriting published history with a force-push, which the
    work-item process forbids.
- Misses and false positives with a likely fix, not built on this branch: each needs its
  own test first (CHG-050), and none has been tried.
  - dash-encoded paths such as `-Users-<name>-Projects-...`;
  - a UTF-16 file, or any text with a NUL byte in its first 8192 bytes: it is skipped as
    binary;
  - an encoded key (a JSON `\u002d` for `-`, base64, `%2D`), and fragments joined with
    backticks;
  - Python item assignment (`env["X_TOKEN"] = "..."`) and the Dockerfile space form
    (`ENV X_TOKEN value`), which are not named assignments;
  - a home folder after another `/` (`file:///Users/<name>/`);
  - for named secrets: a Python string prefix (`f"…"`, `r"…"`, `b"…"`), a value in
    parentheses, a JavaScript template literal (backticks), and a name and its value in two
    fragments joined with no `+` (`"DB_PASSWORD=" "…"`);
  - a type annotation with a space anywhere but around `|` (`dict[str, str]`) hides the
    value after it;
  - a false positive: a `vault:` or KeyVault-style reference of 12 or more set characters
    under a secret name may be named;
  - a false positive from the YAML reading of `:`: in a file that is not code, a Python
    annotation whose type name has 12 or more set characters (`X_TOKEN: <TypeName> = None`
    in Markdown) is named. No committed line has this form today (Measurements, row 6).
- Advisory, not built: the independent listing in
  `tests/unit/test_security_scan_w70.py::test_the_real_tree_is_read_exactly_as_git_would_commit_it`
  keeps a path only when it is a regular file, following links, while the scan reads every
  symbolic link as its link text. The repository has no tracked links today
  (`git ls-files -s | grep -c ^120000` prints 0). A committed link that dangles or points to
  a folder would turn that test red on a correct scan, and its helper would then need to
  keep links too.
- The `tests/` exemption is narrow, and a test pins it: the same named secret under
  `e2e/tests/`, `.github/workflows/`, `src/`, `docs/`, `scripts/` or `tests_extra/` is named
  (`tests/unit/test_security_scan_w70_round1.py`).
