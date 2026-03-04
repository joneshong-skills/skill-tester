#!/usr/bin/env bash
# run_all.sh — Automates the T1-T4 skill health check pipeline.
#
# Usage:
#   run_all.sh [--skill NAME] [--category T1,T2,T3,T4] [--format md|json] [--output FILE]
#
#   Default: scan all skills, all categories, markdown format, output to stdout
#
# Rules (per CLAUDE.md):
#   - set -u only (NOT set -e or set -o pipefail)
#   - python3 resolves via PATH (~/.local/bin/python3)
#   - Exit 0 on success, exit 1 if scan_env.py fails

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
ARG_SKILL=""
ARG_CATEGORY=""
ARG_FORMAT="md"
ARG_OUTPUT=""

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --skill)
            ARG_SKILL="$2"
            shift 2
            ;;
        --category)
            ARG_CATEGORY="$2"
            shift 2
            ;;
        --format)
            ARG_FORMAT="$2"
            shift 2
            ;;
        --output)
            ARG_OUTPUT="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: run_all.sh [--skill NAME] [--category T1,T2,T3,T4] [--format md|json] [--output FILE]"
            echo ""
            echo "  --skill NAME        Test a single skill by name (e.g. pdf)"
            echo "  --category LIST     Comma-separated categories: T1,T2,T3,T4 (default: all)"
            echo "  --format md|json    Output format (default: md)"
            echo "  --output FILE       Write report to FILE instead of stdout"
            echo ""
            echo "Default output path: ~/workshop/outputs/skill-tester/{YYYY-MM-DD}-report.{ext}"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Run with --help for usage." >&2
            exit 1
            ;;
    esac
done

# Validate format
if [ "$ARG_FORMAT" != "md" ] && [ "$ARG_FORMAT" != "json" ]; then
    echo "Error: --format must be 'md' or 'json', got: $ARG_FORMAT" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Set up temp directory
# ---------------------------------------------------------------------------
TMPDIR_WORK="$(python3 -c "import tempfile; print(tempfile.mkdtemp(prefix='skill-tester-'))")"
SCAN_JSON="${TMPDIR_WORK}/scan_raw.json"
CONVERTED_JSON="${TMPDIR_WORK}/scan_converted.json"

cleanup() {
    rm -rf "$TMPDIR_WORK" || true
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Build scan_env.py arguments
# ---------------------------------------------------------------------------
SCAN_ARGS=()
if [ -n "$ARG_SKILL" ]; then
    SCAN_ARGS+=(--skill "$ARG_SKILL")
fi
if [ -n "$ARG_CATEGORY" ]; then
    SCAN_ARGS+=(--category "$ARG_CATEGORY")
fi
SCAN_ARGS+=(--output "$SCAN_JSON")

# ---------------------------------------------------------------------------
# Step 1: Run scan_env.py
# ---------------------------------------------------------------------------
echo "Running scan_env.py..." >&2
python3 "${SCRIPT_DIR}/scan_env.py" "${SCAN_ARGS[@]}"
SCAN_EXIT=$?

if [ $SCAN_EXIT -ne 0 ]; then
    echo "Error: scan_env.py failed (exit $SCAN_EXIT)" >&2
    exit 1
fi

if [ ! -f "$SCAN_JSON" ]; then
    echo "Error: scan_env.py did not produce output at $SCAN_JSON" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 2: Convert scan_env.py output to gen_report.py input format
#
# scan_env.py produces:
#   { timestamp, python_version, categories, skills_dir,
#     skills: { NAME: { path, t1_dependency:[{name,type,status,detail}],
#               t2_syntax:[{file,status,detail}], t3_consistency:[{check,status,detail}],
#               t4_runtime:[{script,status,detail}], result } } }
#
# gen_report.py expects:
#   { meta: { date, python_version, skills_dir, total_skills },
#     skills: { NAME: { path, tests: { T1:{status,issues}, ... }, result } } }
# ---------------------------------------------------------------------------
echo "Converting results format..." >&2

python3 - "$SCAN_JSON" "$CONVERTED_JSON" <<'PYEOF'
import json
import sys
from datetime import datetime

src_path = sys.argv[1]
dst_path = sys.argv[2]

with open(src_path, "r", encoding="utf-8") as f:
    raw = json.load(f)

# --- helpers ----------------------------------------------------------------

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
                fix = "pip3 install --user {}".format(name)
            elif pkg_type == "brew":
                fix = "brew install {}".format(name)
            elif pkg_type == "npm":
                fix = "npm install -g {}".format(name)
            else:
                fix = ""
            msg = "`{}` not found".format(name)
            if detail:
                msg += " ({})".format(detail)
            issues.append({
                "message": msg,
                "fix": fix,
                "auto_fixable": True,
            })
        elif s == "warn":
            has_warn = True
            name = item.get("name", "")
            detail = item.get("detail", "")
            issues.append({
                "message": "`{}` warning: {}".format(name, detail),
                "fix": "",
                "auto_fixable": False,
            })

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
            issues.append({
                "message": "`{}`: {}".format(fname, detail),
                "fix": "Fix syntax error in script",
                "auto_fixable": False,
            })
        elif s == "warn":
            has_warn = True
            fname = item.get("file", "")
            detail = item.get("detail", "")
            issues.append({
                "message": "`{}`: {}".format(fname, detail),
                "fix": "Convert to Python 3.9-compatible syntax",
                "auto_fixable": True,
            })

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
            issues.append({
                "message": "{}: {}".format(check, detail),
                "fix": "",
                "auto_fixable": False,
            })
        elif s == "warn":
            has_warn = True
            check = item.get("check", "")
            detail = item.get("detail", "")
            issues.append({
                "message": "{}: {}".format(check, detail),
                "fix": "",
                "auto_fixable": True,
            })

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
            issues.append({
                "message": "`{}` runtime error: {}".format(script, detail),
                "fix": "Investigate broken dependency or syntax error",
                "auto_fixable": False,
            })
        elif s == "warn":
            has_warn = True
            script = item.get("script", "")
            detail = item.get("detail", "")
            issues.append({
                "message": "`{}` warning: {}".format(script, detail),
                "fix": "",
                "auto_fixable": False,
            })

    if has_fail:
        status = "FAIL"
    elif has_warn:
        status = "PARTIAL"
    else:
        status = "PASS"
    return {"status": status, "issues": issues}


# --- build converted structure ----------------------------------------------

ts = raw.get("timestamp", "")
try:
    report_date = datetime.fromisoformat(ts).date().isoformat()
except Exception:
    from datetime import date
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

output = {
    "meta": {
        "date": report_date,
        "python_version": raw.get("python_version", ""),
        "skills_dir": raw.get("skills_dir", ""),
        "total_skills": len(converted_skills),
    },
    "skills": converted_skills,
}

with open(dst_path, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
    f.write("\n")

print("Converted {} skills.".format(len(converted_skills)), file=__import__("sys").stderr)
PYEOF

CONVERT_EXIT=$?
if [ $CONVERT_EXIT -ne 0 ]; then
    echo "Error: format conversion failed (exit $CONVERT_EXIT)" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 3: Determine output path
# ---------------------------------------------------------------------------
if [ -n "$ARG_OUTPUT" ]; then
    FINAL_OUTPUT="$ARG_OUTPUT"
else
    TODAY="$(python3 -c "from datetime import date; print(date.today().isoformat())")"
    OUTPUT_ROOT="${CLAUDE_OUTPUTS_DIR:-${HOME}/workshop/outputs}"
    FINAL_OUTPUT="${OUTPUT_ROOT}/skill-tester/${TODAY}-report.${ARG_FORMAT}"
fi

# ---------------------------------------------------------------------------
# Step 4: Run gen_report.py
# ---------------------------------------------------------------------------
echo "Generating report..." >&2

GEN_ARGS=(--input "$CONVERTED_JSON" --format "$ARG_FORMAT")

if [ -n "$ARG_OUTPUT" ]; then
    # Write to specified file, also print to stdout for piping
    python3 "${SCRIPT_DIR}/gen_report.py" "${GEN_ARGS[@]}" -o "$FINAL_OUTPUT"
    GEN_EXIT=$?
    if [ $GEN_EXIT -eq 0 ]; then
        # Also emit to stdout so caller can capture
        cat "$FINAL_OUTPUT"
    fi
else
    # No --output: use default save path, also print to stdout
    python3 "${SCRIPT_DIR}/gen_report.py" "${GEN_ARGS[@]}" -o "$FINAL_OUTPUT"
    GEN_EXIT=$?
    if [ $GEN_EXIT -eq 0 ]; then
        cat "$FINAL_OUTPUT"
    fi
fi

if [ $GEN_EXIT -ne 0 ]; then
    echo "Error: gen_report.py failed (exit $GEN_EXIT)" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 5: Summary line to stderr
# ---------------------------------------------------------------------------
python3 - "$CONVERTED_JSON" >&2 <<'PYEOF'
import json, sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)

skills = data.get("skills", {})
total = len(skills)
passed = sum(1 for v in skills.values() if v.get("result") == "PASS")
partial = sum(1 for v in skills.values() if v.get("result") == "PARTIAL")
failed = sum(1 for v in skills.values() if v.get("result") == "FAIL")
failures = [name for name, v in skills.items() if v.get("result") == "FAIL"]

print("")
print("=" * 60)
print("{}/{} skills passed, {} failures".format(passed, total, failed))
if partial:
    print("  {} partial (warnings only)".format(partial))
if failures:
    print("  Failed: {}".format(", ".join(sorted(failures))))
print("=" * 60)
PYEOF

echo "Report saved: $FINAL_OUTPUT" >&2
exit 0
