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
 * but NOT one over a subject whose SHAPE cannot reach live application state,
 * which is a tautology and was a real hole. See `isLiveSubject`: that test is
 * DEFAULT-DENY on the node type, because the blocklist that preceded it was
 * defeated by `expect("lit" as string)`.
 *
 * KNOWN LIMITS, stated rather than implied. None is closed here.
 *
 *  1. Element-presence is not text-non-emptiness. `expect(surface).toBeVisible()`
 *     partnered with `expect(text).not.toMatch(/x/)` passes even if `text` is
 *     empty. Same-subject matching would close it and is markedly more
 *     false-alarm-prone; this is a shape check, not a proof.
 *
 *  2. `toBeTruthy()` over a Locator or Page is accepted as a partner and proves
 *     nothing: those objects are truthy whether or not they match anything.
 *     (Measured on the parked #226 branch in the Playwright runner; INHERITED
 *     here, not re-measured. Recorded in ADR-0059's Consequences.)
 *
 *  3. `toHaveAttribute` is accepted with no argument inspection at all, so
 *     `toHaveAttribute()` — which names nothing — counts as proof. Tightening
 *     it is a separate widening of the partner definition, not this concern.
 *
 *  4. CI runs this guard in `--base` (changed-specs) mode only
 *     (`.github/workflows/e2e.yml`), and that step is gated on
 *     `github.event_name == 'pull_request'`, so a spec no pull request touches
 *     is never re-checked. That is why the argument-shape property lives in
 *     `tests/unit/test_negative_assertion_guard.py` rather than in an
 *     `--all` run.
 *
 *  5. `--all` mode lists files with `git ls-files`, so gitignored scratch specs
 *     (e.g. `e2e/tests/review/`) are outside any count it prints. Read every
 *     such number as tracked-only.
 *
 *  6. `isLiveSubject` is default-deny on the NODE TYPE, not on reachability.
 *     It answers "could an expression of this shape reach live state?", never
 *     "does THIS expression reach live state?" — that needs the dataflow
 *     analysis ADR-0059 rejects. So a dead value wrapped in any call, or bound
 *     to a name, is accepted. MEASURED against a genuinely vacuous negative in
 *     the same test, each of these silences it and the guard exits 0:
 *     `expect(String("lit")).toBeTruthy()`, `expect(Boolean(1)).toBeTruthy()`,
 *     `expect(Object.keys({ a: 1 }).length).toBeGreaterThan(0)`, and
 *     `const dead = "x"; expect(dead).toBeTruthy()`. This is not a regression —
 *     the blocklist that preceded it accepted the same shapes — but the
 *     predicate closes the TSAsExpression family, not the tautology family.
 *
 *  7. Only the literal identifier `expect`, and only lexically inside a
 *     `test()` body. `const e = expect; await e(x).toBeHidden();` is invisible,
 *     and so is a negative moved into a helper function the test calls. Both
 *     measured at zero violations. `it.only(...)` / `it.skip(...)` bodies are
 *     also unwalked: the modifier recogniser requires the object to be `test`,
 *     and accepts `it` only bare.
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
  // #148: found missing by running a 9-assertion absence fixture through the
  // shipped checker — only 1 of 9 was reported.
  "toHaveClass",
  "toHaveAttribute",
  "toBeInViewport",
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

/**
 * #226: THE PROPERTY NAME OF A MEMBER EXPRESSION, however it is spelled.
 *
 * Every read of a member property used to be `node.property.name`. For a
 * COMPUTED property (`expect(x)["not"]`) the property node is a `Literal`, so
 * `.name` is `undefined` and the read silently produced nothing — at EVERY
 * member-property read in the file, in both failure directions at once
 * (`git show origin/main:$0 | grep -c '\.property\.name'` counts them), and
 * this function is now the only way any of them is spelled. Measured on the checker
 * before this change: `expect(x)["not"].toBeVisible()` counted as a POSITIVE
 * partner, `expect(b)["toBeHidden"]()` was invisible entirely, and
 * `expect["soft"](b).toBeVisible()` was not recognised as a partner, so an
 * honest test was reported.
 *
 * Three spellings are static text and are resolved: a dot property, a string
 * `Literal`, and a `TemplateLiteral` with no interpolations. Anything else —
 * a binding (`expect(x)[k]`), a call, an interpolated template — needs
 * dataflow analysis this checker does not have and should not grow, so it
 * returns UNRESOLVED and the caller fails closed. See ADR-0059 and ADR-0047.
 */
const UNRESOLVED = Symbol("unresolved-property");

/** What the report calls a matcher it could not read. A violation naming
 * `undefined` is one the author cannot act on. */
const COMPUTED = "<computed>";

function propertyName(node) {
  if (!node || node.type !== "MemberExpression") return UNRESOLVED;
  const property = node.property;
  if (!property || typeof property.type !== "string") return UNRESOLVED;
  if (!node.computed) return property.type === "Identifier" ? property.name : UNRESOLVED;
  if (property.type === "Literal" && typeof property.value === "string") return property.value;
  if (property.type === "TemplateLiteral" && property.expressions.length === 0) {
    return property.quasis.map((q) => (q.value.cooked == null ? "" : q.value.cooked)).join("");
  }
  return UNRESOLVED;
}

/** `expect(x).not.toEqual([])` -> { matcher, negated, args }, or null. */
function assertionOf(node) {
  if (node.type !== "CallExpression" || node.callee.type !== "MemberExpression") return null;
  const named = propertyName(node.callee);
  // `unresolved` travels with the assertion: `classify` treats it as a
  // negative that can never be a partner, so both halves lean toward a red
  // gate rather than toward silence.
  let unresolved = named === UNRESOLVED;
  const matcher = unresolved ? COMPUTED : named;
  if (!matcher) return null;
  // Walk back down the member chain looking for `expect(...)` and a `.not`.
  let cursor = node.callee.object;
  let negated = false;
  const built = (subject) => ({ matcher, negated, unresolved, args: node.arguments, subject });
  while (cursor) {
    if (cursor.type === "MemberExpression") {
      const step = propertyName(cursor);
      if (step === UNRESOLVED) unresolved = true;
      else if (step === "not") negated = true;
      cursor = cursor.object;
    } else if (cursor.type === "ChainExpression") {
      cursor = cursor.expression;
    } else if (cursor.type === "CallExpression") {
      if (cursor.callee.type === "Identifier" && cursor.callee.name === "expect") {
        return built(cursor.arguments[0]);
      }
      // #148: `expect.soft(...)` and `expect.poll(...)` are the same claim
      // as `expect(...)` for this guard's purposes. The chain root for
      // these is a MemberExpression (`expect.soft`), not the bare
      // Identifier `expect` — without this, every soft/poll assertion was
      // invisible in BOTH directions: a vacuous one passed, and a genuine
      // one never counted as a partner either.
      if (
        cursor.callee.type === "MemberExpression" &&
        cursor.callee.object.type === "Identifier" &&
        cursor.callee.object.name === "expect"
      ) {
        const root = propertyName(cursor.callee);
        if (root === "soft" || root === "poll") return built(cursor.arguments[0]);
        if (root === UNRESOLVED) {
          unresolved = true;
          return built(cursor.arguments[0]);
        }
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
/** #148: an explicit empty-string literal argument — `toHaveText("")`,
 * `toEqual("")` — is as much an emptiness claim as `toHaveCount(0)`. */
const isEmptyStringLiteral = (arg) =>
  arg && arg.type === "Literal" && typeof arg.value === "string" && arg.value.length === 0;
/**
 * #226: THE ARGUMENT HALF OF THE ACCEPTANCE PREDICATE.
 *
 * An argument counts as proof only if SATISFYING IT REQUIRES THE SUBJECT TO
 * CARRY SOMETHING — in the PLAIN direction. Under `.not` the predicate is
 * weaker and this comment used to overstate it: `.not.toHaveText("placeholder")`
 * is satisfied by an element that exists and is EMPTY, so it proves PRESENCE,
 * not content. (It does prove presence: measured in real Chromium on the parked
 * #226 branch, `.not.toHaveText` FAILS against a locator matching no element.)
 * Tightening the `.not` branch is a separate widening of the partner
 * definition, not this concern.
 *
 * The predicate this replaced had three accept clauses, two
 * of them unconditional on content: ANY template literal (`` `` `` included)
 * and ANY regex literal (`/(?:)/` included). So several spellings of "this
 * element is empty" were accepted as proof that it is not.
 *
 * PLAYWRIGHT'S OWN TEXT NORMALIZER, copied rather than re-derived. "Which
 * characters does Playwright treat as nothing?" is a question about an
 * UPSTREAM, and AGENTS.md rule 8c says such a mitigation is worth exactly as
 * much as your MEASUREMENT of that upstream. An earlier attempt reasoned about
 * Unicode instead, arrived at `[\u200B-\u200D\uFEFF]`, and got U+00AD SOFT
 * HYPHEN wrong in the dangerous direction.
 *
 * READ from the installed playwright-core (1.61.1, the version pinned in
 * `e2e/package-lock.json`), `lib/coreBundle.js:518`:
 *
 *     function normalizeWhiteSpace(text2) {
 *       ... text2.replace(/[\u200B\u00AD]/g, "").trim().replace(/\s+/g, " ")
 *     }
 *
 * Exactly two characters are STRIPPED, then JavaScript `\s` is trimmed and
 * collapsed. `tests/unit/test_negative_assertion_guard.py` re-reads that file
 * on every run and fails if upstream changes the class under this copy.
 * The real-Chromium agreement figures for this rule are INHERITED from the
 * parked #226 branch and were not re-measured here.
 */
export const PLAYWRIGHT_STRIPS = /[\u200B\u00AD]/g;
const normalizeWhiteSpace = (text) => text.replace(PLAYWRIGHT_STRIPS, "").trim().replace(/\s+/g, " ");

/** Text that survives Playwright's normalizer. If it does not survive, an
 * element carrying nothing normalises to the same thing and satisfies the
 * assertion — so the argument proves nothing. */
const isNonBlankText = (value) => typeof value === "string" && normalizeWhiteSpace(value).length > 0;

/** The text a template literal contributes NO MATTER WHAT its interpolations
 * evaluate to. `` `${v}` `` contributes nothing knowable here; `` `ok ${v}` ``
 * always contributes "ok ". */
const staticTemplateText = (node) =>
  node.quasis.map((q) => (q.value.cooked == null ? "" : q.value.cooked)).join("");

// A regex proves content only if it CANNOT match the empty string. `/(?:)/`,
// `/^$/`, `/a?/`, `/x*/` and `/x|/` all can, and all pass against an empty
// element. The question is asked of the engine rather than pattern-matched on
// the source, so there is no spelling of "matches empty" left to enumerate.
// `g`/`y` are stripped because `lastIndex` makes `.test` stateful.
function regexRejectsEmptyString(node) {
  try {
    return !new RegExp(node.regex.pattern, node.regex.flags.replace(/[gy]/g, "")).test("");
  } catch {
    return false; // cannot be evaluated here, so it cannot be counted as proof
  }
}

/**
 * NO ARRAYS, in either direction. A rejected earlier attempt at #226 widened
 * this to accept an ArrayExpression whose elements were `.some()` non-empty.
 * `.not.toHaveText(["a"])` PASSES against a locator matching ZERO elements, so
 * it proves nothing. The plain direction's `toHaveText(["a"])` IS a genuine
 * liveness proof, but the two directions share this predicate and the safe
 * intersection is "no arrays". (Both runtime verdicts are INHERITED from that
 * branch's real-Chromium measurements, not re-measured here.)
 */
function provesNonEmptyContent(arg) {
  if (!arg) return false;
  if (arg.type === "Literal" && arg.regex) return regexRejectsEmptyString(arg);
  if (arg.type === "Literal") return isNonBlankText(arg.value);
  if (arg.type === "TemplateLiteral") return isNonBlankText(staticTemplateText(arg));
  return false;
}

/**
 * #226: THE SUBJECT HALF OF THE PREDICATE, and it is DEFAULT-DENY.
 *
 * `expect(true).toBeTruthy()` proves nothing about the code under test.
 * Adversarial review confirmed this WAS the hole: one such line silenced a
 * vacuous negative with no reason comment and no reviewer signal.
 *
 * The first fix for that was a BLOCKLIST — reject `Literal`, `TemplateLiteral`,
 * `ArrayExpression`, `ObjectExpression`, accept everything else. A blocklist is
 * defeated by any node type nobody thought of, and the exact case its own
 * comment claimed to close was defeated by adding ` as string`:
 * `expect("lit" as string).toBeTruthy()` is a `TSAsExpression`, so it was
 * accepted. That is the anti-pattern this issue exists to remove, sitting
 * inside the fix for it.
 *
 * So the question is inverted. Not "is this one of the shapes I know to be
 * dead?" but "could an expression OF THIS SHAPE reach live application state?"
 * — answered by walking to the root, and answered NO for anything
 * unrecognised. A node type that appears in the future is REJECTED, which costs
 * a conservative false positive a reviewer sees, instead of silently granting
 * an evasion nobody measured.
 *
 * WHAT THIS DOES NOT CLOSE, stated because the sentence above invites the
 * stronger reading: the question is about the SHAPE, never about the value. A
 * dead literal wrapped in a call (`expect(String("lit"))`) or bound to a name
 * is a `CallExpression` / `Identifier` and is accepted. Closing that needs
 * dataflow analysis ADR-0059 rejects; see KNOWN LIMIT 6 at the top of this
 * file for the measured list.
 *
 * The accept set below came from a census of
 * `expect()` subjects across the committed specs, taken on the parked #226
 * branch; it is INHERITED, not re-measured here. Re-derive it rather than
 * trusting it: `node e2e/tools/check-negative-assertions.mjs --all`.
 */
function isLiveSubject(node, depth = 0) {
  if (!node || typeof node.type !== "string" || depth > 24) return false;
  switch (node.type) {
    // Roots that can carry live state: a binding, or a thunk that runs code
    // (`expect.poll(() => locator.count())`).
    case "Identifier":
    case "ThisExpression":
    case "ArrowFunctionExpression":
    case "FunctionExpression":
      return true;
    // `page.locator(...)` — live iff what it is reached FROM is live.
    // `"lit".repeat(3)` is not.
    case "MemberExpression":
      return isLiveSubject(node.object, depth + 1);
    case "CallExpression":
      return isLiveSubject(node.callee, depth + 1);
    // Transparent wrappers: they change the type, never the value.
    case "AwaitExpression":
      return isLiveSubject(node.argument, depth + 1);
    case "ChainExpression":
    case "TSAsExpression":
    case "TSSatisfiesExpression":
    case "TSNonNullExpression":
    case "TSTypeAssertion":
    case "TSInstantiationExpression":
      return isLiveSubject(node.expression, depth + 1);
    // Composites: live if EITHER operand can be.
    case "LogicalExpression":
    case "BinaryExpression":
      return isLiveSubject(node.left, depth + 1) || isLiveSubject(node.right, depth + 1);
    // `new Set(liveArray).size` reaches live state through its ARGUMENT, the
    // same way `items.length + 1` does through an operand — and the plain-call
    // spelling `Array.from(liveArray)` was already accepted via
    // `CallExpression`, so rejecting the `new` form was an asymmetry, not a
    // policy. MEASURED: it demoted one committed assertion,
    // `e2e/tests/ui-parity/parity-behavior.spec.ts:1412`
    // (`expect(new Set(bgs).size, ...).toBe(4)`), from partner to non-partner.
    // Argument-driven, so `new Date()` — no arguments — stays dead.
    case "NewExpression":
      return (node.arguments || []).some((argument) => isLiveSubject(argument, depth + 1));
    default:
      return false; // DEFAULT DENY. An unrecognised shape is not a live subject.
  }
}

function classify(a) {
  const [first] = a.args;
  // #226, FAIL CLOSED. An assertion whose chain carries a property this parser
  // cannot read is treated as a negative: it demands a partner, and it never
  // supplies one. ADR-0047 already settled the direction for this class of
  // static detector — resolve an ambiguous case toward a RED gate. Measured
  // cost (ADR-0059): it only bites in a test with no positive partner at all.
  if (a.unresolved) return "negative";
  if (a.negated) {
    // #226: a partner over a dead subject is a tautology in BOTH directions.
    // The `.not` branch never consulted this at all, so
    // `expect("lit").not.toHaveText("x")` — which examines no code — silenced a
    // real negative.
    if (!isLiveSubject(a.subject)) {
      return NEGATIVE_UNDER_NOT.has(a.matcher) ? "negative" : "other";
    }
    // `.not.toHaveCount(0)` / `.not.toBeNull()` are POSITIVE: they assert presence.
    if (a.matcher === "toHaveCount" && isZero(first)) return "positive";
    if (a.matcher === "toBeNull" || a.matcher === "toBeUndefined") return "positive";
    // `.not.toHaveText("—")` asserts the surface is not the empty placeholder.
    if (a.matcher === "toHaveText" && provesNonEmptyContent(first)) return "positive";
    if (NEGATIVE_UNDER_NOT.has(a.matcher)) return "negative";
    return "other";
  }
  // #148: `toStrictEqual` joins `toEqual` for the empty-array/empty-string
  // check — both are full-equality matchers making the same emptiness claim.
  if (
    (a.matcher === "toEqual" || a.matcher === "toStrictEqual") &&
    (isEmptyArray(first) || isEmptyStringLiteral(first))
  )
    return "negative";
  if (a.matcher === "toHaveText" && isEmptyStringLiteral(first)) return "negative";
  // #148: `toBe` dropped from this zero-check — `expect(scrollTop).toBe(0)`
  // is a legitimate generic numeric-equality assertion, not an emptiness
  // claim the way `toHaveCount(0)`/`toHaveLength(0)` specifically are.
  if ((a.matcher === "toHaveCount" || a.matcher === "toHaveLength") && isZero(first)) return "negative";
  if (a.matcher === "toBeNull" || a.matcher === "toBeFalsy" || a.matcher === "toBeUndefined") return "negative";
  // #148: the most idiomatic Playwright absence matchers — found completely
  // absent from this function despite being at least as common as the
  // `.not`-qualified forms above.
  if (a.matcher === "toBeHidden" || a.matcher === "toBeEmpty") return "negative";
  // A positive over a subject that cannot reach live state is a tautology, not
  // evidence. Default-deny: see `isLiveSubject`.
  if (!isLiveSubject(a.subject)) return "other";
  if (a.matcher === "toBeGreaterThan" && isZero(first)) return "positive";
  if (a.matcher === "toBeGreaterThanOrEqual" && isPositiveNumber(first)) return "positive";
  if ((a.matcher === "toHaveCount" || a.matcher === "toBe" || a.matcher === "toHaveLength") && isPositiveNumber(first))
    return "positive";
  if (a.matcher === "toBeVisible" || a.matcher === "toBeTruthy" || a.matcher === "toBeAttached") return "positive";
  if (a.matcher === "toHaveAttribute") return "positive";
  if (
    (a.matcher === "toContainText" || a.matcher === "toHaveText" || a.matcher === "toContain") &&
    provesNonEmptyContent(first)
  )
    return "positive";
  return "other";
}

const isFunctionLike = (node) =>
  node && (node.type === "ArrowFunctionExpression" || node.type === "FunctionExpression");

/** Is `node` the Identifier `name`? Used instead of a bare `.name` read so a
 * computed or wrapped object cannot be mistaken for the `test` global. */
const isNamed = (node, name) => Boolean(node) && node.type === "Identifier" && node.name === name;

const isTestCall = (node) =>
  node.type === "CallExpression" &&
  ((node.callee.type === "Identifier" && ["test", "it"].includes(node.callee.name)) ||
    (node.callee.type === "MemberExpression" &&
      isNamed(node.callee.object, "test") &&
      // #226: read through `propertyName`, so `test["only"](...)` is a test.
      // It was not, and the ENTIRE body of such a test went unwalked — every
      // assertion inside it invisible at once, the largest of the
      // computed-access evasions.
      ["only", "skip", "fixme"].includes(propertyName(node.callee))));

/**
 * #148 follow-up (found by adversarial review, same PR, self-fixed here):
 * the three-level chain (`test.describe.<modifier>(...)`) used to check
 * `property.name` against a hardcoded `["only", "skip"]` allowlist.
 * `.parallel`/`.serial` are real, documented Playwright modifiers that were
 * invisible as describe calls at all under that allowlist, so
 * `collectBeforeEachAssertions` never fired for them and their
 * `beforeEach`'s positive assertion never reached the tests inside — the
 * exact false-positive class this issue exists to close, on a different
 * modifier. Matching ANY `test.describe.X` chain (not enumerating modifier
 * names) is correct here: the only question this function answers is
 * "does this open a describe block", and every `test.describe.*` call does.
 */
const isDescribeCall = (node) =>
  node.type === "CallExpression" &&
  ((node.callee.type === "Identifier" && node.callee.name === "describe") ||
    (node.callee.type === "MemberExpression" &&
      isNamed(node.callee.object, "test") &&
      propertyName(node.callee) === "describe") ||
    (node.callee.type === "MemberExpression" &&
      node.callee.object.type === "MemberExpression" &&
      isNamed(node.callee.object.object, "test") &&
      propertyName(node.callee.object) === "describe"));

const isBeforeEachCall = (node) =>
  node.type === "CallExpression" &&
  ((node.callee.type === "Identifier" && node.callee.name === "beforeEach") ||
    (node.callee.type === "MemberExpression" &&
      isNamed(node.callee.object, "test") &&
      propertyName(node.callee) === "beforeEach"));

/**
 * #148: assertions inside a `test.beforeEach(...)` run before every test in
 * the SAME `describe` (Playwright semantics) — the flat walk this replaced
 * never associated them, so this extremely common "drive once, assert
 * per-test" layout was a guaranteed false positive (measured 15-25% of what
 * the guard flagged). A shallow walk: it stops at a nested `describe`/`test`
 * boundary, because that nested block's own `beforeEach` belongs to IT, not
 * to the assertions this call collects for its own siblings.
 */
function collectBeforeEachAssertions(describeBody) {
  const out = [];
  (function walk(node) {
    if (!node || typeof node.type !== "string") return;
    if (node.type === "CallExpression" && (isDescribeCall(node) || isTestCall(node))) return;
    if (node.type === "CallExpression" && isBeforeEachCall(node)) {
      const body = node.arguments.find(isFunctionLike);
      if (body) out.push(...collectAssertions(body));
      return;
    }
    for (const key of Object.keys(node)) {
      const child = node[key];
      if (Array.isArray(child)) child.forEach(walk);
      else if (child && typeof child.type === "string") walk(child);
    }
  })(describeBody);
  return out;
}

/** Every `test(...)`/`it(...)` call with its body node, plus the assertions
 * from any `test.beforeEach(...)` in an enclosing `describe` (accumulated
 * through nested describes, matching Playwright's own execution order). */
function testsIn(ast) {
  const found = [];
  (function walk(node, inheritedBeforeEach) {
    if (!node || typeof node.type !== "string") return;
    if (node.type === "CallExpression" && isDescribeCall(node)) {
      const describeBody = node.arguments.find(isFunctionLike);
      if (describeBody) {
        const combined = [...inheritedBeforeEach, ...collectBeforeEachAssertions(describeBody)];
        walk(describeBody, combined);
      }
      return;
    }
    if (node.type === "CallExpression" && isTestCall(node)) {
      const title = node.arguments[0];
      const body = node.arguments.find(isFunctionLike);
      if (body) {
        found.push({
          title: title && title.value ? String(title.value) : "<dynamic>",
          body,
          inheritedBeforeEach,
        });
      }
      return;
    }
    for (const key of Object.keys(node)) {
      const child = node[key];
      if (Array.isArray(child)) child.forEach((c) => walk(c, inheritedBeforeEach));
      else if (child && typeof child.type === "string") walk(child, inheritedBeforeEach);
    }
  })(ast, []);
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
  for (const { title, body, inheritedBeforeEach } of testsIn(ast)) {
    const assertions = collectAssertions(body);
    // #148: a positive partner in an enclosing `test.beforeEach` counts too
    // — Playwright runs it before every test in the same `describe`.
    const hasPositive =
      assertions.some((a) => a.kind === "positive") ||
      inheritedBeforeEach.some((a) => a.kind === "positive");
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
      violations.push({
        file,
        line: a.line,
        test: title,
        // An assertion whose chain could not be read is reported as
        // `<computed>` rather than by a matcher name that may be only half the
        // story — the author needs to see WHICH shape the guard refused.
        matcher: a.unresolved ? COMPUTED : `${a.negated ? "not." : ""}${a.matcher}`,
      });
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
