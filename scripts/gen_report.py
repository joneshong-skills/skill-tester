#!/usr/bin/env python3
"""Generate a test report from skill-tester scan results.

Reads JSON output from scan_env.py (T1-T4 results), optionally merges
T5 scenario results, and produces a markdown or JSON report.

Usage:
    python3 gen_report.py --input results.json
    python3 gen_report.py --input results.json --scenario t5.json --format md
    python3 gen_report.py --input results.json --format json -o report.json
    cat results.json | python3 gen_report.py --save

Expected input JSON structure:
{
  "meta": {
    "date": "2026-02-12",
    "python_version": "3.9.6",
    "skills_dir": "~/.claude/skills",
    "total_skills": 39
  },
  "skills": {
    "pdf": {
      "path": "~/.claude/skills/pdf",
      "tests": {
        "T1": {"status": "PASS", "issues": []},
        "T2": {"status": "PASS", "issues": []},
        "T3": {"status": "PASS", "issues": []},
        "T4": {"status": "PASS", "issues": []}
      },
      "result": "PASS"
    },
    "xlsx": {
      "path": "~/.claude/skills/xlsx",
      "tests": {
        "T1": {"status": "FAIL", "issues": [
          {
            "message": "`openpyxl` not installed",
            "fix": "pip3 install --user openpyxl",
            "auto_fixable": true
          }
        ]},
        "T2": {"status": "FAIL", "issues": [
          {
            "message": "`scripts/office/validate.py`: uses match/case (Python 3.10+)",
            "fix": "Convert match/case to if/elif chains",
            "auto_fixable": true
          }
        ]}
      },
      "result": "FAIL"
    }
  }
}

T5 scenario JSON structure:
{
  "skills": {
    "pdf": {
      "T5": {"status": "PASS", "issues": []}
    }
  }
}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_LABELS = {
    "T1": "T1 Dep",
    "T2": "T2 Syn",
    "T3": "T3 Con",
    "T4": "T4 Run",
    "T5": "T5 Sce",
}

TEST_FULL_NAMES = {
    "T1": "T1 Dependency",
    "T2": "T2 Syntax",
    "T3": "T3 Consistency",
    "T4": "T4 Runtime",
    "T5": "T5 Scenario",
}

STATUS_ORDER = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def load_json(path: Optional[str]) -> Dict[str, Any]:
    """Load JSON from a file path or stdin."""
    if path is None or path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    if not raw.strip():
        print("Error: empty input", file=sys.stderr)
        sys.exit(1)
    return json.loads(raw)


def merge_scenario(data: Dict[str, Any], scenario: Dict[str, Any]) -> None:
    """Merge T5 scenario results into the main data in-place."""
    scenario_skills = scenario.get("skills", {})
    data_skills = data.get("skills", {})

    for name, t5_data in scenario_skills.items():
        if name not in data_skills:
            continue
        skill = data_skills[name]
        tests = skill.setdefault("tests", {})

        # Accept either {"T5": {...}} or direct {"status": ..., "issues": ...}
        if "T5" in t5_data:
            tests["T5"] = t5_data["T5"]
        elif "status" in t5_data:
            tests["T5"] = t5_data
        # Recompute overall result
        skill["result"] = compute_result(tests)


def compute_result(tests: Dict[str, Any]) -> str:
    """Compute overall PASS/PARTIAL/FAIL from individual test results."""
    statuses = []
    for tid in ("T1", "T2", "T3", "T4", "T5"):
        t = tests.get(tid)
        if t is None:
            continue
        statuses.append(t.get("status", "SKIP"))

    if not statuses:
        return "SKIP"
    if any(s == "FAIL" for s in statuses):
        return "FAIL"
    if any(s == "PARTIAL" for s in statuses):
        return "PARTIAL"
    return "PASS"


def collect_issues(skill_name: str, tests: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return all issues for a skill, annotated with test category."""
    issues = []
    for tid in ("T1", "T2", "T3", "T4", "T5"):
        t = tests.get(tid)
        if t is None:
            continue
        for issue in t.get("issues", []):
            entry = dict(issue)
            entry["test"] = tid
            entry["test_name"] = TEST_FULL_NAMES.get(tid, tid)
            issues.append(entry)
    return issues


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------


def build_summary(data: Dict[str, Any]) -> Dict[str, int]:
    """Count PASS / PARTIAL / FAIL across all skills."""
    counts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0}
    for skill in data.get("skills", {}).values():
        result = skill.get("result", "SKIP")
        if result in counts:
            counts[result] += 1
    return counts


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def fmt_status(status: Optional[str]) -> str:
    """Format a test status for the results table."""
    if status is None:
        return "\u2014"
    return status


def sort_skills(
    skills: Dict[str, Any],
) -> List[Tuple[str, Dict[str, Any]]]:
    """Sort skills: FAIL first, then PARTIAL, then PASS, alphabetical within."""
    items = list(skills.items())
    items.sort(key=lambda x: x[0].lower())
    items.sort(key=lambda x: STATUS_ORDER.get(x[1].get("result", "SKIP"), 3))
    return items


def generate_markdown(data: Dict[str, Any]) -> str:
    """Produce the full markdown report."""
    meta = data.get("meta", {})
    skills = data.get("skills", {})
    summary = build_summary(data)

    lines = []  # type: List[str]
    w = lines.append  # shorthand

    # ----- Header -----
    w("# Skill Test Report")
    w("")
    report_date = meta.get("date", date.today().isoformat())
    python_ver = meta.get("python_version", "unknown")
    total = meta.get("total_skills", len(skills))
    w("**Date**: {}  ".format(report_date))
    w("**Python**: {}  ".format(python_ver))
    w("**Skills tested**: {}  ".format(total))
    w("")

    # ----- Summary table -----
    w("## Summary")
    w("")
    w("| Result | Count |")
    w("|--------|-------|")
    for result in ("PASS", "PARTIAL", "FAIL"):
        w("| {:<6} | {:<5} |".format(result, summary.get(result, 0)))
    w("")

    # ----- Results table -----
    w("## Results")
    w("")
    w("| Skill | T1 Dep | T2 Syn | T3 Con | T4 Run | T5 Sce | Result |")
    w("|-------|--------|--------|--------|--------|--------|--------|")

    sorted_skills = sort_skills(skills)
    for name, skill in sorted_skills:
        tests = skill.get("tests", {})
        cols = []
        for tid in ("T1", "T2", "T3", "T4", "T5"):
            t = tests.get(tid)
            cols.append(fmt_status(t.get("status") if t else None))
        result = skill.get("result", "SKIP")
        w("| {name} | {t1} | {t2} | {t3} | {t4} | {t5} | **{r}** |".format(
            name=name,
            t1=cols[0],
            t2=cols[1],
            t3=cols[2],
            t4=cols[3],
            t5=cols[4],
            r=result,
        ))
    w("")

    # ----- Issues section -----
    has_issues = False
    for name, skill in sorted_skills:
        result = skill.get("result", "SKIP")
        if result == "PASS":
            continue
        tests = skill.get("tests", {})
        issues = collect_issues(name, tests)
        if not issues:
            continue

        if not has_issues:
            w("## Issues")
            w("")
            has_issues = True

        issue_count = len(issues)
        plural = "issue" if issue_count == 1 else "issues"
        w("### {}: {} ({} {})".format(result, name, issue_count, plural))
        w("")

        for idx, issue in enumerate(issues, 1):
            msg = issue.get("message", "Unknown issue")
            test_name = issue.get("test_name", issue.get("test", "?"))
            w("{}. **{}** \u2014 {}".format(idx, test_name, msg))
            fix = issue.get("fix")
            if fix:
                # If fix looks like a command, wrap in backticks
                if fix.startswith(("pip", "brew", "npm", "apt")):
                    w("   - **Fix**: `{}`".format(fix))
                else:
                    w("   - **Fix**: {}".format(fix))
            auto = issue.get("auto_fixable")
            if auto is not None:
                w("   - **Auto-fixable**: {}".format("Yes" if auto else "No"))
            w("")

    # ----- Footer -----
    if not has_issues:
        w("## Issues")
        w("")
        w("No issues found. All tested skills passed.")
        w("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------


def generate_json(data: Dict[str, Any]) -> str:
    """Produce a JSON report with an added summary field."""
    output = dict(data)
    output["summary"] = build_summary(data)
    return json.dumps(output, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a test report from skill-tester scan results.",
    )
    parser.add_argument(
        "--input", "-i",
        metavar="FILE",
        default=None,
        help="JSON results file from scan_env.py (default: stdin)",
    )
    parser.add_argument(
        "--scenario", "-s",
        metavar="FILE",
        default=None,
        help="Optional JSON file with T5 scenario results to merge",
    )
    parser.add_argument(
        "--format", "-f",
        choices=("md", "json"),
        default="md",
        dest="fmt",
        help="Output format: md (markdown) or json (default: md)",
    )
    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Auto-save to ~/Claude/skills/skill-tester/skill-test-report-{date}.{ext}",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    # Load primary results
    data = load_json(args.input)

    # Merge T5 scenario results if provided
    if args.scenario:
        scenario = load_json(args.scenario)
        merge_scenario(data, scenario)

    # Generate report
    if args.fmt == "md":
        report = generate_markdown(data)
    else:
        report = generate_json(data)

    # Determine output destinations
    outputs = []  # type: List[Optional[str]]
    if args.output:
        outputs.append(args.output)
    if args.save:
        ext = "md" if args.fmt == "md" else "json"
        today = data.get("meta", {}).get("date", date.today().isoformat())
        _root = os.path.expanduser(os.environ.get("CLAUDE_OUTPUTS_DIR", "~/Claude/skills"))
        save_path = os.path.join(_root, "skill-tester", "skill-test-report-{}.{}".format(today, ext))
        outputs.append(save_path)

    # Write to file(s) if specified
    for out_path in outputs:
        parent = os.path.dirname(out_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
            if not report.endswith("\n"):
                f.write("\n")
        print("Saved: {}".format(out_path), file=sys.stderr)

    # Always write to stdout unless output file was specified (without --save)
    if not args.output:
        sys.stdout.write(report)
        if not report.endswith("\n"):
            sys.stdout.write("\n")


if __name__ == "__main__":
    main()
