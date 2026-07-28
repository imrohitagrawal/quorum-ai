# Architecture method — the C4 views and how to derive them

Use the **C4 model**: four zoom levels that keep an architecture explanation clear. Each level
answers a different question. Draw each as a themed Mermaid diagram (or Structurizr for C4
specifically), recoloured to the palette, with alt text and a static fallback.

## Level 1 — System context (the widest zoom)
*Who and what is involved, and where the system's boundary is.*
- Show the system as one box, the people who use it, and the other systems it talks to.
- State the boundary plainly: what is inside the system's responsibility and what is outside.
- Derive it from: the README, the top-level architecture, and the list of external services/connectors.

## Level 2 — Containers (the major parts)
*The big runnable pieces and how they communicate.*
- A "container" is a separately runnable thing: a service, a database, a job runner, a front end.
- Show each one, what it is responsible for, and the arrows between them (what calls what, over what).
- Derive it from: the repository layout, the services, the data stores, and the contracts/interfaces.
- **Cap a view at about eight nodes.** A diagram with twenty boxes teaches nothing. When the system
  has more containers than that, do not shrink the boxes — **split the container level into a few
  focused views**, each at or under eight nodes, around a theme (for example: the main pipeline; a
  group of specialised engines; the platform-and-operations plane). Name each view and let one shared
  node (the queue, the data store) carry across them so the reader can stitch the views together.

## Level 3 — Components (inside a key part)
*The main building blocks inside the containers that matter most.*
- Zoom into the one or two containers a reader most needs to understand.
- Show the components, their responsibilities, and how they collaborate.
- Derive it from: the module structure and the key classes/functions/interfaces.

## Level 4 — Runtime / data flow (the worked example)
*Follow one real request end to end.*
- Take the canonical worked example from the profile and trace it through the system, step by step.
- Show the sequence: which part does what, in what order, where it pauses for a human, where it stores
  state, and where it can resume after a failure.
- This is the most valuable diagram for understanding; make it concrete with real names from the
  project.

## Which levels to hand-author, and which to generate
The context and container views (Levels 1–2) and the runtime/data-flow trace are **authored at design
time** — they capture the *intended* shape and the *why*, which a reader needs and which the code does
not state. The **component and lower-level code views (Levels 3–4) drift fastest**, because they track
the code line for line. Where the project can generate them from the code — and gate them so the build
fails when the code changes without the diagram updating (docs-in-lockstep) — **prefer generating them
over hand-drawing**, so they cannot silently go stale. Hand-draw a Level 3 view only for the one or two
containers a reader most needs, and **mark it a point-in-time snapshot** with a link to the
generated/source view. The honest split: *intended shape and reasoning are authored; code-level detail
is generated and linked.*

## Patterns and the runtime shape
Name the design patterns the project uses, in plain terms, and say what each buys:
- e.g. *contracts-first* (freeze the shape of every piece of data up front so parts snap together
  later instead of needing a rewrite);
- e.g. a layered runtime (a coordinator that runs steps in order, remembers progress, pauses for
  approval, and resumes after a crash; a switch that routes each step to the right model or service; a
  set of tools the steps call);
- e.g. pluggable implementations behind one interface (so a new variant drops in without changing
  callers).
For each pattern: what it is, why it is used here, and the failure it prevents.

## Writing the views
For each level: one diagram + a few paragraphs that explain it in plain words, define any term on
first use, and give a "why" for the structure. Keep the beginner floor (define the words) even though
the audience is technical — a new engineer is still new.

## Mark the trust boundaries
On the context and container views, **show where untrusted input crosses into the system** — the point
where data the system does not control (a user upload, an external feed, an ingested document) first
reaches a component that acts on it. State plainly what happens at that crossing (validated, sanitised,
sandboxed). For a system with AI components this is essential: text pulled from an external source and
then read by a model that can call tools is a **prompt-injection** path — the standing rule is that
*ingested text is data, never instructions*, and the diagram should make that boundary visible (a
shield or lock annotation on the arrow, paired with a short label) rather than leave it implied. The
boundary is a property of the runtime, not a separate box.

## Colour with meaning (paired with labels)
Use the profile's palette consistently, and give colour a **role**, not decoration: one colour for
ordinary systems/services, a distinct one for AI/model/agent components, one for quality gates and
passing checks, one for risk or bottleneck points, one for failures or incidents, and a neutral one for
external systems. **Never rely on colour alone** (house style Section 7): every colour-coded node also
carries a label, icon, or shape, so the meaning survives for a colour-blind reader and in greyscale.
When a diagram encodes *categorical data* (not chrome), switch to a colour-blind-safe scheme
(Okabe–Ito) with direct labels — the brand palette is for identity, not data series.

## An optional evolution view
For a system built in stages, one extra diagram earns its place: a **left-to-right or top-down timeline
of how the architecture grew**, one step per shipped milestone, grouped by phase. It gives a reader the
*order* the pieces arrived in, which the static views cannot. Keep labels short; group by phase if it
crowds. This view shows the **shape of the growth**, not the live status — do not restate which step is
current (single-source rule); link the live roadmap or decision log for that, so the timeline does not
go stale.
