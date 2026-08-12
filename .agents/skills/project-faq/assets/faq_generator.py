#!/usr/bin/env python3
"""
faq_generator.py — build a self-contained tabbed FAQ as one HTML file.

Import it and call build_faq(faq_dict, "out.html"), or run this file directly to
emit a small demo (so you can confirm it renders before wiring real content).

The HTML it produces has: a grouped left sidebar, one pane per tab, hash deep-links
(#tab-id), left/right arrow-key navigation, two distinct example boxes
("In your project" / "Picture it in real life"), an optional non-overlapping
watermark, and accessibility basics (a single h1, a lang attribute, nav landmark,
img alt required by the author, good contrast). No build dependencies.

Content model (a plain dict):

faq = {
  "title": str, "subtitle": str, "lang": "en",
  "last_reviewed": "YYYY-MM-DD",    # optional but recommended: the date the facts were last checked.
                                    #   Renders a machine-readable <meta name="last-reviewed"> plus a
                                    #   visible stamp (render-contract.md P2). verify.py WARNs when it
                                    #   is older than the staleness threshold — going stale is an FAQ's
                                    #   most likely real failure. Omit and the page is undated (INFO).
  "footer": str,                    # REQUIRED for the licensing gate: the licence line that
                                    #   carries the © (the public or internal variant from
                                    #   references/licensing-and-credits.md). Inline HTML allowed
                                    #   (links to the licence + About & credits). Rendered as a
                                    #   contentinfo <footer>. The watermark below does NOT replace it.
                                    #   Alias accepted: "licence_footer".
  "watermark": str | "",            # optional DECORATIVE credit line (profile `watermark`); not a
  "watermark_opacity": 0.22,        #   substitute for the © footer (licensing-and-credits.md S2).
  "sections": [
    {"name": str, "tabs": [
      {"id": str, "label": str, "blocks": [ <block>, ... ]},
    ]},
  ],
}

Blocks (each a dict with a "type"):
  {"type":"h2","text":...}                         section heading inside a tab
  {"type":"h3","text":...}
  {"type":"p","html":...}                           paragraph (inline HTML allowed)
  {"type":"steps","items":[...]}                    ordered list
  {"type":"bullets","items":[...]}                  unordered list
  {"type":"in_project","html":...}                  the "In your project" box
  {"type":"real_life","html":...}                   the "Picture it in real life" box
  {"type":"note","label":"Key idea","html":...}     callout
  {"type":"code","lang":"bash","text":...}          code block (text is escaped)
  {"type":"table","headers":[...],"rows":[[...],...]}
  {"type":"glossary","items":[(term, definition_html), ...]}
  {"type":"credits","heading":...,"intro":html,"items":[(label, value_html), ...]}
                                                    the About & credits panel. `licensing-and-credits.md`
                                                    Section 4 wants a credits block in the doc (the
                                                    internal variant especially) — this is the first-
                                                    class block for it, so compliance is one block, not a
                                                    hand-composed panel. Carries the attribution line,
                                                    author/maintainer, and the licence link. It does NOT
                                                    replace the © footer (set `footer` too), and it must
                                                    carry only the short licence line, never the full "AS
                                                    IS" disclaimer (that lives in LICENSE).
"""
from __future__ import annotations
import datetime
import html
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------- block render

def _esc(s: str) -> str:
    return html.escape(str(s), quote=False)


def _render_block(b: dict) -> str:
    t = b.get("type")
    if t == "h2":
        return f"<h2>{_esc(b['text'])}</h2>"
    if t == "h3":
        return f"<h3>{_esc(b['text'])}</h3>"
    if t == "p":
        return f"<p>{b['html']}</p>"
    if t == "steps":
        items = "".join(f"<li>{it}</li>" for it in b["items"])
        return f"<ol>{items}</ol>"
    if t == "bullets":
        items = "".join(f"<li>{it}</li>" for it in b["items"])
        return f"<ul>{items}</ul>"
    if t == "in_project":
        return (f'<div class="box box-project"><span class="box-label">'
                f'In your project</span><div class="box-body">{b["html"]}</div></div>')
    if t == "real_life":
        return (f'<div class="box box-real"><span class="box-label">'
                f'Picture it in real life</span><div class="box-body">{b["html"]}</div></div>')
    if t == "note":
        label = _esc(b.get("label", "Key idea"))
        return (f'<div class="box box-note"><span class="box-label">{label}</span>'
                f'<div class="box-body">{b["html"]}</div></div>')
    if t == "code":
        lang = _esc(b.get("lang", ""))
        return f'<pre class="code" data-lang="{lang}"><code>{_esc(b["text"])}</code></pre>'
    if t == "table":
        head = "".join(f"<th>{h}</th>" for h in b["headers"])
        rows = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in b["rows"])
        return f'<table class="tbl"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>'
    if t == "glossary":
        items = "".join(f"<dt>{_esc(term)}</dt><dd>{defn}</dd>" for term, defn in b["items"])
        return f'<dl class="glossary">{items}</dl>'
    if t == "credits":
        head = _esc(b.get("heading", "About & credits"))
        intro = f'<div class="box-body">{b["intro"]}</div>' if b.get("intro") else ""
        rows = "".join(f"<dt>{_esc(lbl)}</dt><dd>{val}</dd>" for lbl, val in b.get("items", []))
        dl = f'<dl class="credits-list">{rows}</dl>' if rows else ""
        return (f'<div class="box box-credits"><span class="box-label">{head}</span>'
                f'{intro}{dl}</div>')
    return ""


def _render_tab(tab: dict) -> str:
    body = "\n".join(_render_block(b) for b in tab["blocks"])
    return (f'<section class="pane" id="{_esc(tab["id"])}" role="tabpanel" '
            f'aria-label="{_esc(tab["label"])}" hidden>\n'
            f'<h1 class="pane-title">{_esc(tab["label"])}</h1>\n{body}\n</section>')

# ---------------------------------------------------------------------- styles

_CSS = """
:root{
  --bg:#FBF7F0; --panel:#FFFDF8; --ink:#1f1b16; --muted:#5b5347;
  --line:#e6ddcd; --indigo:#4338CA; --indigo-bg:#eef0fb; --indigo-bd:#c7cdf3;
  --green:#15803D; --green-bg:#eaf5ee; --green-bd:#bfe0cb;
  --amber:#a15c00; --amber-bg:#fbf1de; --amber-bd:#ecd9b0; --code:#2b2620;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Newsreader","Source Serif 4",Georgia,serif;font-size:18px;line-height:1.65}
a{color:var(--indigo);text-decoration:underline;text-underline-offset:2px}
.layout{display:grid;grid-template-columns:300px 1fr;min-height:100vh}
nav.side{background:var(--panel);border-right:1px solid var(--line);padding:22px 16px;
  position:sticky;top:0;height:100vh;overflow:auto}
.brand{font-family:"Fraunces","Newsreader",Georgia,serif;font-weight:600;font-size:21px;
  line-height:1.2;color:var(--ink);margin:0 0 4px}
.brand .sub{display:block;font-size:13px;color:var(--muted);font-weight:400;margin-top:4px}
.side h4{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
  margin:20px 0 6px;font-family:"Fraunces",serif}
.side a{display:block;padding:7px 10px;border-radius:8px;text-decoration:none;color:var(--ink);
  font-size:15.5px;line-height:1.35}
.side a:hover{background:#f3ecdb}
.side a.active{background:var(--indigo);color:#fff}
main{padding:40px clamp(20px,5vw,72px);max-width:920px}
.pane-title{font-family:"Fraunces","Newsreader",serif;font-weight:600;font-size:30px;
  line-height:1.15;margin:0 0 18px;color:var(--ink)}
h2{font-family:"Fraunces",serif;font-weight:600;font-size:23px;margin:30px 0 10px}
h3{font-family:"Fraunces",serif;font-weight:600;font-size:19px;margin:22px 0 8px;color:var(--muted)}
p{margin:0 0 14px}
ol,ul{margin:0 0 14px;padding-left:22px}
li{margin:6px 0}
.box{border-radius:12px;padding:14px 16px;margin:16px 0;border:1px solid}
.box-label{display:inline-block;font-family:"Fraunces",serif;font-weight:600;font-size:13px;
  letter-spacing:.02em;margin-bottom:6px;padding:2px 8px;border-radius:999px}
.box-body p:last-child{margin-bottom:0}
.box-project{background:var(--indigo-bg);border-color:var(--indigo-bd)}
.box-project .box-label{background:var(--indigo);color:#fff}
.box-real{background:var(--green-bg);border-color:var(--green-bd)}
.box-real .box-label{background:var(--green);color:#fff}
.box-note{background:var(--amber-bg);border-color:var(--amber-bd)}
.box-note .box-label{background:var(--amber);color:#fff}
pre.code{background:var(--code);color:#f4eee2;border-radius:10px;padding:14px 16px;overflow:auto;
  font-family:"JetBrains Mono","IBM Plex Mono",ui-monospace,monospace;font-size:14.5px;line-height:1.5}
code{font-family:"JetBrains Mono","IBM Plex Mono",ui-monospace,monospace;font-size:.92em}
p code,li code{background:#f0e8d8;padding:1px 5px;border-radius:5px}
.tbl{border-collapse:collapse;width:100%;margin:14px 0;font-size:15.5px}
.tbl th,.tbl td{border:1px solid var(--line);padding:8px 11px;text-align:left;vertical-align:top}
.tbl th{background:#f3ecdb;font-family:"Fraunces",serif}
dl.glossary dt{font-family:"Fraunces",serif;font-weight:600;margin-top:12px}
dl.glossary dd{margin:2px 0 0;color:var(--muted)}
.box-credits{background:#f4f1ea;border-color:var(--line)}
.box-credits .box-label{background:var(--ink);color:var(--bg)}
dl.credits-list{margin:8px 0 0;display:grid;grid-template-columns:max-content 1fr;gap:4px 14px}
dl.credits-list dt{font-family:"Fraunces",serif;font-weight:600;color:var(--ink)}
dl.credits-list dd{margin:0;color:var(--muted)}
.reviewed{display:block;font-size:12px;color:var(--muted);margin-top:8px;
  font-family:"JetBrains Mono",monospace}
.watermark{position:fixed;right:14px;bottom:10px;font-size:12px;color:var(--muted);
  pointer-events:none;font-family:"JetBrains Mono",monospace}
footer.licence{grid-column:1/-1;border-top:1px solid var(--line);color:var(--muted);
  font-size:13.5px;line-height:1.55;padding:18px clamp(20px,5vw,72px);background:var(--panel)}
footer.licence a{color:var(--indigo)}
.skip{position:absolute;left:-999px}.skip:focus{left:8px;top:8px;background:#fff;padding:8px;z-index:9}
@media(max-width:820px){.layout{grid-template-columns:1fr}nav.side{position:static;height:auto}}
"""

_FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
          '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
          '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;'
          '9..144,600&family=Newsreader:opsz,wght@6..72,400;6..72,500&family=JetBrains+Mono:wght@400'
          '&display=swap" rel="stylesheet">')

_JS = """
const tabs=[...document.querySelectorAll('.pane')].map(p=>p.id);
const links=document.querySelectorAll('nav.side a[data-tab]');
function show(id){
  if(!tabs.includes(id))id=tabs[0];
  document.querySelectorAll('.pane').forEach(p=>p.hidden=(p.id!==id));
  links.forEach(a=>a.classList.toggle('active',a.dataset.tab===id));
  if(location.hash.slice(1)!==id)history.replaceState(null,'','#'+id);
  document.querySelector('main').scrollTo(0,0);window.scrollTo(0,0);
}
links.forEach(a=>a.addEventListener('click',e=>{e.preventDefault();show(a.dataset.tab);}));
window.addEventListener('hashchange',()=>show(location.hash.slice(1)));
document.addEventListener('keydown',e=>{
  if(e.target.matches('input,textarea'))return;
  const i=tabs.indexOf(location.hash.slice(1)||tabs[0]);
  if(e.key==='ArrowRight'&&i<tabs.length-1)show(tabs[i+1]);
  if(e.key==='ArrowLeft'&&i>0)show(tabs[i-1]);
});
show(location.hash.slice(1)||tabs[0]);
"""

# ----------------------------------------------------------------------- build

def build_faq(faq: dict, out_path: str | Path) -> Path:
    lang = _esc(faq.get("lang", "en"))
    title = _esc(faq["title"])
    subtitle = _esc(faq.get("subtitle", ""))

    # Last-reviewed stamp (render-contract.md P2): a machine-readable <meta> the verifier reads for
    # the staleness check, plus a visible line under the brand. Omit `last_reviewed` and both are
    # dropped (the page is undated; verify.py then reports INFO, not a failure).
    last_reviewed = _esc(faq.get("last_reviewed", "")).strip()
    meta_reviewed = f'<meta name="last-reviewed" content="{last_reviewed}">' if last_reviewed else ""
    reviewed_line = f'<span class="reviewed">Last reviewed: {last_reviewed}</span>' if last_reviewed else ""

    side = [f'<p class="brand">{title}<span class="sub">{subtitle}</span>{reviewed_line}</p>']
    panes = []
    for sec in faq["sections"]:
        side.append(f'<h4>{_esc(sec["name"])}</h4>')
        for tab in sec["tabs"]:
            side.append(f'<a href="#{_esc(tab["id"])}" data-tab="{_esc(tab["id"])}">'
                        f'{_esc(tab["label"])}</a>')
            panes.append(_render_tab(tab))

    wm = ""
    if faq.get("watermark"):
        op = faq.get("watermark_opacity", 0.22)
        wm = f'<div class="watermark" style="opacity:{op}">{_esc(faq["watermark"])}</div>'

    # Licence footer (carries the ©). Required by the licensing gate; the watermark above does not
    # replace it (references/licensing-and-credits.md Section 2). Inline HTML is allowed so the author
    # can link the licence + About & credits. Rendered as a contentinfo landmark spanning the layout.
    footer_text = faq.get("footer") or faq.get("licence_footer") or ""
    footer_html = (f'<footer class="licence" role="contentinfo">{footer_text}</footer>'
                   if footer_text else "")

    doc = f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{meta_reviewed}
<title>{title} — FAQ</title>
{_FONTS}
<style>{_CSS}</style>
</head>
<body>
<a class="skip" href="#__main">Skip to content</a>
<div class="layout">
<nav class="side" aria-label="Sections">{''.join(side)}</nav>
<main id="__main">{''.join(panes)}</main>
{footer_html}
</div>
{wm}
<script>{_JS}</script>
</body>
</html>
"""
    out = Path(out_path)
    out.write_text(doc, encoding="utf-8")
    if "©" not in doc:
        sys.stderr.write(
            f"NOTE: {out} has no © licence footer — set faq['footer'] to the licence line "
            f"(internal or public variant) from references/licensing-and-credits.md; "
            f"the verifier fails a page/set with no ©.\n")
    return out


# --------------------------------------------------------------------- demo/cli

def _demo() -> dict:
    return {
        "title": "Example Project",
        "subtitle": "FAQ & onboarding",
        "lang": "en",
        # The date the facts were last checked. In a real run, set this each milestone; here it is
        # today's date so the demo never trips the staleness WARN and models correct usage.
        "last_reviewed": datetime.date.today().isoformat(),
        # The licence line that carries the © (here the internal variant, also naming the content
        # licence). In a real run, take this from the profile via references/licensing-and-credits.md.
        "footer": ('© 2026 Example Owner (Example Brand) · Licensed under '
                   '<a href="https://creativecommons.org/licenses/by-nc-nd/4.0/">CC BY-NC-ND 4.0</a> · '
                   '<a href="#credits">About &amp; credits</a> · Internal — not for distribution. '
                   'Provided "as is"; see LICENSE.'),
        "watermark": "Your Name · your-link",
        "sections": [
            {"name": "Start here", "tabs": [
                {"id": "overview", "label": "What is it", "blocks": [
                    {"type": "p", "html": "This is a short, plain-words overview of the project. It "
                     "says what the project does, who it is for, and why it matters. Every new word "
                     "is explained the first time it is used, so a reader who is new to the field "
                     "can still follow along."},
                    {"type": "p", "html": "A real answer here would be several paragraphs, not one "
                     "line. It would walk through what the thing is, why it matters, how it works "
                     "step by step, and what was chosen over the other options and why. The two "
                     "boxes below show the pattern: one real example from the project, and one "
                     "everyday picture that anyone can relate to."},
                    {"type": "in_project", "html": "<p>The real, specific example from the project.</p>"},
                    {"type": "real_life", "html": "<p>An everyday analogy anyone relates to.</p>"},
                ]},
                {"id": "glossary", "label": "Words explained", "blocks": [
                    {"type": "glossary", "items": [
                        ("Repository", "the folder, tracked over time, that holds all the project's files."),
                        ("API key", "a secret password a program uses to prove it is allowed to call a service."),
                    ]},
                ]},
            ]},
            {"name": "People", "tabs": [
                {"id": "onboarding", "label": "Your buddy", "blocks": [
                    {"type": "h2", "text": "Set up from zero"},
                    {"type": "steps", "items": ["Install the tools.", "Clone the repository.",
                                                 "Run the quickstart command."]},
                    {"type": "code", "lang": "bash", "text": "make quickstart"},
                ]},
            ]},
            # About & credits — the first-class credits block (licensing-and-credits.md Section 4).
            # Built from profile values in a real run; never hard-code a name. The short licence line
            # only — the full "AS IS" disclaimer stays in LICENSE, off the page.
            {"name": "About", "tabs": [
                {"id": "credits", "label": "About & credits", "blocks": [
                    {"type": "credits",
                     "heading": "About & credits",
                     "intro": "<p>This page is the project FAQ. Start at <em>What is it</em>.</p>",
                     "items": [
                         ("Maintainer", 'Example Owner (Example Brand) — '
                                        '<a href="https://github.com/example">GitHub</a>, '
                                        '<a href="https://www.linkedin.com/in/example/">LinkedIn</a>.'),
                         ("Licence", 'Documentation under '
                                     '<a href="https://creativecommons.org/licenses/by-nc-nd/4.0/">'
                                     'CC BY-NC-ND 4.0</a>; code under MIT. See the repository LICENSE.'),
                         ("How to attribute", '"Example Project documentation" by Example Owner '
                                              '(Example Brand), licensed under CC BY-NC-ND 4.0.'),
                     ]},
                ]},
            ]},
        ],
    }


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1].endswith(".json"):
        data = json.loads(Path(sys.argv[1]).read_text())
        p = build_faq(data, sys.argv[2])
    else:
        out = sys.argv[1] if len(sys.argv) > 1 else "faq-demo.html"
        p = build_faq(_demo(), out)
    print(f"wrote {p}")
