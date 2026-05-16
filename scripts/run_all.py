#!/usr/bin/env python3
# run_all.py — Automates the T1-T4 skill health check pipeline.
#
# Usage:
#   run_all.py [--skill NAME] [--category T1,T2,T3,T4] [--format md|json] [--output FILE]
#
#   Default: scan all skills, all categories, markdown format, output to stdout
#
# Rules (per CLAUDE.md):
#   - python3 resolves via PATH (~/.local/bin/python3)
#   - Exit 0 on success, exit 1 if scan_env.py fails

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(
        prog="run_all.py",
        description="Automates the T1-T4 skill health check pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Default output path: ~/workshop/outputs/skill-tester/{YYYY-MM-DD}-report.{ext}",
    )
    parser.add_argument(
        "--skill",
        metavar="NAME",
        default="",
        help="Test a single skill by name (e.g. pdf)",
    )
    parser.add_argument(
        "--category",
        metavar="LIST",
        default="",
        help="Comma-separated categories: T1,T2,T3,T4 (default: all)",
    )
    parser.add_argument(
        "--format",
        choices=["md", "json"],
        default="md",
        help="Output format (default: md)",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        default="",
        help="Write report to FILE instead of stdout",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Format conversion helpers (scan_env.py output → gen_report.py input)
# ---------------------------------------------------------------------------


def t1_to_report(items):
    """Convert T1 flat list to {status, issues}."""
    issues = []
    has_fail = False
    has_warn = False
    for item in items:
        s = item.get("status", "")
        if s in ("missing", "fail", "error"):
            has_fail = True
            pkg_type = item.get("type", "")
            name = item.get("name", "")
            detail = item.get("detail", "")
            if pkg_type.startswith("pip"):
                fix = f"pip3 install --user {name}"
            elif pkg_type == "brew":
                fix = f"brew install {name}"
            elif pkg_type == "npm":
                fix = f"npm install -g {name}"
            else:
                fix = ""
            msg = f"`{name}` not found"
            if detail:
                msg += f" ({detail})"
            issues.append({"message": msg, "fix": fix, "auto_fixable": True})
        elif s == "warn":
            has_warn = True
            name = item.get("name", "")
            detail = item.get("detail", "")
            issues.append(
                {
                    "message": f"`{name}` warning: {detail}",
                    "fix": "",
                    "auto_fixable": False,
                }
            )

    if has_fail:
        status = "FAIL"
    elif has_warn:
        status = "PARTIAL"
    else:
        status = "PASS"
    return {"status": status, "issues": issues}


def t2_to_report(items):
    """Convert T2 flat list to {status, issues}."""
    issues = []
    has_fail = False
    has_warn = False
    for item in items:
        s = item.get("status", "")
        if s in ("error", "fail"):
            has_fail = True
            fname = item.get("file", "")
            detail = item.get("detail", "")
            issues.append(
                {
                    "message": f"`{fname}`: {detail}",
                    "fix": "Fix syntax error in script",
                    "auto_fixable": False,
                }
            )
        elif s == "warn":
            has_warn = True
            fname = item.get("file", "")
            detail = item.get("detail", "")
            issues.append(
                {
                    "message": f"`{fname}`: {detail}",
                    "fix": "Convert to Python 3.9-compatible syntax",
                    "auto_fixable": True,
                }
            )

    if has_fail:
        status = "FAIL"
    elif has_warn:
        status = "PARTIAL"
    else:
        status = "PASS"
    return {"status": status, "issues": issues}


def t3_to_report(items):
    """Convert T3 flat list to {status, issues}."""
    issues = []
    has_fail = False
    has_warn = False
    for item in items:
        s = item.get("status", "")
        if s in ("fail", "error"):
            has_fail = True
            check = item.get("check", "")
            detail = item.get("detail", "")
            issues.append(
                {
                    "message": f"{check}: {detail}",
                    "fix": "",
                    "auto_fixable": False,
                }
            )
        elif s == "warn":
            has_warn = True
            check = item.get("check", "")
            detail = item.get("detail", "")
            issues.append(
                {
                    "message": f"{check}: {detail}",
                    "fix": "",
                    "auto_fixable": True,
                }
            )

    if has_fail:
        status = "FAIL"
    elif has_warn:
        status = "PARTIAL"
    else:
        status = "PASS"
    return {"status": status, "issues": issues}


def t4_to_report(items):
    """Convert T4 flat list to {status, issues}."""
    issues = []
    has_fail = False
    has_warn = False
    for item in items:
        s = item.get("status", "")
        if s == "error":
            has_fail = True
            script = item.get("script", "")
            detail = item.get("detail", "")
            issues.append(
                {
                    "message": f"`{script}` runtime error: {detail}",
                    "fix": "Investigate broken dependency or syntax error",
                    "auto_fixable": False,
                }
            )
        elif s == "warn":
            has_warn = True
            script = item.get("script", "")
            detail = item.get("detail", "")
            issues.append(
                {
                    "message": f"`{script}` warning: {detail}",
                    "fix": "",
                    "auto_fixable": False,
                }
            )

    if has_fail:
        status = "FAIL"
    elif has_warn:
        status = "PARTIAL"
    else:
        status = "PASS"
    return {"status": status, "issues": issues}


def convert_scan_to_report(raw: dict) -> dict:
    """Convert scan_env.py output format to gen_report.py input format."""
    ts = raw.get("timestamp", "")
    try:
        report_date = datetime.fromisoformat(ts).date().isoformat()
    except Exception:
        report_date = date.today().isoformat()

    skills_raw = raw.get("skills", {})
    converted_skills = {}

    for skill_name, skill_data in skills_raw.items():
        tests = {}
        if "t1_dependency" in skill_data:
            tests["T1"] = t1_to_report(skill_data["t1_dependency"])
        if "t2_syntax" in skill_data:
            tests["T2"] = t2_to_report(skill_data["t2_syntax"])
        if "t3_consistency" in skill_data:
            tests["T3"] = t3_to_report(skill_data["t3_consistency"])
        if "t4_runtime" in skill_data:
            tests["T4"] = t4_to_report(skill_data["t4_runtime"])

        converted_skills[skill_name] = {
            "path": skill_data.get("path", ""),
            "tests": tests,
            "result": skill_data.get("result", "PASS"),
        }

    return {
        "meta": {
            "date": report_date,
            "python_version": raw.get("python_version", ""),
            "skills_dir": raw.get("skills_dir", ""),
            "total_skills": len(converted_skills),
        },
        "skills": converted_skills,
    }


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def print_summary(converted: dict):
    skills = converted.get("skills", {})
    total = len(skills)
    passed = sum(1 for v in skills.values() if v.get("result") == "PASS")
    partial = sum(1 for v in skills.values() if v.get("result") == "PARTIAL")
    failed = sum(1 for v in skills.values() if v.get("result") == "FAIL")
    failures = sorted(name for name, v in skills.items() if v.get("result") == "FAIL")

    print("", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"{passed}/{total} skills passed, {failed} failures", file=sys.stderr)
    if partial:
        print(f"  {partial} partial (warnings only)", file=sys.stderr)
    if failures:
        print("  Failed: {}".format(", ".join(failures)), file=sys.stderr)
    print("=" * 60, file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = parse_args()

    tmpdir = tempfile.mkdtemp(prefix="skill-tester-")
    scan_json = os.path.join(tmpdir, "scan_raw.json")
    converted_json = os.path.join(tmpdir, "scan_converted.json")

    try:
        # -----------------------------------------------------------------------
        # Step 1: Run scan_env.py
        # -----------------------------------------------------------------------
        print("Running scan_env.py...", file=sys.stderr)

        scan_cmd = [sys.executable, str(SCRIPT_DIR / "scan_env.py")]
        if args.skill:
            scan_cmd += ["--skill", args.skill]
        if args.category:
            scan_cmd += ["--category", args.category]
        scan_cmd += ["--output", scan_json]

        result = subprocess.run(scan_cmd)
        if result.returncode != 0:
            print(f"Error: scan_env.py failed (exit {result.returncode})", file=sys.stderr)
            return 1

        if not os.path.isfile(scan_json):
            print(f"Error: scan_env.py did not produce output at {scan_json}", file=sys.stderr)
            return 1

        # -----------------------------------------------------------------------
        # Step 2: Convert scan_env.py output to gen_report.py input format
        # -----------------------------------------------------------------------
        print("Converting results format...", file=sys.stderr)

        with open(scan_json, encoding="utf-8") as f:
            raw = json.load(f)

        converted = convert_scan_to_report(raw)

        with open(converted_json, "w", encoding="utf-8") as f:
            json.dump(converted, f, indent=2, ensure_ascii=False)
            f.write("\n")

        print("Converted {} skills.".format(len(converted.get("skills", {}))), file=sys.stderr)

        # -----------------------------------------------------------------------
        # Step 3: Determine output path
        # -----------------------------------------------------------------------
        if args.output:
            final_output = args.output
        else:
            today = date.today().isoformat()
            output_root = os.environ.get(
                "CLAUDE_OUTPUTS_DIR",
                os.path.join(os.path.expanduser("~"), "workshop", "outputs"),
            )
            final_output = os.path.join(
                output_root, "skill-tester", f"{today}-report.{args.format}"
            )

        # Ensure output directory exists
        os.makedirs(os.path.dirname(final_output), exist_ok=True)

        # -----------------------------------------------------------------------
        # Step 4: Run gen_report.py
        # -----------------------------------------------------------------------
        print("Generating report...", file=sys.stderr)

        gen_cmd = [
            sys.executable,
            str(SCRIPT_DIR / "gen_report.py"),
            "--input",
            converted_json,
            "--format",
            args.format,
            "-o",
            final_output,
        ]

        gen_result = subprocess.run(gen_cmd)
        if gen_result.returncode != 0:
            print(f"Error: gen_report.py failed (exit {gen_result.returncode})", file=sys.stderr)
            return 1

        # Emit report to stdout (same behaviour as original: cat "$FINAL_OUTPUT")
        with open(final_output, encoding="utf-8") as f:
            sys.stdout.write(f.read())

        # -----------------------------------------------------------------------
        # Step 5: Summary line to stderr
        # -----------------------------------------------------------------------
        print_summary(converted)
        print(f"Report saved: {final_output}", file=sys.stderr)
        return 0

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
