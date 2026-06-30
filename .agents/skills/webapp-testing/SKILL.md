---
name: webapp-testing
description: Toolkit for interacting with and testing local web applications using Playwright. Supports verifying frontend functionality, debugging UI behavior, capturing browser screenshots, and viewing browser logs.
license: Complete terms in LICENSE.txt
---

# Web Application Testing

To test local web applications, write native Python Playwright scripts.

**Helper Scripts Available**:
- `scripts/with_server.py` - Manages server lifecycle (supports multiple servers)

**Always run scripts with `--help` first** to see usage. DO NOT read the source until you try running the script first and find that a customized solution is abslutely necessary. These scripts can be very large and thus pollute your context window. They exist to be called directly as black-box scripts rather than ingested into your context window.


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


## Decision Tree: Choosing Your Approach

```
User task → Is it static HTML?
    ├─ Yes → Read HTML file directly to identify selectors
    │         ├─ Success → Write Playwright script using selectors
    │         └─ Fails/Incomplete → Treat as dynamic (below)
    │
    └─ No (dynamic webapp) → Is the server already running?
        ├─ No → Run: python scripts/with_server.py --help
        │        Then use the helper + write simplified Playwright script
        │
        └─ Yes → Reconnaissance-then-action:
            1. Navigate and wait for networkidle
            2. Take screenshot or inspect DOM
            3. Identify selectors from rendered state
            4. Execute actions with discovered selectors
```

## Example: Using with_server.py

To start a server, run `--help` first, then use the helper:

**Single server:**
```bash
python scripts/with_server.py --server "npm run dev" --port 5173 -- python your_automation.py
```

**Multiple servers (e.g., backend + frontend):**
```bash
python scripts/with_server.py \
  --server "cd backend && python server.py" --port 3000 \
  --server "cd frontend && npm run dev" --port 5173 \
  -- python your_automation.py
```

To create an automation script, include only Playwright logic (servers are managed automatically):
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True) # Always launch chromium in headless mode
    page = browser.new_page()
    page.goto('http://localhost:5173') # Server already running and ready
    page.wait_for_load_state('networkidle') # CRITICAL: Wait for JS to execute
    # ... your automation logic
    browser.close()
```

## Reconnaissance-Then-Action Pattern

1. **Inspect rendered DOM**:
   ```python
   page.screenshot(path='/tmp/inspect.png', full_page=True)
   content = page.content()
   page.locator('button').all()
   ```

2. **Identify selectors** from inspection results

3. **Execute actions** using discovered selectors

## Common Pitfall

❌ **Don't** inspect the DOM before waiting for `networkidle` on dynamic apps
✅ **Do** wait for `page.wait_for_load_state('networkidle')` before inspection

## Best Practices

- **Use bundled scripts as black boxes** - To accomplish a task, consider whether one of the scripts available in `scripts/` can help. These scripts handle common, complex workflows reliably without cluttering the context window. Use `--help` to see usage, then invoke directly. 
- Use `sync_playwright()` for synchronous scripts
- Always close the browser when done
- Use descriptive selectors: `text=`, `role=`, CSS selectors, or IDs
- Add appropriate waits: `page.wait_for_selector()` or `page.wait_for_timeout()`

## Reference Files

- **examples/** - Examples showing common patterns:
  - `element_discovery.py` - Discovering buttons, links, and inputs on a page
  - `static_html_automation.py` - Using file:// URLs for local HTML
  - `console_logging.py` - Capturing console logs during automation