# Visual Asset Factory Model

## Purpose

After requirements are frozen and architecture is approved, the factory must propose product names and create a visual communication plan for engineering, product, leadership, and users.

## Naming gate

After requirements freeze, create `docs/91-product-naming.md` with exactly three name options.

Each name must include:

- name;
- business meaning;
- relation to the core requirement;
- what the product does;
- why users will remember it;
- risks or naming conflicts to verify manually.

## Visual asset gate

After architecture is finalized, create `docs/92-visual-asset-plan.md` and diagram files covering:

- one HERO diagram;
- C4 context diagram;
- C4 container diagram;
- C4 component diagram;
- C4 code/module-level diagram where useful;
- two GIF storyboards;
- one demo video storyboard;
- four Mermaid diagrams: high-level, low-level, module-level, sub-module-level;
- four Excalidraw diagrams: high-level, low-level, module-level, sub-module-level.

## Asset quality rules

Every asset must have:

- audience;
- message;
- source requirement IDs;
- architecture source;
- review owner;
- file path;
- update trigger.

Generated visuals must not invent architecture. They must be derived from approved architecture, ADRs, API contract, data model, and implementation plan.
