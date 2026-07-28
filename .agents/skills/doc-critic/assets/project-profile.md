# Project profile — fill this in once per project

This is the one place that holds the facts shared across all the documentation skills (learning
track, FAQ, usage guide, architecture, runbook, onboarding). Every skill reads its values from here
so the documents stay consistent.

**How to use it.** On a new project, copy this file to `docs/project-profile.md` in the repository,
then edit the values below. The fields are **pre-filled with sensible defaults** — change anything
that does not fit. Lines marked `# REQUIRED` should be set before you publish.

**Placeholder convention.** Anything written as `{{key}}` (double curly braces) is a slot a tool or
agent fills from the matching key in this file — for example `{{project_name}}`, `{{owner_name}}`,
`{{year}}`. The pattern is the same everywhere, so Claude, Claude Code, GPT, or Codex all read it as
a template slot. `{{project_name}}` ships unfilled on purpose: set the real name here once and every
document inherits it.

**Runtime tokens (the only `{{...}}` that do NOT back to a key here).** Two slots are filled by the
tool at build/publish time, not from this profile — they are the documented, closed set:

- `{{today}}` — the build date in ISO `YYYY-MM-DD` (e.g. an FAQ's `last_reviewed`, set when the page
  is generated). The FAQ generator's demo uses `datetime.date.today()`; in a template the slot reads
  `{{today}}`.
- `{{canonical_url}}` — the real published URL, wired at publish time (the footer/attribution
  "canonical link"). Until publish, the page carries the literal "canonical link wired at publish".

Every other `{{...}}` in the suite must resolve to a key in this file or in `publish-targets.yaml`.
The build's placeholder check (`lint-placeholders.py`) enforces exactly that: an unresolved `{{...}}`
is reported with its `file:line`; these two runtime tokens and the manifest's own slots pass.

> The defaults below are suggestions. They reflect one common setup; replace them with the real
> project's details. Nothing here is binding.

---

## Identity and ownership

```yaml
owner_name:        "Rohit Agrawal"                 # REQUIRED — the person or team credited
brand:             "StackClimb"                    # house brand the project sits under (optional)
project_name:      "{{project_name}}"                # REQUIRED — the project/product name; fill in per project. This is a placeholder, never hard-coded in the skills; everything else reads it as {{project_name}}.
year:              "2026"                           # publish year shown by {{year}} in the footer; set to the publish year (a range like "2024–2026" is fine); update before each publish
public_branding:   "StackClimb {{project_name}}"    # how the name reads publicly (brand + product); swap {{project_name}}, keep or change the brand to suit
github:            "https://github.com/imrohitagrawal"
linkedin:          "https://www.linkedin.com/in/rohitagrawal14/"
contact:           "via the LinkedIn profile above"
```

## Licence and attribution

```yaml
licence_id:        "CC BY-NC-ND 4.0"               # content licence for the docs
licence_url:       "https://creativecommons.org/licenses/by-nc-nd/4.0/"
licence_footer:    "© {{year}} {{owner_name}} · {{licence_id}} · About & credits · canonical link wired at publish."
attribution_line:  "\"{{project_name}} documentation\" by {{owner_name}} ({{brand}}), licensed under {{licence_id}}. Source: the canonical published URL · {{github}}"
licence_disclaimer: |
  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.
code_licence:      "MIT"                            # licence for any source code in the project (docs use licence_id above)
licence_spdx:      "CC-BY-NC-ND-4.0"               # SPDX id for the content licence (machine-readable; for Git hosts / REUSE)
code_licence_spdx: "MIT"                            # SPDX id for the code licence
watermark:         "Rohit Agrawal · https://www.linkedin.com/in/rohitagrawal14/"   # decorative HTML credit line; NOT a substitute for the © footer; leave blank to omit
watermark_opacity: 0.22                            # 0.18–0.30 recommended; never overlap content
```

## Audience and reading level

```yaml
# Per-skill reading-grade targets (Flesch–Kincaid grade level). Lower = simpler.
grade_target_learning_track:  9     # student-first floor for the learning track
grade_target_usage_guide:     2     # grade-1 to grade-3; the simplest output
grade_target_project_faq:             8
grade_target_architecture_and_decisions:    11    # technical readers, but still plain
grade_target_operations_runbook:         10
grade_target_onboarding_companion:      7

# Audience scope per output: "public" (stands alone, hide build tooling) or "internal"
# (team/contributors, may name the day-to-day workflow and tools).
scope_learning_track:   "public"
scope_usage_guide:      "public"
scope_project_faq:              "internal"
scope_architecture_and_decisions:     "public"
scope_operations_runbook:          "internal"
scope_onboarding_companion:       "internal"

# Staleness threshold (months) for the last-reviewed stamp the verifier checks. A page whose
# last-reviewed date is older than this WARNs (never fails); raise it for slow-moving docs, lower
# it for fast-moving ones. A CLI --max-age-months overrides this; default if unset is 6.
max_doc_age_months: 6
```


> **How the verifier reads this.** Each documentation skill runs the shared verifier as
> `python3 scripts/verify.py <docs> --skill <skill-name> --profile docs/project-profile.md`.
> The skill name maps to the keys above by turning hyphens into underscores
> (`learning-track` -> `grade_target_learning_track`). A CLI `--grade-target` / `--scope` flag
> still overrides the profile. The `internal_reference_terms` below are checked only on
> `public`-scope docs: filenames/acronyms/tool names hard-fail, ordinary English words only warn.

## Visual language

```yaml
# Defaults match the shared house style. Override if the project has its own brand palette.
palette_primary:        "#4338CA"   # indigo — system/AI steps
palette_primary_border: "#3730A3"
palette_success:        "#15803D"   # green — outcomes
palette_neutral_fill:   "#E2E8F0"
palette_neutral_text:   "#1E293B"
palette_line:           "#64748B"   # slate
palette_title:          "#0F172A"
palette_subtitle:       "#334155"
font_family:            "DejaVu Sans, Helvetica, Arial, sans-serif"
```

## House style additions

```yaml
# Words to ban in addition to the shared list (leverage, seamless, robust, delve,
# supercharge, unlock, harness, elevate, cutting-edge, game-changer, effortless,
# empower, revolutionise). Add project-specific ones here.
extra_banned_words: []

# Internal-reference terms that must NOT appear in public-scope docs (tool names,
# build-process words, internal working files). Extend per project.
internal_reference_terms:
  - "backbone"
  - "handoff"
  - "CLAUDE.md"
  - "SKILL.md"
  - "MAANG"
  - "FAANG"
```

## Project facts the docs draw on

```yaml
# These ground the documents. Fill from the repository and the decision record.
one_line_summary:   "{{project_name}} — one plain-English sentence on what the project does and who it is for. Replace this example with the real summary."
repo_layout:        "polyrepo now, monorepo later"            # how the code is organised
adr_location:       "docs/adr/ (flat NNNN-slug.md sequence); index at docs/adr/README.md"
decision_log:       "the live Decision Log (mirrors the ADR registry)"
requirements_home:  "the issue tracker"                       # where requirements live
docs_home:          "the docs site / wiki"                    # where published docs live
status_link:        "the project roadmap and Decision Log"    # where live build status is tracked
canonical_example:  "Room booking — a signed-in user can book an available room for a date range, and can view, change, or cancel their own booking; staff can list and filter all bookings."
practice_api:       "restful-booker (or another public sandbox API)"  # for runnable examples
```

---

## Notes for whoever fills this in

- The **canonical example** matters: pick one worked example that exercises as many of the project's
  capabilities as possible, and thread it through every document. Room booking is a strong default
  because it forces ambiguity (what does "available" mean?), edge cases (overlaps, time zones),
  authorisation (owner vs other user vs staff), pagination, and data integrity (no double-booking).
- If the project was built with AI assistance and you must state it in a **public** document, use one
  neutral factual line and no career or motivation framing. Team-facing (`internal`) documents may
  describe the workflow and tools fully.
- Keep this profile in the repository and update it when a core fact changes; the documents inherit
  from it.
