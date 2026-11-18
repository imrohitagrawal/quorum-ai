# Session prompt: W147's new design, the rest of the dependency updates, the owner's page decisions, then W117 onward

Written 2026-11-17. The full next-session prompt, with its items and approvals, is kept in the
owner's private notes (CHG-102); this file is a pointer so the repository's prompt check and
handoff keep working until W117 changes them.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. The full prompt in the owner's private notes, which this file does not reproduce.
2. `docs/README.md`, then `docs/analysis/2026-11-17-session-handoff-2.md`.
3. `docs/65-open-work.md`: rows W147, W76, W136, W137, W141 to W146, W51, W129, W117, W118,
   W121 and the Parked table (`make parked-check`); `docs/19-change-control-log.md`: CHG-102 to
   CHG-113; ADR-0190.

## The items, in order

As stated in the full prompt in the owner's private notes.

## Approvals

As stated in the full prompt in the owner's private notes; nothing here adds to them.

## End of session

1. Write the narrative handoff as a plain public record.
2. Write the next prompt in the owner's private notes; move this file into `docs/archive/YYYY-MM/`.
3. Run `make handoff` last.
