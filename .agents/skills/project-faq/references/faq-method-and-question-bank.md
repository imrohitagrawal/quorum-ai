# FAQ method — deriving questions, grouping tabs, and driving the generator

## Deriving the question inventory

The questions come from the project, not a template. Survey these and write down every real question a
newcomer or teammate would ask:

- **The README and overview** → "What is it? What problem does it solve? Who is it for?"
- **The decision records (ADRs) and decision log** → "Why this technology and not the alternatives?
  Why this structure?" One question per significant decision.
- **The architecture and contracts** → "What are the main pieces and how do they fit? What is the
  data flow?"
- **The tech stack** → "What is each tool, why was it chosen over its two main competitors, and how
  does it serve the purpose?"
- **The workflow and config files** → "How do we work day to day? What do the project's rule and
  config files do?"
- **Setup** → "How do I get set up from zero? Where do I get keys and access?"
- **Quality and security** → "How is it tested? What automated checks run? How is it kept secure?"
- **Operations** → "How do I run, monitor, deploy, verify, and debug it?"
- **Running it** → "How do I run it end to end? What is the quickstart?"
- **Sharing** → "How is each piece shipped and shown?"

Keep a **dropped-points checklist**: every agreed point and expert addition must end up in a tab.
Nothing gets quietly lost.

## Grouping into tabs

A reusable grouping (rename to fit the project):

- **Start here** — `overview` (the depth-bar answer), `glossary` (zero-knowledge definitions).
- **Working with the tools** — which tool for what; working with AI without losing quality;
  skills/config; the workflow files.
- **Architecture and decisions** — the stack and why; the components; the processing/agent design.
- **Quality, security, operations** — the testing approach; automated checks and security; behaviour
  rules; run/test/deploy/verify/debug.
- **Sharing and people** — shipping each piece; visual standards.
- **People** — `onboarding` (the step-by-step buddy) and `mentor` (the senior-engineer voice).

## Driving the generator

Author the content as a Python dict and render it (the dict shape is documented at the top of
`assets/faq_generator.py`):

```python
import sys
sys.path.insert(0, "path/to/skill/assets")
from faq_generator import build_faq

faq = {
    "title": "{{project_name}}",
    "subtitle": "FAQ & onboarding",
    "lang": "en",
    # Date the facts were last checked (ISO YYYY-MM-DD). `{{today}}` is the documented runtime token
    # (project-profile.md "Runtime tokens" = the build date); the generator's demo uses
    # datetime.date.today(). Renders the freshness stamp + a machine-readable
    # <meta name="last-reviewed">; the verifier WARNs once it is older than max_doc_age_months.
    "last_reviewed": "{{today}}",
    # The licence line that carries the © (licensing gate). Internal variant for a team FAQ; public
    # variant if scope_project_faq is public. Built from the profile via licensing-and-credits.md.
    "footer": "{{licence_footer}}",
    "watermark": "{{watermark}}",                        # decorative only (optional; omit to skip); NOT a substitute for footer
    "watermark_opacity": 0.22,
    "sections": [
        {"name": "Start here", "tabs": [
            {"id": "overview", "label": "What is it", "blocks": [
                {"type": "p", "html": "..."},
                {"type": "in_project", "html": "<p>...</p>"},
                {"type": "real_life", "html": "<p>...</p>"},
            ]},
            {"id": "glossary", "label": "Words explained", "blocks": [
                {"type": "glossary", "items": [("Term", "definition"), ...]},
            ]},
        ]},
        # About & credits — the first-class credits block (licensing-and-credits.md Section 4).
        # Values come from the profile; never hard-code a name. Short licence line only.
        {"name": "About", "tabs": [
            {"id": "credits", "label": "About & credits", "blocks": [
                {"type": "credits", "heading": "About & credits",
                 "intro": "<p>...</p>",
                 "items": [
                     ("Maintainer", "{{owner_name}} ({{brand}}) — GitHub {{github}}, LinkedIn {{linkedin}}."),
                     ("Licence", "Docs under {{licence_id}}; code under {{code_licence}}. See LICENSE."),
                     ("How to attribute", "{{attribution_line}}"),
                 ]},
            ]},
        ]},
        # ... more sections/tabs ...
    ],
}
build_faq(faq, "outputs/{{project_name}}-faq.html")
```

Block types available: `h2`, `h3`, `p`, `steps`, `bullets`, `in_project`, `real_life`, `note`,
`code`, `table`, `glossary`. The `html` fields accept inline HTML (use it for `<strong>`, `<code>`,
and links). Every answer except the glossary needs both an `in_project` and a `real_life` block.

## Design notes (the generator already enforces these)

- A characterful display font + a readable body font + a mono font; a warm, readable palette (not the
  default sans fonts, not purple-on-white).
- Grouped sidebar, hash deep-links, arrow-key navigation between tabs.
- Accessibility: a single visible h1 per tab, a `lang` attribute, a skip link, good contrast, and
  example boxes that carry a **label** (not colour alone).
- Any image you embed must have `alt` text — add it yourself; the verifier checks for it.
