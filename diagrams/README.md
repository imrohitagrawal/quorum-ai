# Diagrams

This folder stores version-control-friendly architecture and product visuals.

## Required asset set

- HERO diagram
- C4 context, container, component, and module/code-level diagrams
- Four Mermaid diagrams: high-level, low-level, module-level, sub-module-level
- Four Excalidraw diagrams: high-level, low-level, module-level, sub-module-level

Do not invent architecture. Update diagrams from approved requirements, ADRs, API contracts, data model, and implementation plan.

## Viewing the Excalidraw diagrams

`.excalidraw` files are JSON scene data, not images — GitHub has no built-in
renderer for them, so browsing the repo shows raw JSON with nothing to look
at. Each one ships with a rendered PNG next to it so the diagram is actually
visible without installing anything:

| Zoom level | Source (edit this) | Rendered preview |
|---|---|---|
| High-level (QueryRun state machine) | [`excalidraw/10-high-level.excalidraw`](excalidraw/10-high-level.excalidraw) | [`excalidraw/10-high-level.png`](excalidraw/10-high-level.png) |
| Low-level (request sequence) | [`excalidraw/11-low-level.excalidraw`](excalidraw/11-low-level.excalidraw) | [`excalidraw/11-low-level.png`](excalidraw/11-low-level.png) |
| Module-level (domain entities) | [`excalidraw/12-module-level.excalidraw`](excalidraw/12-module-level.excalidraw) | [`excalidraw/12-module-level.png`](excalidraw/12-module-level.png) |
| Sub-module-level (evaluation subsystem) | [`excalidraw/13-sub-module-level.excalidraw`](excalidraw/13-sub-module-level.excalidraw) | [`excalidraw/13-sub-module-level.png`](excalidraw/13-sub-module-level.png) |

To edit: open the `.excalidraw` file at [excalidraw.com](https://excalidraw.com)
(File → Open), make changes, re-export as PNG over the matching file so the
preview stays in sync — a stale preview next to a live source is worse than
no preview.
