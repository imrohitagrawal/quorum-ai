---
name: e2e-testing-patterns
description: Master end-to-end testing with Playwright and Cypress to build reliable test suites that catch bugs, improve confidence, and enable fast deployment. Use when implementing E2E tests, debugging flaky tests, or establishing testing standards.
---

# E2E Testing Patterns

Build reliable, fast, and maintainable end-to-end test suites that provide confidence to ship code quickly and catch regressions before users do.


## When to use

- When the user asks about 
- When the task matches this skill's purpose
- When the context aligns with the skill's scope


## When not to use

- When the task requires a different skill
- When the scope exceeds this skill's purpose
- When the user asks about unrelated topics


## Inputs

- **Context** (required): The task or query being addressed
- **Optional metadata**: Additional parameters or constraints


## Owned outputs

- **Analysis results**: Findings and recommendations
- **Code changes**: Implementation if applicable
- **Documentation**: Updates to relevant docs


## Allowed tools

- `Bash` — Execute commands as specified in skill permissions
- `Read` — Read files as needed for context
- `Edit` — Make targeted edits to files
- `Write` — Create new files when needed
- `Grep` — Search for patterns in code
- `Glob` — Find files matching patterns


## Forbidden actions

- **Bypass permissions**: Never use tools not listed in allowed tools
- **Force operations**: Never force pushes, delete operations without confirmation
- **External services**: Never access services outside the project scope
- **Credential exposure**: Never log or expose sensitive data


## Procedure

1. **Understand the request**: Parse the task and identify scope
2. **Gather context**: Read relevant files and understand the codebase
3. **Execute task**: Perform the requested action
4. **Verify results**: Ensure output meets quality bar
5. **Document changes**: Update relevant documentation


## Quality bar

- All changes must compile/run without errors
- Code must follow project conventions
- Tests must pass for modified code
- Documentation must be updated alongside code


## Validation

- Run relevant tests to verify changes
- Check that no regressions are introduced
- Verify code style compliance


## Handoff contract

- **To reviewer**: Provide clear summary of changes
- **To CI**: Ensure all checks pass
- **To developer**: Report any issues found during task


## Stop conditions

- Task completed successfully
- User cancels the request
- Error prevents completion (report to user)
- Resource limits exceeded (report to user)


## Examples

### Example 1: Simple Task
**Input**: "Fix the bug in auth.py"
**Output**: "Fixed the authentication bug by adding null check. Changes: auth.py:45."

### Example 2: Complex Task
**Input**: "Refactor the payment module"
**Output**: "Refactored payment module into 3 smaller modules. Added tests. All checks pass."


## Anti-examples

### Anti-example 1: Incomplete Work
**Bad**: "Made some changes but tests don't pass yet."
**Good**: "Changes complete. All 15 tests pass. Ready for review."

### Anti-example 2: Scope Creep
**Bad**: "Fixed the bug but also rewrote the whole auth system."
**Good**: "Fixed the reported bug. Separate refactoring tracked in ISSUE-123."


## When to Use This Skill

- Implementing end-to-end test automation
- Debugging flaky or unreliable tests
- Testing critical user workflows
- Setting up CI/CD test pipelines
- Testing across multiple browsers
- Validating accessibility requirements
- Testing responsive designs
- Establishing E2E testing standards

## Core Concepts

### 1. E2E Testing Fundamentals

**What to Test with E2E:**

- Critical user journeys (login, checkout, signup)
- Complex interactions (drag-and-drop, multi-step forms)
- Cross-browser compatibility
- Real API integration
- Authentication flows

**What NOT to Test with E2E:**

- Unit-level logic (use unit tests)
- API contracts (use integration tests)
- Edge cases (too slow)
- Internal implementation details

### 2. Test Philosophy

**The Testing Pyramid:**

```
        /\
       /E2E\         ← Few, focused on critical paths
      /─────\
     /Integr\        ← More, test component interactions
    /────────\
   /Unit Tests\      ← Many, fast, isolated
  /────────────\
```

**Best Practices:**

- Test user behavior, not implementation
- Keep tests independent
- Make tests deterministic
- Optimize for speed
- Use data-testid, not CSS selectors

## Detailed patterns and worked examples

Detailed pattern documentation lives in `references/details.md`. Read that file when the navigation tier above is insufficient.

## Best Practices

1. **Use Data Attributes**: `data-testid` or `data-cy` for stable selectors
2. **Avoid Brittle Selectors**: Don't rely on CSS classes or DOM structure
3. **Test User Behavior**: Click, type, see - not implementation details
4. **Keep Tests Independent**: Each test should run in isolation
5. **Clean Up Test Data**: Create and destroy test data in each test
6. **Use Page Objects**: Encapsulate page logic
7. **Meaningful Assertions**: Check actual user-visible behavior
8. **Optimize for Speed**: Mock when possible, parallel execution

```typescript
// ❌ Bad selectors
cy.get(".btn.btn-primary.submit-button").click();
cy.get("div > form > div:nth-child(2) > input").type("text");

// ✅ Good selectors
cy.getByRole("button", { name: "Submit" }).click();
cy.getByLabel("Email address").type("user@example.com");
cy.get('[data-testid="email-input"]').type("user@example.com");
```

## Common Pitfalls

- **Flaky Tests**: Use proper waits, not fixed timeouts
- **Slow Tests**: Mock external APIs, use parallel execution
- **Over-Testing**: Don't test every edge case with E2E
- **Coupled Tests**: Tests should not depend on each other
- **Poor Selectors**: Avoid CSS classes and nth-child
- **No Cleanup**: Clean up test data after each test
- **Testing Implementation**: Test user behavior, not internals

## Debugging Failing Tests

```typescript
// Playwright debugging
// 1. Run in headed mode
npx playwright test --headed

// 2. Run in debug mode
npx playwright test --debug

// 3. Use trace viewer
await page.screenshot({ path: 'screenshot.png' });
await page.video()?.saveAs('video.webm');

// 4. Add test.step for better reporting
test('checkout flow', async ({ page }) => {
    await test.step('Add item to cart', async () => {
        await page.goto('/products');
        await page.getByRole('button', { name: 'Add to Cart' }).click();
    });

    await test.step('Proceed to checkout', async () => {
        await page.goto('/cart');
        await page.getByRole('button', { name: 'Checkout' }).click();
    });
});

// 5. Inspect page state
await page.pause();  // Pauses execution, opens inspector
```
