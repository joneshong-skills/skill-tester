---
name: skill-tester
description: >-
  This skill should be used when the user asks to "test all skills",
  "run skill tests", "validate my skills", "check skill health",
  "skill 測試", "測試 skill", "跑一次 skill 驗證", "skill 健康檢查",
  mentions skill testing or validation, or discusses verifying that
  skills work correctly in the current environment.
version: 0.2.0
tools: Task, Read, Glob, Grep, Bash, sandbox_execute
argument-hint: "skill name or 'all' (default: all)"
---

# Skill Tester

Systematically test skills against the current environment. Detect broken dependencies,
version incompatibilities, stale references, and structural issues. Produce a PASS /
PARTIAL / FAIL report for each skill with actionable fix descriptions.

## Agent Delegation

Delegate test execution to `worker` agent.

## Test Categories

| # | Category | What It Checks | Tool |
|---|----------|---------------|------|
| T1 | **Dependency** | pip/brew/npm packages importable or on PATH | Bash |
| T2 | **Syntax** | Python scripts parse on system Python version | Bash (`ast.parse`) |
| T3 | **Consistency** | Filename conventions, stale cross-skill references, frontmatter completeness | Grep, Glob |
| T4 | **Runtime** | Scripts execute without error (dry-run / `--help`) | Bash |
| T5 | **Scenario** | Simulate a trigger from the skill description, verify workflow is followable | Task (agent) |

### Scoring

```
PASS    = T1–T4 all green, T5 no blocking issues
PARTIAL = T1–T4 have warnings or T5 found non-blocking gaps
FAIL    = Any T1–T4 hard failure (missing dep, syntax error, broken ref)
```

## Workflow

### Step 0 — Enumerate Skills

> **Sandbox acceleration**: T1–T4 automated checks run in `sandbox_execute` — `~/.claude/` imports are now supported.
>
> Preferred (Sandbox):
> ```python
> import sys; sys.path.insert(0, '/Users/joneshong/.claude/skills/skill-tester/scripts')
> import scan_env, gen_report
> env_results = scan_env.run_all()
> report = gen_report.aggregate(env_results)
> output(report)
> ```
>
> Fallback (Bash):
> ```bash
> ~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/scan_env.py
> ~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/gen_report.py --input results.json
> ```

```bash
~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/scan_env.py
```

Produces a JSON list of all skills with paths and detected dependency types.
If the user specified a skill name, filter to that skill only.

### Step 1 — Automated Checks (scan_env.py)

The script runs T1–T4 per skill automatically:

**T1 Dependency** — Parse SKILL.md and scripts for:
- `import X` / `from X import` → check `~/.local/bin/python3 -c "import X"`
- `pip install X` in docs → check `pip3 show X`
- `brew install X` / `which X` in docs → check `which X`
- `npm install X` in docs → check `npm list -g X`

**T2 Syntax** — For each `*.py` in `scripts/`:
- `~/.local/bin/python3 -c "import ast; ast.parse(open('file.py').read())"`
- Grep for Python 3.10+ patterns: `match `, `X | Y` type hints (outside strings)

**T3 Consistency** —
- Frontmatter has `name` and `description` (not TODO)
- `description` contains at least one quoted trigger phrase
- `tools:` frontmatter lists tools actually referenced in the body
- All referenced files mentioned in SKILL.md actually exist on disk
- No references to skills that don't exist in `~/.claude/skills/`
- README filenames follow convention (`README.zh.md` not `README.zh-TW.md`)

**T4 Runtime** — For scripts with `argparse` or `if __name__`:
- Run with `--help` flag (should exit 0)
- Run with `--version` if supported

### Step 2 — Scenario Tests (Parallel Agents)

For each skill, dispatch a Task agent (`subagent_type=general-purpose`) that:

1. Reads the skill's SKILL.md
2. Based on the `description` field, crafts a realistic user request
3. Mentally walks through the documented workflow step-by-step
4. Checks whether each step is actionable given the environment:
   - Are referenced tools available?
   - Do file paths and commands make sense?
   - Are there logical gaps or missing fallbacks?
5. Returns: status (PASS/PARTIAL/FAIL), issues list, suggested fixes

**Batching**: Test at most **6 skills per parallel batch** to avoid context overflow.
Wait for a batch to complete before starting the next.

**Agent prompt template** — see `references/scenario-prompt.md`.

### Step 3 — Aggregate & Report

```bash
~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/gen_report.py --input results.json
```

Combine automated (T1–T4) and scenario (T5) results into a final report:

```
## Skill Test Report — 2026-02-12

| Skill | T1 Dep | T2 Syn | T3 Con | T4 Run | T5 Sce | Result |
|-------|--------|--------|--------|--------|--------|--------|
| pdf   | PASS   | PASS   | PASS   | PASS   | PASS   | PASS   |
| xlsx  | PASS   | FAIL   | PASS   | —      | —      | FAIL   |

### FAIL: xlsx
- T2: scripts/office/validate.py uses match/case (Python 3.10+)
- **Fix**: Convert match/case to if/elif
```

Save the report to `~/Downloads/skill-test-report-{date}.md`.

### Step 4 — Present to User

Display the summary table, then for each FAIL and PARTIAL skill:
- Show the specific failing checks
- Provide concrete fix suggestions
- Ask if the user wants to auto-fix (hand off to skill-optimizer for content issues,
  or fix dependencies/syntax directly)

## Common Failure Patterns

| Pattern | Category | Auto-fixable? |
|---------|----------|--------------|
| pip package not installed | T1 | Yes — `pip3 install --user X` |
| brew tool missing | T1 | Yes — `brew install X` |
| npm package missing | T1 | Yes — `npm install -g X` |
| Python 3.10+ syntax on 3.9 | T2 | Yes — match→if/elif, X\|Y→Union |
| SKILL.md still has TODO placeholders | T3 | No — needs content authoring |
| Stale cross-skill reference | T3 | Yes — remove or update reference |
| README filename mismatch | T3 | Yes — rename file |
| Script fails --help | T4 | Investigate — may be missing dep |
| Missing Playwright fallback | T5 | Partial — add doc note |
| tools frontmatter incomplete | T3 | Yes — add missing tools |

## Integration with skill-lifecycle

This skill fits into the lifecycle pipeline as a gate between Audit and Optimize:

```
skill-curator (Audit) → skill-tester (Test) → skill-optimizer (Optimize) → skill-publisher (Publish) → skill-catalog (Catalog)
```

Related skills:
- **systematic-debugging** — Failed skill tests trigger systematic debugging
- **tdd** — Skill testing follows TDD principles
- **verification-before-completion** — Skill tests are part of completion verification

When called from skill-lifecycle, output JSON to stdout for pipeline consumption:
```bash
~/.local/bin/python3 scripts/gen_report.py --input results.json --format json
```

## Quick Reference

| Command | Description |
|---------|-------------|
| `/skill-tester` | Test all skills |
| `/skill-tester pdf` | Test a single skill |
| `/skill-tester --category T1` | Run only dependency checks |
| Auto-fix | After report, offer to fix auto-fixable issues |

## Sandbox Optimization

This skill is **sandbox-optimized**. Batch operations run inside `sandbox_execute`:

- **Batch T1–T4 checks**: Import `scripts/scan_env.py` in sandbox to run dependency, syntax, consistency, and runtime checks across all skills in one call
- **Report generation**: Import `scripts/gen_report.py` in sandbox to aggregate T1–T4 results and produce markdown or JSON report

Fallback (Bash):
- `~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/scan_env.py` — run checks via Bash when sandbox is unavailable
- `~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/gen_report.py` — generate report via Bash

Principle: **Deterministic batch work → sandbox; reasoning/presentation → LLM.**

## Continuous Improvement

This skill evolves with each use. After every invocation:

1. **Reflect** — Identify what worked, what caused friction, and any unexpected issues
2. **Record** — Append a concise lesson to `lessons.md` in this skill's directory
3. **Refine** — When a pattern recurs (2+ times), update SKILL.md directly

### lessons.md Entry Format

```
### YYYY-MM-DD — Brief title
- **Friction**: What went wrong or was suboptimal
- **Fix**: How it was resolved
- **Rule**: Generalizable takeaway for future invocations
```

Accumulated lessons signal when to run `/skill-optimizer` for a deeper structural review.

## Additional Resources

### Reference Files
- **`references/scenario-prompt.md`** — Agent prompt template for T5 scenario tests
- **`references/dep-patterns.md`** — Regex patterns for extracting dependencies from SKILL.md

### Scripts
- **`scripts/scan_env.py`** — Automated T1–T4 checks, outputs JSON results
- **`scripts/gen_report.py`** — Aggregates results into markdown or JSON report
- **`scripts/run_routing_evals.py`** — Routing 量化評估，跑 confusion matrix + precision/recall/F1

## Routing Evals Framework

蠶食自 yao-meta-skill `evals/` 結構，量化驗證 skill 的 description 是否能精準路由（防 false-positive 和 overfit）。

### 何時用 Routing Evals

- description 修改後想確認沒搶到其他 skill 的觸發
- 新 skill 上線前驗證 description 寫得夠精準
- 觀察到實際使用有 false-positive，要量化重現

不必每次都跑（耗 LLM token）；只在「description 有改」或「routing 出錯」時跑。

### 目錄結構

```
~/.claude/skills/skill-tester/evals/
├── README.md
├── promotion_policy.md          # baseline → improved 升級條件
├── _template/                   # 給每個 skill 套用的模板
├── runs/                        # 每次跑出的 JSON 結果（時間戳記）
└── <skill-slug>/                # 每個被 eval 的 skill
    ├── baseline_description.txt  # 基準（current SKILL.md description）
    ├── improved_description.txt  # 改進版（A/B 中的 B）
    ├── trigger_cases.json        # positive + negative + adversarial
    ├── blind_holdout.json        # 不在 description 中見過的 phrasing（防 overfit）
    ├── adversarial.json          # 邊界 case（相似關鍵字但不該命中）
    ├── semantic_config.json      # stub fallback 用關鍵字
    └── packaging_expectations.json
```

### 為新 skill 建 eval 套件

```bash
SLUG=<your-skill>
cp -r ~/.claude/skills/skill-tester/evals/_template ~/.claude/skills/skill-tester/evals/$SLUG
# 編輯 7 個檔案，最少實填：baseline + trigger_cases (5 pos / 3 neg / 3 adv) + blind_holdout (3-5) + adversarial (3-5)
```

### 跑 evals

```bash
# Baseline
~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/run_routing_evals.py --skill $SLUG

# A/B improved description
~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/run_routing_evals.py --skill $SLUG --description improved

# 強制 stub mode（無 LLM 也能跑，只看 semantic_config 關鍵字）
~/.local/bin/python3 ~/.claude/skills/skill-tester/scripts/run_routing_evals.py --skill $SLUG --stub
```

### LLM 模式

預設 LiteLLM proxy 呼叫真實 LLM（`gpt-4o-mini`）模擬 routing 判斷。LiteLLM 不可用時 fallback stub keyword 匹配（標 `mode: stub`）。stub 結果僅供結構驗證，**不能作為升級依據**。

### Confusion Matrix

```
Precision = TP / (TP + FP)        命中時的精準度
Recall    = TP / (TP + FN)        應命中時的捕獲率
F1        = 2·P·R / (P+R)         綜合分數
adv-FP-rate = adversarial 集中誤觸率
```

### 升級條件（promotion_policy.md）

1. blind_holdout recall ≥ +5%
2. adversarial FP-rate ≤ 10%
3. trigger_cases F1 不退步
4. 人工 review 通過 → 替換 SKILL.md frontmatter

詳見 `evals/promotion_policy.md` 與 `evals/README.md`。
