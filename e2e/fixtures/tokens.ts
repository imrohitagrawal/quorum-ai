import { Page } from "@playwright/test";

/**
 * Token helpers for the FR-016 trust-score invariants.
 *
 * Retyped hex literals are rejected in review (D-6): every expected value is
 * resolved AT RUNTIME from the token source (:root custom properties), so a
 * later edit to a token flows through automatically and cannot be evaded by a
 * stale literal.
 */

/** Resolve CSS custom properties from :root at runtime. */
export async function readTokens(page: Page, names: string[]): Promise<Record<string, string>> {
  return page.evaluate((ns) => {
    const cs = getComputedStyle(document.documentElement);
    const out: Record<string, string> = {};
    for (const n of ns) out[n] = cs.getPropertyValue(n).trim();
    return out;
  }, names);
}

/**
 * The GREEN RULE guard (D-6), run in-page over a subtree.
 *
 * Walks the root element and every descendant, plus ::before/::after, and
 * inspects EVERY paint channel (not `color` alone — that misses --success,
 * --success-soft, --verdict-surface, and the SVG stroke). Each colour is parsed
 * to RGBA by the browser and flagged when it either (a) exactly matches a
 * runtime-resolved token green, or (b) lands in the 120–175° hue band at
 * saturation ≥ 15% with alpha > 0 — the hue-band rule is what survives a NEW or
 * EDITED green token. Returns a list of human-readable violation strings; an
 * empty list means no green paint anywhere in the subtree.
 */
export async function scanSubtreeForGreen(page: Page, selector: string): Promise<string[]> {
  return page.evaluate((sel) => {
    const root = document.querySelector(sel);
    if (!root) return [`GREEN-RULE: no element matched ${sel}`];

    const PAINT = [
      "color",
      "background-color",
      "background-image",
      "border-top-color",
      "border-right-color",
      "border-bottom-color",
      "border-left-color",
      "outline-color",
      "box-shadow",
      "text-decoration-color",
      "caret-color",
      "accent-color",
      "fill",
      "stroke",
    ];

    const parse = (val: string): { r: number; g: number; b: number; a: number } | null => {
      if (!val) return null;
      const probe = document.createElement("span");
      probe.style.color = "";
      probe.style.color = val;
      if (!probe.style.color) return null;
      document.body.appendChild(probe);
      const c = getComputedStyle(probe).color;
      probe.remove();
      const m = c.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const parts = m[1].split(/[,\s/]+/).map((x) => parseFloat(x));
      if (parts.length < 3 || parts.some((n, i) => i < 3 && Number.isNaN(n))) return null;
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 && !Number.isNaN(parts[3]) ? parts[3] : 1 };
    };

    const rootStyle = getComputedStyle(document.documentElement);
    const tokenGreens = ["--c-green", "--success", "--verdict-surface"]
      .map((n) => parse(rootStyle.getPropertyValue(n).trim()))
      .filter((x): x is { r: number; g: number; b: number; a: number } => x !== null);

    const hueSat = (r: number, g: number, b: number) => {
      r /= 255;
      g /= 255;
      b /= 255;
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      const l = (max + min) / 2;
      const d = max - min;
      if (d === 0) return { h: 0, s: 0 };
      const s = d / (1 - Math.abs(2 * l - 1));
      let h = 0;
      if (max === r) h = (((g - b) / d) % 6 + 6) % 6;
      else if (max === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      h *= 60;
      return { h, s };
    };

    const violations: string[] = [];
    const check = (val: string, where: string) => {
      const matches = val.match(/rgba?\([^)]+\)/g) || [];
      for (const c of matches) {
        const p = parse(c);
        if (!p || p.a <= 0) continue;
        for (const tg of tokenGreens) {
          if (Math.abs(p.r - tg.r) < 2 && Math.abs(p.g - tg.g) < 2 && Math.abs(p.b - tg.b) < 2) {
            violations.push(`${where}: exact token-green ${c}`);
          }
        }
        const { h, s } = hueSat(p.r, p.g, p.b);
        if (h >= 120 && h <= 175 && s >= 0.15) {
          violations.push(`${where}: green-hue ${c} (h=${h.toFixed(0)}° s=${s.toFixed(2)})`);
        }
      }
    };

    const els: Element[] = [root, ...Array.from(root.querySelectorAll("*"))];
    for (const el of els) {
      const label = (el.getAttribute("class") || el.tagName).toString();
      for (const pseudo of ["", "::before", "::after"]) {
        const cs = getComputedStyle(el, pseudo || undefined);
        for (const prop of PAINT) {
          const v = cs.getPropertyValue(prop);
          if (v) check(v, `${label}${pseudo} ${prop}`);
        }
      }
    }
    return violations;
  }, selector);
}
