#!/usr/bin/env python3
"""
scan_env.py -- Automated T1-T4 skill health checks.

Scans all skills (or a single skill) under ~/.claude/skills/ and runs:
  T1  Dependency check   (pip, brew, npm)
  T2  Syntax check       (ast.parse + 3.10+ pattern detection)
  T3  Consistency check   (YAML frontmatter, file references, naming)
  T4  Runtime check       (--help smoke test for argparse scripts)

Usage:
  python3 scan_env.py                          # scan all skills
  python3 scan_env.py --skill pdf              # scan one skill
  python3 scan_env.py --category T1,T2         # only T1 and T2
  python3 scan_env.py --output results.json    # write to file

Python 3.9 compatible (no match/case, uses typing.List etc.)
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import os
import platform
import re
import subprocess
import sys
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Pip package name -> Python import name mapping
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# npm package name -> binary name mapping (for brew-installed CLIs)
# ---------------------------------------------------------------------------
NPM_TO_BINARY: Dict[str, str] = {
    "@openai/codex": "codex",
    "@google/gemini-cli": "gemini",
}

# ---------------------------------------------------------------------------
# Pip package name -> Python import name mapping
# ---------------------------------------------------------------------------
PIP_TO_IMPORT: Dict[str, str] = {
    "python-pptx": "pptx",
    "Pillow": "PIL",
    "pikepdf": "pikepdf",
    "defusedxml": "defusedxml",
    "python-dateutil": "dateutil",
    "beautifulsoup4": "bs4",
    "scikit-learn": "sklearn",
    "PyYAML": "yaml",
    "markitdown[pptx]": "markitdown",
    "markitdown[all]": "markitdown",
    "markitdown": "markitdown",
    "python-docx": "docx",
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
    "Pygments": "pygments",
    "attrs": "attr",
    "pyperclip": "pyperclip",
    "pdfplumber": "pdfplumber",
    "reportlab": "reportlab",
    "openpyxl": "openpyxl",
    "fpdf2": "fpdf",
    "camelot-py": "camelot",
    "camelot-py[cv]": "camelot",
}

# Standard library modules (partial list) -- skip these in T1
STDLIB_MODULES = {
    "abc", "argparse", "ast", "asyncio", "base64", "bisect", "calendar",
    "cmath", "codecs", "collections", "colorsys", "concurrent", "configparser",
    "contextlib", "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal",
    "difflib", "email", "enum", "errno", "fcntl", "fileinput", "fnmatch",
    "fractions", "ftplib", "functools", "getpass", "gettext", "glob",
    "gzip", "hashlib", "heapq", "hmac", "html", "http", "imaplib",
    "importlib", "inspect", "io", "itertools", "json", "keyword", "linecache",
    "locale", "logging", "lzma", "math", "mimetypes", "multiprocessing",
    "operator", "optparse", "os", "pathlib", "pickle", "platform", "plistlib",
    "pprint", "profile", "pstats", "queue", "random", "re", "readline",
    "reprlib", "resource", "sched", "secrets", "select", "shelve", "shlex",
    "shutil", "signal", "site", "smtplib", "socket", "socketserver", "sqlite3",
    "ssl", "stat", "statistics", "string", "struct", "subprocess", "sys",
    "sysconfig", "syslog", "tarfile", "tempfile", "termios", "textwrap",
    "threading", "time", "timeit", "tkinter", "token", "tokenize",
    "traceback", "tracemalloc", "tty", "turtle", "types", "typing",
    "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings",
    "wave", "weakref", "webbrowser", "xml", "xmlrpc", "zipfile", "zipimport",
    "zlib", "_thread", "__future__",
}

SUBPROCESS_TIMEOUT = 15  # seconds for most subprocess calls
RUNTIME_TIMEOUT = 10     # seconds for T4 --help

# Regex patterns for detecting relative imports (library modules)
_RELATIVE_IMPORT_RE = re.compile(r"^\s*from\s+\.+\s*import\s", re.MULTILINE)
_RELATIVE_FROM_RE = re.compile(r"^\s*from\s+\.+\w+\s+import\s", re.MULTILINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_python() -> str:
    """Find the best python3 binary, preferring uv-managed."""
    candidates = [
        os.path.expanduser("~/.local/bin/python3"),
        # whatever's in PATH
        "python3",
    ]
    for c in candidates:
        try:
            proc = subprocess.run(
                [c, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                return c
        except Exception:
            continue
    return "python3"


# Module-level cache so we only probe once
_PYTHON_BIN = ""  # type: str


def get_python() -> str:
    """Return cached best python3 path."""
    global _PYTHON_BIN
    if not _PYTHON_BIN:
        _PYTHON_BIN = _find_python()
    return _PYTHON_BIN


def run_cmd(cmd: List[str], timeout: int = SUBPROCESS_TIMEOUT) -> Tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", "command not found"
    except Exception as exc:
        return -1, "", str(exc)


def parse_yaml_frontmatter(text: str) -> Dict[str, Any]:
    """
    Minimal YAML frontmatter parser (no PyYAML dependency).
    Handles simple key: value pairs and key: "quoted value".
    Returns empty dict if no frontmatter found.
    """
    result = {}  # type: Dict[str, Any]
    if not text.startswith("---"):
        return result
    end = text.find("\n---", 3)
    if end == -1:
        return result
    block = text[3:end].strip()
    for line in block.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        colon_idx = line.find(":")
        if colon_idx == -1:
            continue
        key = line[:colon_idx].strip()
        val = line[colon_idx + 1:].strip()
        # Strip surrounding quotes
        if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
            val = val[1:-1]
        result[key] = val
    return result


def find_py_files(directory: str) -> List[str]:
    """Recursively find all .py files under *directory*."""
    results = []  # type: List[str]
    try:
        for root, _dirs, files in os.walk(directory):
            for f in files:
                if f.endswith(".py"):
                    results.append(os.path.join(root, f))
    except Exception:
        pass
    return sorted(results)


def strip_extras(pkg: str) -> str:
    """Remove PEP 508 extras like markitdown[pptx] -> markitdown."""
    idx = pkg.find("[")
    if idx != -1:
        return pkg[:idx]
    return pkg


def import_name_for_pip(pkg: str) -> str:
    """Resolve pip package name to its Python import name."""
    # First check with extras (e.g. markitdown[pptx])
    if pkg in PIP_TO_IMPORT:
        return PIP_TO_IMPORT[pkg]
    # Then check stripped name
    stripped = strip_extras(pkg)
    if stripped in PIP_TO_IMPORT:
        return PIP_TO_IMPORT[stripped]
    # Default: replace hyphens with underscores
    return stripped.replace("-", "_").lower()


# ---------------------------------------------------------------------------
# T1 - Dependency Check
# ---------------------------------------------------------------------------

def _is_valid_package_name(name: str) -> bool:
    """Check if a string looks like a real package name (not a placeholder)."""
    # Must be at least 2 chars
    if len(name) < 2:
        return False
    # Must not contain non-ASCII (like arrows)
    try:
        name.encode("ascii")
    except UnicodeEncodeError:
        return False
    # Must not be a common placeholder or English word used in docs
    placeholders = {
        "x", "y", "z", "X", "Y", "Z", "package", "pkg", "module",
        "name", "your", "the", "a", "an", "in", "of", "to", "for",
        "and", "or", "not", "is", "it", "if", "on", "at", "by",
        "from", "with", "as", "this", "that", "then", "each",
        "list", "show", "check", "docs", "install", "run",
        "example", "test", "all", "any", "some",
    }
    if name.lower() in placeholders:
        return False
    # Must not contain backticks, pipes, parens, arrows, etc.
    if re.search(r"[`|(){}$\u2192\u2190]", name):
        return False
    # Must start with a letter or @ (for scoped npm packages)
    if not re.match(r"^[a-zA-Z@]", name):
        return False
    # Must only contain valid package-name chars: alphanumeric, hyphens, underscores, dots, brackets, slashes
    if not re.match(r"^[@a-zA-Z0-9._\-\[\]/]+$", name):
        return False
    return True


def _extract_code_block_lines(content: str) -> List[str]:
    """
    Extract lines from fenced code blocks (```...```) that contain
    install commands. Also include bare lines that look like shell commands.
    This avoids matching prose like 'pip install X in docs'.
    """
    lines = []  # type: List[str]
    in_code_block = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            lines.append(line)
        else:
            # Also match inline code: `pip install foo`
            for m in re.finditer(r"`([^`]+)`", line):
                lines.append(m.group(1))
    return lines


def extract_deps_from_skillmd(skill_md_path: str) -> Dict[str, List[str]]:
    """
    Parse SKILL.md for pip/brew/npm install commands.
    Only searches inside fenced code blocks and inline code spans.
    Returns {"pip": [...], "brew": [...], "npm": [...]}.
    """
    deps = {"pip": [], "brew": [], "npm": []}  # type: Dict[str, List[str]]
    try:
        with open(skill_md_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return deps

    code_lines = _extract_code_block_lines(content)
    code_text = "\n".join(code_lines)

    # pip install / pip3 install
    for m in re.finditer(r"(?:pip3?|python3?[ \t]+-m[ \t]+pip)[ \t]+install[ \t]+(.+)", code_text):
        pkgs_str = m.group(1).strip()
        # Skip file-based installs: -r requirements.txt / --requirement requirements.txt
        if re.search(r"(?:^|\s)(?:-r|--requirement)\b", pkgs_str):
            continue
        # Remove flags like -q, --upgrade, etc.
        for token in pkgs_str.split():
            if token.startswith("-"):
                continue
            # Remove version specifiers like ==1.0, >=2.0
            pkg = re.split(r"[><=!~;]", token)[0].strip()
            if pkg and _is_valid_package_name(pkg):
                deps["pip"].append(pkg)

    # brew install (skip --cask installs: binary name often differs from cask name)
    for m in re.finditer(r"brew\s+install\s+(.+)", code_text):
        pkgs_str = m.group(1).strip()
        if re.search(r"(?:^|\s)--cask\b", pkgs_str):
            continue
        for token in pkgs_str.split():
            if token.startswith("-"):
                continue
            pkg = token.strip()
            if pkg and _is_valid_package_name(pkg):
                deps["brew"].append(pkg)

    # npm install / npm install -g
    # Use [ \t]+ instead of \s+ to prevent matching across newlines
    for m in re.finditer(r"npm[ \t]+install[ \t]+(?:-g[ \t]+)?(.+)", code_text):
        pkgs_str = m.group(1).strip()
        for token in pkgs_str.split():
            if token.startswith("-"):
                continue
            # Remove @version
            pkg = token.split("@")[0].strip() if "@" in token and not token.startswith("@") else token.strip()
            if pkg and _is_valid_package_name(pkg):
                deps["npm"].append(pkg)

    # Deduplicate while preserving order
    for key in deps:
        seen = set()  # type: set
        unique = []  # type: List[str]
        for item in deps[key]:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        deps[key] = unique

    return deps


def extract_imports_from_py(py_files: List[str]) -> List[str]:
    """
    Parse *.py files for import statements. Return top-level module names
    (e.g., 'from PIL.Image import open' -> 'PIL').
    """
    modules = set()  # type: set
    for fpath in py_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    modules.add(top)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    modules.add(top)
    return sorted(modules)


def check_t1(skill_path: str) -> List[Dict[str, str]]:
    """Run T1 dependency checks. Returns list of {name, type, status, detail}."""
    results = []  # type: List[Dict[str, str]]
    skill_md = os.path.join(skill_path, "SKILL.md")
    scripts_dir = os.path.join(skill_path, "scripts")

    # 1) Extract deps from SKILL.md
    deps = extract_deps_from_skillmd(skill_md)

    # 2) Extract imports from scripts/*.py
    py_files = find_py_files(scripts_dir)
    used_imports = extract_imports_from_py(py_files)

    # 3) Check pip deps (use uv-managed python if available)
    python_bin = get_python()
    checked_pip = set()  # type: set
    for pkg in deps["pip"]:
        import_mod = import_name_for_pip(pkg)
        checked_pip.add(import_mod)
        rc, _, stderr = run_cmd(
            [python_bin, "-c", "import " + import_mod],
            timeout=SUBPROCESS_TIMEOUT,
        )
        status = "ok" if rc == 0 else "missing"
        detail = "" if rc == 0 else stderr.strip().split("\n")[-1] if stderr else "import failed"
        results.append({"name": pkg, "type": "pip", "status": status, "detail": detail})

    # Build set of local module names (sibling .py files and directories in scripts/ and skill root)
    local_modules = set()  # type: set
    for f in py_files:
        basename = os.path.splitext(os.path.basename(f))[0]
        local_modules.add(basename)
        # Also add contents of each .py file's parent directory (handles subdirectory imports)
        parent_dir = os.path.dirname(f)
        try:
            for item in os.listdir(parent_dir):
                item_path = os.path.join(parent_dir, item)
                if os.path.isdir(item_path):
                    local_modules.add(item)
                elif item.endswith(".py"):
                    local_modules.add(os.path.splitext(item)[0])
        except Exception:
            pass
    # Also add directory names and .py basenames from scripts/ and skill root (local packages)
    for scan_dir in [scripts_dir, skill_path]:
        if os.path.isdir(scan_dir):
            try:
                for item in os.listdir(scan_dir):
                    item_path = os.path.join(scan_dir, item)
                    if os.path.isdir(item_path):
                        local_modules.add(item)
                    elif item.endswith(".py"):
                        local_modules.add(os.path.splitext(item)[0])
            except Exception:
                pass

    # 4) Check pip deps discovered from imports (not already in SKILL.md)
    for mod in used_imports:
        if mod in STDLIB_MODULES:
            continue
        if mod in checked_pip:
            continue
        if mod in local_modules:
            continue
        # Only flag as informational -- these are imports found in code
        rc, _, _ = run_cmd(
            [python_bin, "-c", "import " + mod],
            timeout=SUBPROCESS_TIMEOUT,
        )
        if rc != 0:
            results.append({
                "name": mod,
                "type": "pip(inferred)",
                "status": "missing",
                "detail": "found in scripts but not importable",
            })

    # 5) Check brew deps
    for pkg in deps["brew"]:
        rc, _, _ = run_cmd(["which", pkg], timeout=SUBPROCESS_TIMEOUT)
        if rc != 0:
            # Fallback: data-only packages (e.g. tesseract-lang) have no binary
            rc, _, _ = run_cmd(["brew", "list", pkg], timeout=SUBPROCESS_TIMEOUT)
        status = "ok" if rc == 0 else "missing"
        results.append({"name": pkg, "type": "brew", "status": status, "detail": ""})

    # 6) Check npm deps (with fallback to `which` for brew-installed CLIs)
    for pkg in deps["npm"]:
        rc, stdout, _ = run_cmd(["npm", "list", "-g", pkg], timeout=SUBPROCESS_TIMEOUT)
        # npm list -g returns 0 if found
        if rc == 0 and pkg in stdout:
            status = "ok"
            detail = ""
        else:
            # Fallback: check if the binary is on PATH (e.g. installed via brew)
            binary = NPM_TO_BINARY.get(pkg)
            if not binary:
                # Guess binary name: last segment of scoped package, or package name itself
                binary = pkg.split("/")[-1] if "/" in pkg else pkg
                # Strip common suffixes like -cli
                if binary.endswith("-cli"):
                    binary = binary[:-4]
            rc2, _, _ = run_cmd(["which", binary], timeout=SUBPROCESS_TIMEOUT)
            if rc2 == 0:
                status = "ok"
                detail = "found via PATH (brew or other install)"
            else:
                status = "missing"
                detail = ""
        results.append({"name": pkg, "type": "npm", "status": status, "detail": detail})

    return results


# ---------------------------------------------------------------------------
# T2 - Syntax Check
# ---------------------------------------------------------------------------

# Patterns that indicate Python 3.10+ syntax (outside strings/comments)
PY310_PATTERNS = [
    # match/case statement: "match " at start of line (with possible indentation)
    (re.compile(r"^\s*match\s+\S", re.MULTILINE), "match/case statement (3.10+)"),
    # Lowercase generic type hints: list[, dict[, set[, tuple[, type[
    (re.compile(r":\s*(?:list|dict|set|tuple|frozenset|type)\["), "lowercase generic type hint (3.9 __future__ or 3.10+)"),
    # Union with pipe: str | None, int | str (but NOT bitwise or in expressions)
    (re.compile(r":\s*\w+\s*\|\s*\w+"), "PEP 604 union type hint X | Y (3.10+)"),
    (re.compile(r"->\s*\w+\s*\|\s*\w+"), "PEP 604 union type hint X | Y (3.10+)"),
]


def check_t2(skill_path: str) -> List[Dict[str, str]]:
    """Run T2 syntax checks. Returns list of {file, status, detail}."""
    results = []  # type: List[Dict[str, str]]
    scripts_dir = os.path.join(skill_path, "scripts")
    py_files = find_py_files(scripts_dir)

    if not py_files:
        results.append({
            "file": scripts_dir,
            "status": "skip",
            "detail": "no .py files found in scripts/",
        })
        return results

    for fpath in py_files:
        rel = os.path.relpath(fpath, skill_path)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception as exc:
            results.append({"file": rel, "status": "error", "detail": "read error: " + str(exc)})
            continue

        # ast.parse check
        try:
            ast.parse(source, filename=fpath)
            parse_ok = True
        except SyntaxError as exc:
            results.append({
                "file": rel,
                "status": "error",
                "detail": "SyntaxError: {} (line {})".format(exc.msg, exc.lineno),
            })
            parse_ok = False

        # 3.10+ pattern detection
        warnings = []  # type: List[str]
        # Strip string literals to avoid false positives
        stripped = _strip_strings_and_comments(source)
        for pattern, desc in PY310_PATTERNS:
            if pattern.search(stripped):
                warnings.append(desc)

        if parse_ok and not warnings:
            results.append({"file": rel, "status": "ok", "detail": ""})
        elif parse_ok and warnings:
            results.append({
                "file": rel,
                "status": "warn",
                "detail": "possible 3.10+ syntax: " + "; ".join(warnings),
            })
        # If not parse_ok, we already appended the error above

    return results


def _strip_strings_and_comments(source: str) -> str:
    """
    Roughly remove string literals and comments from Python source
    to reduce false positives in regex pattern matching.
    """
    # Remove triple-quoted strings
    result = re.sub(r'"""[\s\S]*?"""', '""', source)
    result = re.sub(r"'''[\s\S]*?'''", "''", result)
    # Remove single-line strings
    result = re.sub(r'"[^"\n]*"', '""', result)
    result = re.sub(r"'[^'\n]*'", "''", result)
    # Remove comments
    result = re.sub(r"#[^\n]*", "", result)
    return result


# ---------------------------------------------------------------------------
# T3 - Consistency Check
# ---------------------------------------------------------------------------

def check_t3(skill_path: str) -> List[Dict[str, str]]:
    """Run T3 consistency checks. Returns list of {check, status, detail}."""
    results = []  # type: List[Dict[str, str]]
    skill_md_path = os.path.join(skill_path, "SKILL.md")

    # Read SKILL.md
    try:
        with open(skill_md_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except FileNotFoundError:
        results.append({"check": "SKILL.md exists", "status": "fail", "detail": "SKILL.md not found"})
        return results
    except Exception as exc:
        results.append({"check": "SKILL.md readable", "status": "fail", "detail": str(exc)})
        return results

    # Parse frontmatter
    fm = parse_yaml_frontmatter(content)

    # Check name
    name = fm.get("name", "")
    if not name or name.upper() == "TODO":
        results.append({
            "check": "frontmatter.name",
            "status": "fail",
            "detail": "name is missing or TODO",
        })
    else:
        results.append({"check": "frontmatter.name", "status": "ok", "detail": name})

    # Check description
    desc = fm.get("description", "")
    if not desc or desc.upper() == "TODO":
        results.append({
            "check": "frontmatter.description",
            "status": "fail",
            "detail": "description is missing or TODO",
        })
    else:
        # Check for at least one quoted phrase
        has_quote = bool(re.search(r'["\u201c\u201d]', desc))
        if has_quote:
            results.append({
                "check": "frontmatter.description",
                "status": "ok",
                "detail": desc[:80] + ("..." if len(desc) > 80 else ""),
            })
        else:
            results.append({
                "check": "frontmatter.description",
                "status": "warn",
                "detail": "description has no quoted trigger phrase",
            })

    # Extract body (after frontmatter)
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            body = content[end + 4:]

    # Strip fenced code blocks from body to avoid false positives
    body_no_codeblocks = re.sub(r"```[\s\S]*?```", "", body)

    # Find file references in body (outside code blocks)
    # Pattern: scripts/foo.py, references/bar.md, assets/img.png, templates/x.html
    file_ref_pattern = re.compile(
        r"(?:scripts|references|assets|templates)/[\w][\w./-]*[\w.]"
    )
    refs_found = set()  # type: set
    for m in file_ref_pattern.finditer(body_no_codeblocks):
        ref = m.group(0)
        # Clean up: strip trailing punctuation
        ref = ref.rstrip(".,;:!?)")
        # Sanity: must look like a file path (contain at least one / and a dot or be a directory)
        if "/" in ref:
            refs_found.add(ref)

    for ref in sorted(refs_found):
        full_path = os.path.join(skill_path, ref)
        if os.path.exists(full_path):
            results.append({"check": "file_ref:" + ref, "status": "ok", "detail": "exists"})
        else:
            results.append({
                "check": "file_ref:" + ref,
                "status": "fail",
                "detail": "referenced in SKILL.md but not found on disk",
            })

    # Check for README.zh-TW.md (should be README.zh.md)
    bad_readme = os.path.join(skill_path, "README.zh-TW.md")
    good_readme = os.path.join(skill_path, "README.zh.md")
    if os.path.exists(bad_readme):
        results.append({
            "check": "readme_naming",
            "status": "warn",
            "detail": "README.zh-TW.md found; convention is README.zh.md",
        })
    elif os.path.exists(good_readme):
        results.append({"check": "readme_naming", "status": "ok", "detail": "README.zh.md exists"})
    else:
        results.append({
            "check": "readme_naming",
            "status": "warn",
            "detail": "no Chinese README found",
        })

    return results


# ---------------------------------------------------------------------------
# T4 - Runtime Check
# ---------------------------------------------------------------------------

def _is_library_module(source: str) -> bool:
    """Check if source contains relative imports (library module, not standalone)."""
    return bool(_RELATIVE_IMPORT_RE.search(source) or _RELATIVE_FROM_RE.search(source))


def _is_runtime_guard_error(stderr: str) -> bool:
    """Check if stderr indicates the script intentionally refuses direct execution."""
    lower = stderr.lower()
    patterns = [
        "runtimeerror: this module should not be run directly",
        "runtimeerror: not meant to be run directly",
        "runtimeerror: do not run this module directly",
        "this script is not meant to be run directly",
        "this module is not meant to be run directly",
    ]
    return any(p in lower for p in patterns)


def _is_real_runtime_error(text: str) -> bool:
    """Return True if the text contains a real import/syntax/runtime error.

    These indicate the script is NOT runnable (broken dependencies, bad syntax,
    etc.) and should remain status='error'.
    """
    real_error_patterns = [
        "ModuleNotFoundError",
        "ImportError",
        "SyntaxError",
        "IndentationError",
        "TabError",
        "NameError",
        "AttributeError: module",
        "cannot import name",
        "No module named",
    ]
    return any(p in text for p in real_error_patterns)


def _analyse_help_failure(
    rc: int, stdout: str, stderr: str, combined: str
) -> Tuple[str, str]:
    """Classify a non-zero exit from ``python script.py --help``.

    T4's purpose is to verify a script is *runnable* (no import errors,
    no syntax errors).  A script that correctly rejects ``--help`` as
    an invalid argument IS runnable.

    Returns (status, detail).
    """
    # 1. Real runtime errors -> always "error"
    if _is_real_runtime_error(combined):
        err_line = stderr.strip().split("\n")[-1] if stderr.strip() else "exit code {}".format(rc)
        return ("error", err_line)

    # 2. Script treated --help as a filename -> FileNotFoundError on "--help"
    #    e.g.  "FileNotFoundError: [Errno 2] No such file or directory: '--help'"
    if "FileNotFoundError" in combined and "--help" in combined:
        return ("ok", "no --help support (argparse not used)")

    # 3. Script echoed back "--help" in a short error message
    #    e.g.  "Error: --help not found", "error: unknown option --help"
    if "--help" in combined and len(combined.strip()) < 200:
        # Short rejection message -- script works, just doesn't know --help
        return ("ok", "no --help support (argparse not used)")

    # 4. Usage-like output: script printed its own help/usage info and
    #    exited non-zero (common with manual sys.argv parsers)
    usage_patterns = [
        r"(?i)^usage:",
        r"(?i)^usage ",
        r"(?i)\busage:",
        r"(?i)positional argument",
        r"(?i)required argument",
        r"(?i)expected \d+ argument",
        r"(?i)missing .* argument",
        r"(?i)too (few|many) arguments",
    ]
    for pat in usage_patterns:
        if re.search(pat, combined):
            preview = combined.strip()[:120]
            return ("warn", preview)

    # 5. Very short output (< 200 chars) with non-zero exit and no real error
    #    indicators -- likely a simple "bad argument" rejection
    if len(combined.strip()) < 200 and rc in (1, 2):
        preview = combined.strip()[:120] if combined.strip() else "exit code {}".format(rc)
        return ("ok", "no --help support: " + preview)

    # 6. Fallback: genuine unknown error
    err_detail = stderr.strip().split("\n")[-1] if stderr.strip() else "exit code {}".format(rc)
    return ("error", err_detail)


def check_t4(skill_path: str) -> List[Dict[str, str]]:
    """Run T4 runtime checks. Returns list of {script, status, detail}."""
    results = []  # type: List[Dict[str, str]]
    scripts_dir = os.path.join(skill_path, "scripts")
    py_files = find_py_files(scripts_dir)
    python_bin = get_python()

    if not py_files:
        results.append({"script": "(none)", "status": "skip", "detail": "no scripts found"})
        return results

    for fpath in py_files:
        rel = os.path.relpath(fpath, skill_path)
        basename = os.path.basename(fpath)

        # Skip __init__.py files -- they are package markers, not scripts
        if basename == "__init__.py":
            results.append({"script": rel, "status": "skip", "detail": "package init file"})
            continue

        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception:
            results.append({"script": rel, "status": "skip", "detail": "cannot read file"})
            continue

        # Pre-scan: skip library modules with relative imports
        if _is_library_module(source):
            results.append({"script": rel, "status": "skip", "detail": "library module (relative imports)"})
            continue

        has_argparse = "argparse" in source
        has_main = ('if __name__' in source) or ("__name__" in source and "__main__" in source)

        if not (has_argparse or has_main):
            results.append({"script": rel, "status": "skip", "detail": "no argparse or __main__"})
            continue

        # Try running with --help
        rc, stdout, stderr = run_cmd(
            [python_bin, fpath, "--help"],
            timeout=RUNTIME_TIMEOUT,
        )

        if rc == 0:
            # Exit code 0 = script is runnable, regardless of output content
            help_preview = stdout.strip()[:120]
            results.append({"script": rel, "status": "ok", "detail": help_preview})
        elif "timeout" in stderr:
            results.append({"script": rel, "status": "error", "detail": "timed out after {}s".format(RUNTIME_TIMEOUT)})
        elif _is_runtime_guard_error(stderr):
            # Script intentionally refuses direct execution -- not an error
            results.append({"script": rel, "status": "skip", "detail": "library module (runtime guard)"})
        elif "ImportError: attempted relative import" in stderr:
            # Catch relative import errors that weren't caught by pre-scan
            results.append({"script": rel, "status": "skip", "detail": "library module (relative imports)"})
        else:
            # --- Analyse non-zero exit to distinguish real errors from
            #     scripts that simply don't understand --help. ---
            combined = (stdout + "\n" + stderr).strip()
            status, detail = _analyse_help_failure(rc, stdout, stderr, combined)
            results.append({"script": rel, "status": status, "detail": detail[:200]})

    return results


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def determine_result(
    t1: List[Dict[str, str]],
    t2: List[Dict[str, str]],
    t3: List[Dict[str, str]],
    t4: List[Dict[str, str]],
    categories: List[str],
) -> str:
    """Determine overall PASS / PARTIAL / FAIL from check results."""
    has_fail = False
    has_warn = False

    all_checks = []  # type: List[Dict[str, str]]
    if "T1" in categories:
        all_checks.extend(t1)
    if "T2" in categories:
        all_checks.extend(t2)
    if "T3" in categories:
        all_checks.extend(t3)
    if "T4" in categories:
        all_checks.extend(t4)

    for item in all_checks:
        s = item.get("status", "")
        if s in ("missing", "fail", "error"):
            has_fail = True
        elif s == "warn":
            has_warn = True

    if has_fail:
        return "FAIL"
    elif has_warn:
        return "PARTIAL"
    else:
        return "PASS"


def scan_skill(skill_path: str, categories: List[str]) -> Dict[str, Any]:
    """Scan a single skill and return its results dict."""
    entry = {"path": skill_path}  # type: Dict[str, Any]

    if "T1" in categories:
        try:
            entry["t1_dependency"] = check_t1(skill_path)
        except Exception as exc:
            entry["t1_dependency"] = [{"name": "(error)", "type": "internal", "status": "error", "detail": str(exc)}]

    if "T2" in categories:
        try:
            entry["t2_syntax"] = check_t2(skill_path)
        except Exception as exc:
            entry["t2_syntax"] = [{"file": "(error)", "status": "error", "detail": str(exc)}]

    if "T3" in categories:
        try:
            entry["t3_consistency"] = check_t3(skill_path)
        except Exception as exc:
            entry["t3_consistency"] = [{"check": "(error)", "status": "error", "detail": str(exc)}]

    if "T4" in categories:
        try:
            entry["t4_runtime"] = check_t4(skill_path)
        except Exception as exc:
            entry["t4_runtime"] = [{"script": "(error)", "status": "error", "detail": str(exc)}]

    entry["result"] = determine_result(
        entry.get("t1_dependency", []),
        entry.get("t2_syntax", []),
        entry.get("t3_consistency", []),
        entry.get("t4_runtime", []),
        categories,
    )
    return entry


def discover_skills(skills_dir: str) -> List[Tuple[str, str]]:
    """
    Return list of (skill_name, skill_path) for directories containing SKILL.md.
    """
    results = []  # type: List[Tuple[str, str]]
    try:
        for item in sorted(os.listdir(skills_dir)):
            full = os.path.join(skills_dir, item)
            if os.path.isdir(full) and os.path.isfile(os.path.join(full, "SKILL.md")):
                results.append((item, full))
    except Exception:
        pass
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated T1-T4 skill health checks",
    )
    parser.add_argument(
        "--skill",
        type=str,
        default=None,
        help="Name of a single skill to test (e.g. 'pdf')",
    )
    parser.add_argument(
        "--skills-dir",
        type=str,
        default=os.path.expanduser("~/.claude/skills"),
        help="Root directory containing skill folders (default: ~/.claude/skills/)",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Comma-separated categories to run: T1,T2,T3,T4 (default: all)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write JSON output to this file instead of stdout",
    )
    args = parser.parse_args()

    # Resolve categories
    if args.category:
        categories = [c.strip().upper() for c in args.category.split(",")]
        valid = {"T1", "T2", "T3", "T4"}
        for c in categories:
            if c not in valid:
                print("Error: unknown category '{}'. Valid: T1,T2,T3,T4".format(c), file=sys.stderr)
                sys.exit(1)
    else:
        categories = ["T1", "T2", "T3", "T4"]

    # Discover skills
    skills_dir = os.path.expanduser(args.skills_dir)
    if args.skill:
        skill_path = os.path.join(skills_dir, args.skill)
        if not os.path.isdir(skill_path):
            print("Error: skill directory not found: {}".format(skill_path), file=sys.stderr)
            sys.exit(1)
        skill_list = [(args.skill, skill_path)]
    else:
        skill_list = discover_skills(skills_dir)
        if not skill_list:
            print("Error: no skills found in {}".format(skills_dir), file=sys.stderr)
            sys.exit(1)

    # Build output
    output = {
        "timestamp": datetime.datetime.now().isoformat(),
        "python_version": platform.python_version(),
        "categories": categories,
        "skills_dir": skills_dir,
        "skills": {},
    }  # type: Dict[str, Any]

    for name, path in skill_list:
        print("Scanning: {} ...".format(name), file=sys.stderr)
        output["skills"][name] = scan_skill(path, categories)

    # Summary to stderr
    total = len(output["skills"])
    passed = sum(1 for v in output["skills"].values() if v.get("result") == "PASS")
    partial = sum(1 for v in output["skills"].values() if v.get("result") == "PARTIAL")
    failed = sum(1 for v in output["skills"].values() if v.get("result") == "FAIL")
    print(
        "\nDone. {} skills scanned: {} PASS, {} PARTIAL, {} FAIL".format(
            total, passed, partial, failed
        ),
        file=sys.stderr,
    )

    # Output JSON
    json_str = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(json_str + "\n")
            print("Results written to: {}".format(args.output), file=sys.stderr)
        except Exception as exc:
            print("Error writing output file: {}".format(exc), file=sys.stderr)
            print(json_str)
    else:
        print(json_str)


if __name__ == "__main__":
    main()
