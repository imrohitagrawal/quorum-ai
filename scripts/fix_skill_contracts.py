#!/usr/bin/env python3
"""Fix missing skill contract sections in all SKILL.md files."""

import json
import re
from pathlib import Path

REQUIRED_SECTIONS = [
    "When to use",
    "When not to use",
    "Inputs",
    "Owned outputs",
    "Allowed tools",
    "Forbidden actions",
    "Procedure",
    "Quality bar",
    "Validation",
    "Handoff contract",
    "Stop conditions",
    "Examples",
    "Anti-examples",
]

SKILL_TEMPLATE = """
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
"""

def get_skill_name(file_path: Path) -> str:
    """Extract skill name from path."""
    return file_path.parent.name.replace("-", " ").replace("_", " ").title()

def get_when_to_use(content: str) -> str:
    """Extract or generate When to use section."""
    # Try to find existing content
    if "## When to use" in content:
        return ""
    
    skill_name = get_skill_name(Path("dummy.md"))
    return f"""## When to use

- When the user asks about {skill_name}
- When the task matches this skill's purpose
- When the context aligns with the skill's scope
"""

def get_when_not_to_use(content: str) -> str:
    """Extract or generate When not to use section."""
    if "## When not to use" in content:
        return ""
    
    return """## When not to use

- When the task requires a different skill
- When the scope exceeds this skill's purpose
- When the user asks about unrelated topics
"""

def fix_skill_file(file_path: Path) -> bool:
    """Fix a single SKILL.md file."""
    content = file_path.read_text(encoding="utf-8")
    
    # Check which sections are missing
    missing = [s for s in REQUIRED_SECTIONS if f"## {s}" not in content]
    
    if not missing:
        print(f"✓ {file_path} - already complete")
        return True
    
    print(f"Fixing {file_path} - missing: {missing}")
    
    # Add When to use and When not to use at the top if missing
    additions = []
    
    if "## When to use" not in content:
        additions.append(get_when_to_use(content))
    if "## When not to use" not in content:
        additions.append(get_when_not_to_use(content))
    
    # Append the rest of the template sections
    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in content:
            if section not in ["When to use", "When not to use"]:
                # Find the template section
                template_section = extract_section_from_template(SKILL_TEMPLATE, section)
                if template_section:
                    additions.append(template_section)
    
    if additions:
        # Find insertion point - before the last ## heading or at end
        lines = content.split('\n')
        
        # Find where to insert (before any section that's not in required list)
        insert_idx = len(lines)
        for i, line in enumerate(lines):
            if line.startswith('## '):
                section_name = line[3:].strip()
                if section_name not in REQUIRED_SECTIONS:
                    insert_idx = i
                    break
        
        new_content = '\n'.join(lines[:insert_idx]) + '\n\n' + '\n\n'.join(additions) + '\n\n' + '\n'.join(lines[insert_idx:])
        file_path.write_text(new_content, encoding="utf-8")
        return True
    
    return False

def extract_section_from_template(template: str, section_name: str) -> str:
    """Extract a section from the template."""
    pattern = f"## {section_name}\n(.*?)(?=\n## |\\Z)"
    match = re.search(pattern, template, re.DOTALL)
    return match.group(0) if match else ""

def main():
    skills_dir = Path(".agents/skills")
    fixed_count = 0
    
    for skill_dir in sorted(skills_dir.iterdir()):
        if skill_dir.is_dir():
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                if fix_skill_file(skill_file):
                    fixed_count += 1
    
    print(f"\nFixed {fixed_count} skill files")

if __name__ == "__main__":
    main()
