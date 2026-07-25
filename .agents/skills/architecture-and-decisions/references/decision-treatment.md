# Decision treatment — five lines per significant choice

A reader understands a system in depth only when they understand *why* it is the way it is. For every
significant choice (each technology, each structural pattern, each major trade-off), write a **five-
line treatment**. Do not list the decision alone — the alternatives and the trade-off are the point.

## The five lines

1. **What it is.** Name the choice and say what it does, in plain words (define any term on first use).
2. **The alternatives.** The two or three real options that were on the table.
3. **Why this one.** The reason it was chosen over the alternatives — the concrete advantage that
   mattered for this project.
4. **When you would choose differently.** The conditions under which an alternative would win. (This is
   what makes the treatment honest and teaches judgement.)
5. **How it serves the purpose.** How this choice helps the project meet its goal, with the honest
   pros and cons.

Link the choice to its decision record by **number** (e.g. "Recorded as ADR-0006"), and point to the
live ADR registry for the canonical status. Do not restate the number's status here — the registry
owns it (the single-source rule).

**Reference tunable values by key — never paste them.** The single-source rule extends past numbers and
status to every *tunable value* a decision carries: a threshold, a count, an `N`, a pixel ratio, a
timeout, the shape of a config object. Name the **key** and point to the file that owns the value (the
ADR or a config file such as `quality-gates.yaml`); do not copy the figure into the treatment. A pasted
value is correct only until the source changes once, after which the walkthrough quietly contradicts the
system — and a decisions document that is wrong about its own decisions is worse than none. A referenced
key cannot drift. Write "the per-tier minimum scores live in `quality-gates.yaml` (`mutationThresholds`)",
not "the threshold is 80%".

## Worked example of the shape

> **Polyrepo now, monorepo later.**
> - *What it is.* Each component lives in its own repository for now; a shared contracts package is
>   published and consumed by the others. (A *repository* is the tracked folder of a project's files; a
>   *monorepo* keeps many projects in one.)
> - *Alternatives.* A single monorepo from day one; or fully independent repos with no shared package.
> - *Why this one.* Components are built and shipped one at a time first, so separate repositories keep
>   each release simple; the shared contracts package stops the pieces drifting apart.
> - *When you would choose differently.* Once the components change together often, a monorepo's single
>   change-set and shared tooling win — migrate then, keeping the same versioning.
> - *How it serves the purpose.* It lets the project ship the first pieces fast without a big-bang
>   setup, and the data shapes stay compatible at the later migration. Recorded as ADR-0006; see the
>   live registry for status.

## Tips
- Cover every choice a new engineer would question. If you cannot give the alternatives and the
  trade-off, you do not yet understand the decision well enough to document it — go read the ADR and
  the code.
- Keep the beginner floor: define each technology in one plain line before comparing it.
- Group related decisions (data store, messaging, framework, testing) so the section reads as a tour,
  not a flat list.
