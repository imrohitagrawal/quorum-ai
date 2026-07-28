/**
 * Fail a CHANGED spec file whose negative assertion has no positive partner.
 *
 * Issue #131. The mutation gate reads Python only, so nothing checks that the
 * browser tests can fail. `docs/metrics/mutation-gate-study.md` §4 censused 158
 * escaped defects and found 144 of them (91%) structurally invisible to that
 * gate, with ~46% living in non-Python files — JavaScript, CSS and the
 * Playwright specs this guard covers. Three specs written in one session passed
 * against the exact bug they existed to catch.
 *
 * THE RULE
 *   A negative assertion needs a positive partner somewhere in the same
 *   `test()` — an assertion proving the thing being examined can be non-empty —
 *   unless the line carries `// no-positive-partner: <reason>`.
 *
 * WHY A REAL PARSER. `@typescript-eslint/parser` gives exact `test()`
 * boundaries and exact assertion nodes. A bracket-balancing scanner was the
 * first plan and was rejected: it ships with documented blind spots, i.e. a
 * guard that cannot see part of what it claims to check — the defect class this
 * whole exercise exists to remove.
 *
 * NO FAMILY ALLOWLIST. An earlier design exempted axe/console-error families by
 * variable name. That is gameable — name your array `violations` and you are
 * exempt — and it is the "gate on a whole-line substring" antipattern AGENTS.md
 * warns about. Instead, nothing is exempt and the PARTNER definition is honest:
 * a liveness assertion (the surface rendered, the list is non-empty) counts —
 * but NOT one over a literal subject, which is a tautology and was a real hole.
 * Measured with this tool over the whole corpus: 21 unpartnered sites across 7
 * files, and both known-vacuous tests are caught.
 *
 * KNOWN LIMIT, stated rather than implied: element-presence is not
 * text-non-emptiness. `expect(surface).toBeVisible()` partnered with
 * `expect(text).not.toMatch(/x/)` passes even if `text` is empty. Same-subject
 * matching would close it and is markedly more false-alarm-prone; this is a
 * shape check, not a proof.
 *
 * Usage:  node e2e/tools/check-negative-assertions.mjs [--base <ref>] [--all] [paths...]
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { parse } from "@typescript-eslint/parser";

const EXEMPTION = /\/\/\s*no-positive-partner:\s*(\S.*)$/;

/** Matchers that, under `.not`, assert absence. */
const NEGATIVE_UNDER_NOT = new Set([
  "toContain",
  "toContainText",
  "toMatch",
  "toBeVisible",
  "toHaveText",
  "toBeAttached",
  "toBeChecked",
]);

function run(cmd, args, { required = false } = {}) {
  try {
    return execFileSync(cmd, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  } catch (error) {
    if (required) {
      // FAIL CLOSED. Swallowing this printed "nothing to check" and exited 0 —
      // identical to a healthy PR that touched no specs, which is exactly the
      // silent-no-op failure this guard exists to prevent elsewhere.
      console.error(
        `negative-assertion guard: git ${args.join(" ")} failed. The base ref is ` +
          `unresolvable, so the changed-spec diff cannot be computed. Refusing to ` +
          `report success over an unknown set of files.\n${error.stderr || error.message}`
      );
      process.exit(2);
    }
    return "";
  }
}

/** Spec files changed vs `base`, plus uncommitted ones. Mirrors the mutation gate's scoping. */
function changedSpecs(base, repoRoot) {
  const seen = new Set();
  for (const [args, required] of [
    [["diff", "--name-only", `${base}...HEAD`, "--", "e2e"], true],
    [["diff", "--name-only", "HEAD", "--", "e2e"], false],
  ]) {
    for (const line of run("git", ["-C", repoRoot, ...args], { required }).split("\n")) {
      if (line.endsWith(".spec.ts")) seen.add(line.trim());
    }
  }
  return [...seen];
}

/** `expect(x).not.toEqual([])` -> { matcher, negated, args }, or null. */
function assertionOf(node) {
  if (node.type !== "CallExpression" || node.callee.type !== "MemberExpression") return null;
  const matcher = node.callee.property.name;
  if (!matcher) return null;
  // Walk back down the member chain looking for `expect(...)` and a `.not`.
  let cursor = node.callee.object;
  let negated = false;
  while (cursor) {
    if (cursor.type === "MemberExpression") {
      if (cursor.property.name === "not") negated = true;
      cursor = cursor.object;
    } else if (cursor.type === "CallExpression") {
      if (cursor.callee.type === "Identifier" && cursor.callee.name === "expect") {
        return { matcher, negated, args: node.arguments, subject: cursor.arguments[0] };
      }
      cursor = cursor.callee;
    } else if (cursor.type === "AwaitExpression") {
      cursor = cursor.argument;
    } else {
      return null;
    }
  }
  return null;
}

const isZero = (arg) => arg && arg.type === "Literal" && arg.value === 0;
const isEmptyArray = (arg) => arg && arg.type === "ArrayExpression" && arg.elements.length === 0;
const isPositiveNumber = (arg) => arg && arg.type === "Literal" && typeof arg.value === "number" && arg.value > 0;
/** A non-empty string/regex literal argument — proof the subject holds something. */
const isNonEmptyLiteral = (arg) =>
  arg &&
  ((arg.type === "Literal" && typeof arg.value === "string" && arg.value.length > 0) ||
    arg.type === "TemplateLiteral" ||
    (arg.type === "Literal" && arg.regex));

/**
 * `expect(true)`, `expect(1)`, `expect([1])` — a partner over a literal proves
 * nothing about the code under test. Adversarial review confirmed this WAS the
 * hole: `expect(true).toBeTruthy()` silenced a vacuous negative with no reason
 * comment and no reviewer signal, making the rule strictly MORE gameable than
 * the family allowlist it replaced.
 */
function isTautologicalSubject(subject) {
  if (!subject) return false;
  return (
    subject.type === "Literal" ||
    subject.type === "TemplateLiteral" ||
    subject.type === "ArrayExpression" ||
    subject.type === "ObjectExpression"
  );
}

function classify(a) {
  const [first] = a.args;
  if (a.negated) {
    // `.not.toHaveCount(0)` / `.not.toBeNull()` are POSITIVE: they assert presence.
    if (a.matcher === "toHaveCount" && isZero(first)) return "positive";
    if (a.matcher === "toBeNull" || a.matcher === "toBeUndefined") return "positive";
    // `.not.toHaveText("—")` asserts the surface is not the empty placeholder.
    if (a.matcher === "toHaveText" && isNonEmptyLiteral(first)) return "positive";
    if (NEGATIVE_UNDER_NOT.has(a.matcher)) return "negative";
    return "other";
  }
  if (a.matcher === "toEqual" && isEmptyArray(first)) return "negative";
  if ((a.matcher === "toHaveCount" || a.matcher === "toBe" || a.matcher === "toHaveLength") && isZero(first))
    return "negative";
  if (a.matcher === "toBeNull" || a.matcher === "toBeFalsy" || a.matcher === "toBeUndefined") return "negative";
  // A positive over a literal subject is a tautology, not evidence.
  if (isTautologicalSubject(a.subject)) return "other";
  if (a.matcher === "toBeGreaterThan" && isZero(first)) return "positive";
  if (a.matcher === "toBeGreaterThanOrEqual" && isPositiveNumber(first)) return "positive";
  if ((a.matcher === "toHaveCount" || a.matcher === "toBe" || a.matcher === "toHaveLength") && isPositiveNumber(first))
    return "positive";
  if (a.matcher === "toBeVisible" || a.matcher === "toBeTruthy" || a.matcher === "toBeAttached") return "positive";
  if (a.matcher === "toHaveAttribute") return "positive";
  if ((a.matcher === "toContainText" || a.matcher === "toHaveText" || a.matcher === "toContain") && isNonEmptyLiteral(first))
    return "positive";
  return "other";
}

/** Every `test(...)`/`it(...)` call with its body node. */
function testsIn(ast) {
  const found = [];
  (function walk(node) {
    if (!node || typeof node.type !== "string") return;
    if (
      node.type === "CallExpression" &&
      ((node.callee.type === "Identifier" && ["test", "it"].includes(node.callee.name)) ||
        (node.callee.type === "MemberExpression" &&
          node.callee.object.name === "test" &&
          ["only", "skip", "fixme"].includes(node.callee.property.name)))
    ) {
      const title = node.arguments[0];
      const body = node.arguments.find((a) => a && (a.type === "ArrowFunctionExpression" || a.type === "FunctionExpression"));
      if (body) found.push({ title: title && title.value ? String(title.value) : "<dynamic>", body });
    }
    for (const key of Object.keys(node)) {
      const child = node[key];
      if (Array.isArray(child)) child.forEach(walk);
      else if (child && typeof child.type === "string") walk(child);
    }
  })(ast);
  return found;
}

function collectAssertions(body) {
  const out = [];
  (function walk(node) {
    if (!node || typeof node.type !== "string") return;
    const a = assertionOf(node);
    if (a) out.push({ ...a, kind: classify(a), line: node.loc.start.line });
    for (const key of Object.keys(node)) {
      const child = node[key];
      if (Array.isArray(child)) child.forEach(walk);
      else if (child && typeof child.type === "string") walk(child);
    }
  })(body);
  return out;
}

export function checkSource(source, file) {
  const ast = parse(source, { loc: true, range: true, comment: true, ecmaVersion: "latest", sourceType: "module" });
  // Exemptions are matched against real COMMENT TOKENS, never raw line text.
  // Matching text let the marker be smuggled in a `test()` title or any string
  // literal on a preceding line, and let one annotation cover a second
  // assertion further down (both confirmed by adversarial review).
  const exemptionLines = new Map();
  for (const comment of ast.comments || []) {
    const match = EXEMPTION.exec(`//${comment.value}`);
    if (comment.type === "Line" && match) exemptionLines.set(comment.loc.start.line, false);
  }
  const violations = [];
  for (const { title, body } of testsIn(ast)) {
    const assertions = collectAssertions(body);
    const hasPositive = assertions.some((a) => a.kind === "positive");
    for (const a of assertions) {
      if (a.kind !== "negative" || hasPositive) continue;
      // The annotation may end the assertion's own line, or sit in a contiguous
      // comment block directly above it. Each annotation is CONSUMED once, so
      // one reason cannot silently cover a second assertion below it.
      let exempt = false;
      for (let probe = a.line; probe >= a.line - 3 && probe > 0; probe -= 1) {
        if (!exemptionLines.has(probe)) {
          if (probe < a.line) break; // a gap: this block does not reach us
          continue;
        }
        if (exemptionLines.get(probe)) break; // already spent on another assertion
        exemptionLines.set(probe, true);
        exempt = true;
        break;
      }
      if (exempt) continue;
      violations.push({ file, line: a.line, test: title, matcher: `${a.negated ? "not." : ""}${a.matcher}` });
    }
  }
  return violations;
}

function main() {
  const argv = process.argv.slice(2);
  const repoRoot = run("git", ["rev-parse", "--show-toplevel"]).trim() || process.cwd();
  const baseIndex = argv.indexOf("--base");
  const base = baseIndex === -1 ? "origin/main" : argv[baseIndex + 1];
  const explicit = argv.filter((a) => a.endsWith(".spec.ts"));

  let targets;
  if (explicit.length) targets = explicit;
  else if (argv.includes("--all")) {
    targets = run("git", ["-C", repoRoot, "ls-files", "e2e/**/*.spec.ts"]).split("\n").filter(Boolean);
  } else {
    targets = changedSpecs(base, repoRoot);
  }

  if (!targets.length) {
    console.log(`negative-assertion guard: no changed spec files vs ${base} — nothing to check`);
    return 0;
  }

  const violations = [];
  for (const file of targets) {
    const abs = path.isAbsolute(file) ? file : path.join(repoRoot, file);
    let source;
    try {
      source = readFileSync(abs, "utf8");
    } catch {
      continue; // deleted in this diff
    }
    violations.push(...checkSource(source, file));
  }

  console.log(`negative-assertion guard: checked ${targets.length} changed spec file(s) vs ${base}`);
  if (!violations.length) return 0;

  console.error(
    `\n${violations.length} negative assertion(s) with no positive partner in the same test:\n`
  );
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line}  ${v.matcher}`);
    console.error(`      test: ${v.test}`);
  }
  console.error(
    "\nA negative assertion proves nothing if the thing it examines can be empty.\n" +
      "Add an assertion in the same test proving the subject exists — e.g.\n" +
      "  await expect(page.locator('#result')).toBeVisible();\n" +
      "  expect(items.length).toBeGreaterThan(0);\n" +
      "or, if absence really is the whole point, annotate the line:\n" +
      "  // no-positive-partner: <why this cannot have one>\n"
  );
  return 1;
}

if (import.meta.url === `file://${process.argv[1]}`) process.exit(main());
