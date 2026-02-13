# Skill Tester

Systematically test skills against the current environment. Detect broken dependencies, version incompatibilities, stale references, and structural issues. Produce a PASS / PARTIAL / FAIL report for each skill with actionable fix descriptions.

## Overview

This skill validates all skills in your environment across five test categories:

- **T1 Dependency** - Check pip/brew/npm packages are importable or on PATH
- **T2 Syntax** - Verify Python scripts parse on system Python version
- **T3 Consistency** - Validate filename conventions and cross-skill references
- **T4 Runtime** - Confirm scripts execute without error
- **T5 Scenario** - Simulate skill triggers and verify workflows are followable

## Quick Start

```bash
/skill-tester              # Test all skills
/skill-tester pdf          # Test a single skill
/skill-tester --category T1  # Run only dependency checks
```

## Test Categories

| Category | What It Checks | Tool |
|----------|---------------|------|
| **T1 Dependency** | pip/brew/npm packages importable or on PATH | Bash |
| **T2 Syntax** | Python scripts parse on system Python version | Bash (`ast.parse`) |
| **T3 Consistency** | Filename conventions, stale references, frontmatter completeness | Grep, Glob |
| **T4 Runtime** | Scripts execute without error (dry-run / `--help`) | Bash |
| **T5 Scenario** | Simulate trigger from skill description, verify workflow is followable | Task (agent) |

## Scoring

- **PASS** - T1–T4 all green, T5 no blocking issues
- **PARTIAL** - T1–T4 have warnings or T5 found non-blocking gaps
- **FAIL** - Any T1–T4 hard failure (missing dep, syntax error, broken ref)

## Output

After testing, you'll receive:
- Summary table with results for each skill
- Detailed findings for each FAIL and PARTIAL skill
- Concrete fix suggestions
- Option to auto-fix detected issues

## Common Failure Patterns

| Pattern | Category | Auto-fixable? |
|---------|----------|--------------|
| pip package not installed | T1 | Yes — `pip3 install --user X` |
| brew tool missing | T1 | Yes — `brew install X` |
| Python 3.10+ syntax on 3.9 | T2 | Yes — match→if/elif |
| SKILL.md has TODO placeholders | T3 | No — needs content authoring |
| Stale cross-skill reference | T3 | Yes — remove or update |
| Script fails `--help` | T4 | Investigate — may be missing dep |

## Continuous Improvement

This skill evolves with each use. After every invocation, it records lessons to `lessons.md` for future refinement.

---

**Version:** 0.1.0
**Tools:** Task, Read, Glob, Grep, Bash
**License:** Standard usage rights
