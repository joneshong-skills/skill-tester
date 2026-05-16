# Dependency Extraction Patterns

Regex patterns used by `scan_env.py` to detect dependencies from SKILL.md files
and Python scripts. Each pattern section includes the regex, example matches,
and the verification command used for T1 checks.

---

## 1. pip install Patterns

Detects Python package install instructions in documentation and code blocks.

### Regex

```python
# Matches: pip install X, pip3 install X, pip install "X[extra]", pip install X==1.2.3
# Also handles: pip install --user X, pip install -U X, pip install --upgrade X
PIP_INSTALL = r'''
    (?:pip3?|python3?\s+-m\s+pip)   # pip, pip3, python -m pip, python3 -m pip
    \s+install
    (?:\s+(?:-[\w-]+|\-\-[\w-]+))*  # optional flags: --user, -U, --upgrade, etc.
    \s+
    (                                # capture group: package spec
        [A-Za-z0-9]                  # must start with alphanumeric
        [A-Za-z0-9._-]*             # package name body
        (?:\[[\w,]+\])?             # optional extras: [extra1,extra2]
        (?:[><=!~]+[\d.]+)?         # optional version constraint: ==1.2.3, >=2.0
    )
'''
```

### Examples

| Input | Captured Package |
|-------|-----------------|
| `pip install beautifulsoup4` | `beautifulsoup4` |
| `pip3 install "requests[security]"` | `requests[security]` |
| `pip install --user PyYAML>=6.0` | `PyYAML>=6.0` |
| `~/.local/bin/python3 -m pip install rich` | `rich` |
| `pip install -U openai==1.30.0` | `openai==1.30.0` |

### Verification Command

```bash
pip3 show <package_name>    # strip version spec and extras before checking
```

---

## 2. brew install Patterns

Detects Homebrew package install instructions.

### Regex

```python
# Matches: brew install X, brew install --cask X
BREW_INSTALL = r'''
    brew\s+install
    (?:\s+--cask)?               # optional --cask flag
    \s+
    ([a-z0-9][\w@./-]*)         # capture: formula or cask name
'''
```

### Examples

| Input | Captured Package |
|-------|-----------------|
| `brew install jq` | `jq` |
| `brew install --cask firefox` | `firefox` |
| `brew install imagemagick@7` | `imagemagick@7` |

### Verification Command

```bash
which <binary_name>          # for CLI tools (most cases)
brew list <formula_name>     # fallback if which fails
```

---

## 3. npm install Patterns

Detects Node.js package install instructions.

### Regex

```python
# Matches: npm install X, npm install -g X, npm i X, npx X (implies dep)
NPM_INSTALL = r'''
    (?:
        npm\s+(?:install|i)      # npm install or npm i
        (?:\s+-[gD]|\s+--(?:global|save-dev))*  # optional flags
        \s+
        (@?[a-z0-9][\w./-]*)    # capture: package name (may start with @)
        (?:@[\d.^~>=<]+)?       # optional version
    |
        npx\s+                   # npx implies package needed
        (@?[a-z0-9][\w./-]*)    # capture: package name
    )
'''
```

### Examples

| Input | Captured Package |
|-------|-----------------|
| `npm install -g beautiful-mermaid` | `beautiful-mermaid` |
| `npm install puppeteer` | `puppeteer` |
| `npm i -D @types/node` | `@types/node` |
| `npx playwright install` | `playwright` |

### Verification Command

```bash
npm list -g <package_name> 2>/dev/null   # for global installs
npm list <package_name> 2>/dev/null      # for local installs
```

---

## 4. Python Import Patterns

Detects Python import statements in `.py` scripts.

### Regex

```python
# Matches: import X, from X import Y, from X.sub import Y
# Captures the top-level package name only
PYTHON_IMPORT = r'''
    ^\s*                         # leading whitespace (but at start of line)
    (?:
        import\s+(\w+)           # import X → capture X
    |
        from\s+(\w+)            # from X import ... → capture X
        (?:\.\w+)*              # optional submodules (.sub.module)
        \s+import
    )
'''
```

### Examples

| Input | Captured Package |
|-------|-----------------|
| `import requests` | `requests` |
| `from PIL import Image` | `PIL` |
| `from bs4 import BeautifulSoup` | `bs4` |
| `import yaml` | `yaml` |
| `from pathlib import Path` | `pathlib` |

### Verification Command

```bash
~/.local/bin/python3 -c "import <module_name>"
```

---

## 5. pip-to-import Name Mappings

Many pip packages have a different import name than their install name. This
table maps pip package names to the Python module name used for import
verification.

| pip install name | Python import name | Notes |
|-----------------|-------------------|-------|
| `beautifulsoup4` | `bs4` | |
| `Pillow` | `PIL` | |
| `PyYAML` | `yaml` | |
| `python-dateutil` | `dateutil` | |
| `python-dotenv` | `dotenv` | |
| `scikit-learn` | `sklearn` | |
| `opencv-python` | `cv2` | |
| `opencv-python-headless` | `cv2` | |
| `google-auth` | `google.auth` | |
| `google-cloud-storage` | `google.cloud.storage` | |
| `attrs` | `attr` | |
| `rich` | `rich` | same name |
| `httpx` | `httpx` | same name |
| `openai` | `openai` | same name |
| `anthropic` | `anthropic` | same name |
| `pydantic` | `pydantic` | same name |
| `selenium` | `selenium` | same name |
| `playwright` | `playwright` | same name |
| `pytest` | `pytest` | same name |
| `flask` | `flask` | same name |
| `fastapi` | `fastapi` | same name |
| `uvicorn` | `uvicorn` | same name |
| `jinja2` | `jinja2` | case matters on pip side: `Jinja2` |
| `markupsafe` | `markupsafe` | pip: `MarkupSafe` |
| `websocket-client` | `websocket` | |
| `python-magic` | `magic` | |
| `msgpack-python` | `msgpack` | deprecated, now `msgpack` |
| `ruamel.yaml` | `ruamel.yaml` | dot in both names |

### Using the Mapping

```python
PIP_TO_IMPORT = {
    "beautifulsoup4": "bs4",
    "Pillow": "PIL",
    "PyYAML": "yaml",
    "python-dateutil": "dateutil",
    "python-dotenv": "dotenv",
    "scikit-learn": "sklearn",
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
    "attrs": "attr",
    "websocket-client": "websocket",
    "python-magic": "magic",
    "Jinja2": "jinja2",
    "MarkupSafe": "markupsafe",
}

def pip_name_to_import(pip_name: str) -> str:
    """Convert a pip package name to its Python import name."""
    # Strip version constraints and extras
    clean = re.sub(r'[\[>=<~!].*', '', pip_name).strip()
    return PIP_TO_IMPORT.get(clean, clean.lower().replace('-', '_'))
```

---

## 6. Known False Positives — Python Standard Library Modules

These modules ship with Python and should be skipped during T1 dependency
checks. This is not exhaustive but covers the most commonly imported stdlib
modules.

```python
STDLIB_MODULES = {
    # Built-in and core
    "abc", "ast", "asyncio", "argparse", "atexit",
    "base64", "builtins",
    "cgi", "codecs", "collections", "concurrent", "configparser",
    "contextlib", "copy", "csv", "ctypes",
    "dataclasses", "datetime", "decimal", "difflib", "dis",
    "email", "enum",
    "fileinput", "fnmatch", "fractions", "functools", "ftplib",
    "getpass", "glob", "gzip",
    "hashlib", "heapq", "hmac", "html", "http",
    "importlib", "inspect", "io", "ipaddress", "itertools",
    "json",
    "keyword",
    "linecache", "locale", "logging",
    "math", "mimetypes", "multiprocessing",
    "numbers",
    "operator", "os",
    "pathlib", "pdb", "pickle", "platform", "plistlib",
    "pprint", "profile",
    "queue",
    "random", "re",
    "secrets", "select", "shelve", "shlex", "shutil", "signal",
    "site", "socket", "sqlite3", "ssl", "stat", "string",
    "struct", "subprocess", "sys", "sysconfig",
    "tempfile", "textwrap", "threading", "time", "timeit",
    "tkinter", "token", "tokenize", "tomllib", "traceback",
    "turtle", "types", "typing",
    "unicodedata", "unittest", "urllib", "uuid",
    "venv",
    "warnings", "wave", "weakref",
    "xml", "xmlrpc",
    "zipfile", "zipimport", "zlib",
    # Commonly confused — these are also stdlib
    "posixpath", "ntpath", "genericpath",
    "distutils",  # deprecated in 3.12 but still stdlib
    "_thread",
}
```

### Usage in T1 Checks

```python
def is_third_party(module_name: str) -> bool:
    """Return True if the module is NOT part of the Python standard library."""
    top_level = module_name.split('.')[0]
    return top_level not in STDLIB_MODULES
```

---

## 7. Pattern Application Order

When analyzing a SKILL.md file, apply patterns in this order:

1. **pip install** patterns (from doc text and code blocks)
2. **brew install** patterns (from doc text and code blocks)
3. **npm install** patterns (from doc text and code blocks)
4. **Python import** patterns (from `scripts/*.py` files only, not SKILL.md)
5. Cross-reference: for each import, check if a corresponding pip install was
   already detected. If not, and the module is third-party, flag it as an
   undocumented dependency.

### Deduplication

- Normalize pip names to lowercase for comparison (`PyYAML` -> `pyyaml`)
- Map pip names to import names before comparing with detected imports
- A single dependency should produce only one T1 check, not multiple
