# Session handoff — 2026-10-14 (second session)

The session of 2026-10-14 (transcript `42608a52`) ran `CONTINUE-SECURITY-W69-W70-PROMPT.md`: W69, then W70 (CHG-042 (b)). The source of truth is `git log` and the ADRs; this note says where things stand.

## Shipped

| Pull request | Merge commit | What | Decisions |
|---|---|---|---|
| #566 | `c56dd8e` | W69: every outside GitHub Action pinned to a commit with its version as a comment; `uv` 0.13.0 and `flyctl` 0.4.117 pinned; a manual deploy refused from any ref but `main` (on refs that carry W69); `zizmor` 1.30.1 run offline from `uv.lock` as a blocking step of `validate-and-test`; `DEPLOY.md`'s rollback steps corrected (flyctl has no `releases rollback`) | ADR-0166 |

#566 was verified in production on 2026-10-14:
- the Deploy job of run 38537469815 concluded `success`;
- its log shows `Acquired 0.4.117`;
- `/status` `build_sha` read `c56dd8eca23771050a7f7de8a9b7a2f0766e449e`;
- `/ready` returned 200.

Before the merge, `#566`'s own CI log showed:
- `No findings to report. Good job! (6 ignored, 22 suppressed)` from the zizmor step;
- `Successfully installed uv version 0.13.0`.

## Not shipped: W70 stopped under the stop rule

W70 (the secret scan) is on branch `w70/secret-scan`, pushed as a draft pull request (#567). It is not merged.

The work-item process stops a work item when two fixes in a row add defects, or a required finding remains after round 2. Both happened:
- Round 1's fixes widened rules and added false positives and slow inputs.
- Round 2's fix narrowed them, then the narrow re-check of `688debf` found D1 to D4. The pull request body lists them.
- D1 is `REQUIRED_CONTRACT`. A value containing `%letters%` anywhere counts as a placeholder (`_PERCENT_VARIABLE.search` in `_is_placeholder`), so `DB_PASSWORD=Kx9%vQ2%w7zPq` passes. Reproduced by the orchestrator; the same value with each `%` replaced by a letter (`Kx9xvQ2xw7zPq`) is named.

Owner decision recorded on the branch, not on `main`: CHG-045 (home-directory paths: "Rewrite them to ~"). The CHG row reaches `main` with W70.

**Root cause, as far as it is understood.** `named_secret_assignment` is a hand-built reader for assignments in shell, make, YAML, TOML, JSON, Python and JS/TS. Each round traded misses for false positives:
- round 1 widened the value characters;
- round 2 narrowed them and dropped a guard;
- each change broke a case the other had covered.

The other W70 parts are the file selection, the joined OpenRouter key, the known shapes, the home-path rule and the rewrite. Round 2's re-check reported no new false positive in them: a reviewer compared both commits over about 2.9 million lines of real code (`e2e/node_modules`, the venv's site-packages, the tree) and found 0 lines newly flagged. That figure is the reviewer's, not re-measured here, and it counts false positives only.

The same re-check reported four home paths that `688debf` misses and `deab8d4` caught. Codex reproduced them independently; they are not in ADR-0167's known limits:
- a name with a non-ASCII letter (`/Users/` + an accented name + `/`);
- a name with a space (`/Users/` + a first and last name + `/`);
- a name with `$` (`/home/` + a name ending `$` + `/`);
- a path glued to a compiler flag (`-I` + `/home/<name>/include`).

**Bounded plan for the next session** (the next prompt carries it):
1. Merge `main` into the branch, regenerate `docs/session-handoff.md` (it conflicts), and re-run the scan.
2. D1: test first (the three reviewer cases: `Kx9%vQ2%w7zPq`, a URL with `%C3%A9`, a URL with `%E2%82%AC`), then change `search` to `fullmatch`.
3. Correct ADR-0167. The 512-window sentence is false for a value cut into fragments across the window (D4). The bundled-JavaScript sentence is false in general (D2). A URL whose host is `[::1]` followed by `/home/<name>/` is still flagged. Record D2, D3, D4 and the two pre-existing items (quadratic `_PYTHON_PASSTHROUGH_VALUE` on a 1 MB line, a base64 value ending `=`) as known limits.
4. The four home-path misses above: test each (built at run time, not as literals) and fix it, or record it as a known limit. Do not ship the home-path rule with them unstated.
5. One review round on that diff only. If it finds a new defect again, split instead of patching:
   - ship the file selection, joined key, known shapes and home paths;
   - move `named_secret_assignment` to its own board row.

## Left for the owner

Two repository settings, recorded in ADR-0166 and board row W79. This session was not approved to change either:
1. Move `FLY_API_TOKEN` into the `production` environment with a branch rule allowing only `main`, attach the environment to the deploy job, and delete the repository copy. Until then, a branch with an older or edited `deploy.yml` can still deploy by a manual run (5 remote branches other than `main` carry the old gate).
2. Turn on the Actions setting that requires actions pinned to a full commit (`sha_pinning_required` reads `false`).

## Left as advisory

From W69 (#566), all listed in ADR-0166:
- `setup-uv` does not check uv 0.13.0's download against a checksum;
- both Dockerfile bases are tags, not digests;
- zizmor's default persona hides some findings;
- a workflow zizmor's schema rejects is skipped;
- zizmor's online audits (impostor commits, version mismatches) ran once by hand, not in CI.

## Traps met this session

- **The signed-in History lane failed again on a merge commit.**
  - Where: `shared-allowance.spec.ts:183`, a 90-second wait for the estimate response, on #566's push run (E2E run 38533093481, first attempt).
  - The Deploy gate refused once. A re-run of the failed job went green, and the deploy followed.
  - The previous handoff recorded the same lane failing first attempts 4 times in 30 runs. Board row W60 tracks this lane's first-attempt failures (history-refresh, shared-allowance).
- **A shell loop that builds a `make` call from a string** (`for t in quality "diff-cover DIFF_BASE=origin/main"`) passes the target and its variable as one word in zsh. `make` read it as a variable assignment, ran its default target instead of the gate, and exited 0; the empty log looked like a pass. Run each gate as its own command.
- **Commit before trusting the board, cited-paths, completion-claims and planted-claims checks.** They read committed files. A `PRESENT` needle must name a commit (`PRESENT@<sha>`). The board's unpinned count line changes whenever a row gains a needle.
- **The word "passed" in a new ADR fails `make validate`.** `scripts/check_completion_claims.py` reads it as a completion claim with no citation.
- **A new test module that reads the real repository through git** must carry `pytest.mark.repo_introspection` and be added to the pinned list in `tests/unit/test_mutation_test_set_integrity.py`. Inside mutmut's `./mutants/` copy the git listing is empty.
- **Stop a background gate chain before letting a fixer edit the tree.** Once this session a chain kept running while a fixer edited; it was stopped as soon as it was noticed.
