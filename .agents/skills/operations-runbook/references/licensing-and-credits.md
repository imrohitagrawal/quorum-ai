# Licensing and credits — the shared standard (read before publishing any document)

The single source of truth for how every document this suite produces is licensed and credited. The
values live in `project-profile.md`; the text and placement live here. Do **not** copy this content
into individual skills — reference it. Keep `{{project_name}}` a placeholder, filled per project;
only the brand, author, URLs, licence, and disclaimer are fixed. Every value drawn from the profile
is written as `{{key}}` (double curly braces, matching a key in `project-profile.md`) so any tool or
agent resolves it the same way.

Values from the profile: `owner_name`, `brand`, `github`, `linkedin`, `contact`, `licence_id`,
`licence_url`, `licence_footer`, `attribution_line`, `licence_disclaimer`, `code_licence`,
`licence_spdx`, `code_licence_spdx`, `watermark`, `year`.

## 1. What carries what (chosen by the skill's `scope_<skill>`)

| Output scope | Per-page footer | LICENSE file | About & credits page | Disclaimer |
|---|---|---|---|---|
| **public** | yes, on every page | yes (public variant) | yes | in LICENSE + About & credits |
| **internal** | short copyright line on the doc | yes (internal variant) | a credits block in the doc | in LICENSE + footer |

## 2. Per-page footer

- **Public** (every page): `{{licence_footer}}`
  → renders as `© {{year}} {{owner_name}} · {{licence_id}} · About & credits · <canonical link>`.
- **Internal** (foot of the document):
  `© {{year}} {{owner_name}} ({{brand}}). Internal — not for distribution. Provided "as is"; see LICENSE.`

Every public page MUST carry the footer (the © line). The verifier enforces this as a hard failure.

The `<canonical link>` (and the "Source: the canonical published URL" in the attribution line,
Section 4) is a **placeholder wired to the real published URL at publish time** — the `{{canonical_url}}`
runtime token (defined in `project-profile.md`, "Runtime tokens"); substitute it in both places so a
re-sharer can point back to the exact source. The optional HTML `{{watermark}}` (a
subtle credit line, profile field `watermark`) is **decorative only and does not satisfy the footer
requirement**: an HTML page still needs the © footer line, not just the watermark. HTML generators
that render a watermark must also render the © footer (or a credits block carrying it).

## 3. LICENSE file

### 3a. Public content — `{{licence_id}}`
Plain-words summary (share-only: Attribution / NonCommercial / NoDerivatives), the links to the CC
deed and legal code (`{{licence_url}}` and `{{licence_url}}legalcode`), the attribution example
(Section 4), and a scope note: this licence covers the documentation content; source code is licensed
separately under `{{code_licence}}` (Section 3c). Then the disclaimer (3d).

### 3b. Internal content
`© {{year}} {{owner_name}} ({{brand}}). All rights reserved.` · "Internal — not for external
distribution." · then the disclaimer (3d).

### 3c. Code
Any source code in the project is licensed under **`{{code_licence}}`**, separate from the docs. State
this separation in the LICENSE so a reader never assumes the content licence governs the code. For
machine-readable detection (Git hosts, REUSE/SPDX tooling), include the SPDX identifiers from the
profile: content `{{licence_spdx}}`, code `{{code_licence_spdx}}` (e.g. `SPDX-License-Identifier:
{{licence_spdx}}` in the LICENSE header, and the code SPDX in source-file headers or a NOTICE).

### 3d. Warranty and liability disclaimer (in both variants)
Insert the profile value **`{{licence_disclaimer}}`** verbatim and unaltered into the LICENSE — in
**both** the public (3a) and internal (3b) variants. It is the standard "AS IS" warranty/liability
text; the literal wording is defined **once**, in the profile (`licence_disclaimer`), so it is never
restated here (no value in two places). The verifier can confirm it is present in the LICENSE: run
`verify.py --license <LICENSE>` (Section 6).

This covers the materials AND any code. (CC BY-NC-ND already disclaims warranties for the content;
this makes it explicit and extends it to code, which CC is not meant to license.)

## 4. About & credits page (write once per doc set; update as it grows)

In plain words:
- **What this is** and where to start; the public name `{{project_name}}` under the **{{brand}}** brand.
- **Author / maintainer:** {{owner_name}} — GitHub {{github}}, LinkedIn {{linkedin}}. Contact: {{contact}}.
- **How to attribute (on reshare):** `{{attribution_line}}` — i.e. *"{{project_name}} documentation" by
  {{owner_name}} ({{brand}}), licensed under {{licence_id}}. Source: the canonical published URL ·
  {{github}}.*
- **Licence:** {{licence_id}}, with the short plain summary and a link to the LICENSE file.
- **Commercial use / translations / derivatives:** ask first (NonCommercial + NoDerivatives); contact
  via {{contact}}.
- **Trademark acknowledgements:** name each third-party registered mark with its owner, used
  nominatively (e.g. *SAFe is a registered trademark of Scaled Agile, Inc.*). Present `{{project_name}}`
  as a product under the **{{brand}}** brand.
- **Originality / assets:** all diagrams original; images use permissively-licensed fonts — name
  them: text in diagrams is set in **DejaVu Sans** (DejaVu Fonts, released under a permissive
  Bitstream Vera / DejaVu licence); outside facts paraphrased and cited.
- **Privacy / no personal data:** published docs must not embed personal data — real names, emails,
  phone numbers, tokens, credentials, or live on-call/rota contacts. Redact logs, screenshots-as-
  text, and worked examples before publishing; reference roles or aliases, not individuals. This
  applies especially to internal runbooks and FAQs that paste real incidents or environment detail.
  `verify.py` gives this a deterministic, low-false-positive backstop: it **FAILS** near-certain
  credential shapes on a page (private-key blocks, AWS access-key ids, GitHub tokens, Slack tokens)
  and **WARNs** softer signals (email addresses, JSON Web Tokens, browser API keys, a
  `secret/key/token = <long value>` assignment), exempting placeholders (the `{{key}}` token,
  example/test domains, obvious dummy values). It does **not** scan for names or phone numbers — those
  are too false-positive-prone for a machine and stay a human-review item. The scan runs for **every**
  scope: a leaked key is a leak whether the page is public or internal.

## 5. IP rules (enforced by the IP critic and the verifier)
No third-party text reproduced (paraphrase + cite; any unavoidable quote under 15 words, attributed);
all diagrams/GIFs original; no copyrighted screenshots, product UI, or logos without rights;
trademarks used nominatively with acknowledgement; field facts cited to verifiable sources.

## 6. Machine-enforcement (what the verifier checks)

The footer rule is a **hard gate**, not advice. `verify.py` (shipped at `scripts/verify.py`) enforces:

- **Public page footer.** Any `public`-scope page without a `©` line **FAILS**. It also warns if the
  page does not name `{{licence_id}}`.
- **Internal set copyright.** An `internal`-scope document set with no `©` anywhere **FAILS** at the
  set level (lighter than per-page).
- **LICENSE + disclaimer (optional flag, wire it in CI).** `verify.py --license <path>` confirms the
  LICENSE exists, **FAILS** if the "AS IS" warranty/liability text (`licence_disclaimer`) is absent or
  if `{{licence_id}}` is not named, and **warns** if the separate code licence (`{{code_licence}}`) is not
  named. This catches a LICENSE that forgot the disclaimer or the docs-vs-code separation.
- **Canonical link wiring.** On an HTML output, a leftover canonical **placeholder** (the page still
  says "canonical link wired at publish") **warns** — a reminder to substitute the real URL at publish.
- **Secret / PII shapes (every scope).** A page carrying a near-certain credential shape (private-key
  block, AWS access-key id, GitHub token, Slack token) **FAILS**; softer signals (email addresses,
  JSON Web Tokens, browser API keys, a `secret/key/token = <long value>` assignment) **warn**.
  Placeholders are exempt (`{{key}}`, example/test domains, obvious dummy values). Names and phone
  numbers are not machine-scanned (too false-positive-prone) and stay a human-review item. This is the
  deterministic backstop for the Section 4 privacy rule.
- **Staleness (last-reviewed).** A page whose last-reviewed stamp (render-contract.md P2,
  `YYYY-MM-DD`) is older than the threshold — CLI `--max-age-months` > profile `max_doc_age_months` >
  6 — or is in the future **warns**; an absent stamp is an INFO nudge. Going stale is the most likely
  real-world failure for a Q&A or status page, so this gives "refresh per milestone" teeth without
  blocking a build.

**The profile must be readable for scope to resolve.** Scope (public vs internal) selects the
licensing variant, and it comes from the profile via `--skill`. If PyYAML is not installed the profile
is ignored and scope **silently falls back to `public`** — which mis-judges internal sets. Install
PyYAML in every gate (CI and pre-commit) so the correct variant is enforced; the resolver prints the
source (`flag` / `profile` / `default`) so a silent fallback is visible.

> This is a grounded standard, not legal advice. For commercial licensing, registering the **{{brand}}**
> mark, or anything with legal exposure, consult a qualified attorney.
