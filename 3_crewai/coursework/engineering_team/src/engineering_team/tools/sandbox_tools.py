from crewai.tools import tool
from pathlib import Path
import ast
import base64
import functools
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime


SANDBOX_DIR = Path(__file__).parents[3] / "sandbox"
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

# Project/build config the agents must not touch: it is only written by reset_sandbox.
PROTECTED_FILES = {"pyproject.toml", "uv.lock", ".python-version"}
# Readable by agents, but only the release tool may change them.
RELEASE_FILES = {"version.py", "docs/versiones.md"}


# Previous sandboxes are copied here (outside the sandbox, git-ignored) before every reset.
BACKUP_DIR = Path(__file__).parents[3] / "sandbox_backups"
KEEP_BACKUPS = 5
MAX_LISTED_FILES = 500
MAX_OUTLINE_LINES = 400
MAX_SEARCH_HITS = 60
SEARCHABLE_SUFFIXES = {".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".csv"}
_SKIPPED_DIRS = {".venv", "__pycache__"}
_NOT_WORTH_BACKING_UP = PROTECTED_FILES | {".venv", "__pycache__"}


def backup_sandbox() -> Path | None:
    """Copy the current sandbox to sandbox_backups/<timestamp>/ and prune old backups.

    Skips .venv and __pycache__ (regenerable). Returns the backup path, or None when the
    sandbox holds nothing but project scaffolding. Raises on failure so that the caller
    never wipes a sandbox that could not be saved.
    """
    if not SANDBOX_DIR.exists() or not any(p.name not in _NOT_WORTH_BACKING_UP for p in SANDBOX_DIR.iterdir()):
        return None
    dest = BACKUP_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copytree(SANDBOX_DIR, dest, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
    for old in sorted(p for p in BACKUP_DIR.iterdir() if p.is_dir())[:-KEEP_BACKUPS]:
        shutil.rmtree(old)
    return dest


def reset_sandbox() -> None:
    """Back up, then wipe the sandbox and re-initialize it as a fresh uv project with gradio."""
    backup = backup_sandbox()
    if backup:
        print(f"Sandbox anterior guardado en: {backup}")
    if SANDBOX_DIR.exists():
        shutil.rmtree(SANDBOX_DIR)
    SANDBOX_DIR.mkdir(parents=True)

    subprocess.run(["uv", "init", "--bare", "--no-workspace", "--python", "3.13"], cwd=SANDBOX_DIR, check=True)
    subprocess.run(["uv", "add", "gradio"], cwd=SANDBOX_DIR, check=True)

# A model once emitted dozens of identical parallel calls to the same tool in a single response (113 calls to
# Search Sandbox with the same arguments), each returning a large result and burning the iteration budget.
# An identical call made right after another one, with no different call in between, is answered with a tiny
# message instead of being executed again. The guard is reset when a task ends (see cost_tools.mark_task_done)
# because a new task starts with an empty conversation and must be able to repeat the previous agent's calls.
_repeat_lock = threading.Lock()
_last_call: tuple | None = None
REPEATED_CALL_MESSAGE = (
    "Repeated call ignored: it is identical to the previous one and its result is already in the conversation above. "
    "Do not repeat it. To get different information change the arguments or use another tool "
    "(Outline Sandbox File for structure, Search Sandbox with a `regex` to locate code, Read Sandbox File with start_line/end_line)."
)


def reset_repeat_guard() -> None:
    """Forget the last call so that the next one is always executed."""
    global _last_call
    with _repeat_lock:
        _last_call = None


def _no_immediate_repeat(func):
    """Decorator: do not execute a call identical to the one just made."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        global _last_call
        signature = (func.__name__, repr(args), repr(sorted(kwargs.items())))
        with _repeat_lock:
            repeated = signature == _last_call
            _last_call = signature
        return REPEATED_CALL_MESSAGE if repeated else func(*args, **kwargs)

    return wrapper


def _syntax_error(source: str) -> str | None:
    """Why a piece of Python source does not parse, or None if it is valid."""
    try:
        ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return str(exc)
    return None


def _safe_path(filename: str, for_write: bool = False) -> Path:
    """Resolve filename inside the sandbox, rejecting anything that escapes it."""
    base = SANDBOX_DIR.resolve()
    p = (base / filename).resolve()
    if not p.is_relative_to(base) or p == base:
        raise ValueError(f"Path escapes the sandbox: {filename}")
    if p.parent == base and p.name.lower() in PROTECTED_FILES:
        raise ValueError(f"Protected file, not accessible: {filename}")
    if for_write and p.parent == base and p.name.startswith("_") and p.suffix == ".py":
        raise ValueError(f"Auxiliary scripts (names starting with an underscore) go in scripts/, not in the sandbox root: {filename}")
    if for_write and p.relative_to(base).as_posix().lower() in RELEASE_FILES:
        raise ValueError(f"{filename} is managed by the Register Release tool and cannot be edited directly")
    return p


@tool("List Sandbox Files")
@_no_immediate_repeat
def list_sandbox_files() -> str:
    """
    List the files currently in the sandbox, including those in subfolders
    (e.g. the markdown reports live in "docs/").

    Returns:
        A newline-separated list of paths relative to the sandbox, or a
        message if the sandbox is empty.
    """
    names = []
    for folder, dirs, files in os.walk(SANDBOX_DIR, followlinks=False):
        # Prune generated folders and symlinked folders (os.walk lists them but would not enter them).
        dirs[:] = sorted(d for d in dirs if d not in _SKIPPED_DIRS and not (Path(folder) / d).is_symlink())
        for name in files:
            path = Path(folder) / name
            if not path.is_symlink():
                names.append(path.relative_to(SANDBOX_DIR).as_posix())
    names.sort()
    if not names:
        return "The sandbox is empty."
    shown = names[:MAX_LISTED_FILES]
    extra = len(names) - len(shown)
    return "\n".join(shown + ([f"... and {extra} more files not shown."] if extra else []))


@tool("Read Sandbox File")
@_no_immediate_repeat
def read_sandbox_file(filename: str, start_line: int = 0, end_line: int = 0) -> str:
    """
    Read and return the text contents of a file in the sandbox directory. Large files cost a lot
    of tokens: use Outline Sandbox File or Search Sandbox to find what you need and then read only
    that range with start_line and end_line.

    Args:
        filename: The name of the file to read (e.g. "solution.py").
        start_line: Optional first line to return (1-based). Leave 0 to read from the beginning.
        end_line: Optional last line to return (inclusive). Leave 0 to read to the end.
            When a range is given, each line is prefixed with its number ("123: text").
    Returns:
        The file's contents (or the requested lines), or a message if the file does not exist.
    """
    try:
        path = _safe_path(filename)
    except ValueError as e:
        return str(e)
    if not path.is_file():
        return f"No such file in the sandbox: {filename}"
    text = path.read_text(encoding="utf-8")
    if not (start_line or end_line):
        return text
    lines = text.splitlines()
    first = max(start_line, 1)
    last = min(end_line, len(lines)) if end_line else len(lines)
    if first > len(lines):
        return f"{filename} has only {len(lines)} lines."
    return "\n".join(f"{n}: {lines[n - 1]}" for n in range(first, last + 1))


def _outline_text(filename: str) -> str:
    """Structure of a .py or .md file as indented text with line numbers."""
    try:
        path = _safe_path(filename)
    except ValueError as e:
        return str(e)
    if not path.is_file():
        return f"No such file in the sandbox: {filename}"
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".md":
        found = [f"L{n}: {line}" for n, line in enumerate(text.splitlines(), 1) if line.startswith("#")]
        return "\n".join(found[:MAX_OUTLINE_LINES]) or "No headings found."
    if path.suffix != ".py":
        return "Outline only supports .py and .md files; use Read Sandbox File."
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return f"Cannot outline {filename}: {exc}"
    out: list[str] = []

    def visit(body: list, depth: int) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                out.append(f"{'  ' * depth}class {node.name} (L{node.lineno}-{node.end_lineno})")
                visit(node.body, depth + 1)
            elif isinstance(node, _FUNCTION_NODES):
                out.append(f"{'  ' * depth}def {node.name} (L{node.lineno}-{node.end_lineno})")

    visit(tree.body, 0)
    extra = len(out) - MAX_OUTLINE_LINES
    shown = out[:MAX_OUTLINE_LINES] + ([f"... and {extra} more entries."] if extra > 0 else [])
    return "\n".join(shown) or "No classes or functions found."


@tool("Outline Sandbox File")
@_no_immediate_repeat
def outline_sandbox_file(filename: str) -> str:
    """
    Show the structure of a file without reading it all: for Python, every class, function and
    method with its line range; for markdown, every heading with its line number. Use it first on
    large files, then read only the ranges you need with Read Sandbox File.

    Args:
        filename: The Python (.py) or markdown (.md) file to outline (e.g. "accounting.py").
    Returns:
        An indented outline with line numbers.
    """
    return _outline_text(filename)


@tool("Search Sandbox")
@_no_immediate_repeat
def search_sandbox(regex: str = "", filename: str = "") -> str:
    """
    Search the sandbox with a regular expression and return the matching lines with their file and
    line number. Much cheaper than reading whole files to find where something is used.

    Args:
        regex: A Python regular expression (e.g. "def preview_recurring|_ACTIVE_STATUSES"). Required.
            If you only want the structure of a file, use Outline Sandbox File instead.
        filename: Optional single file to search. Leave empty to search every text file in the sandbox.
    Returns:
        Up to 60 lines formatted as "file:line: text".
    """
    if not regex:
        if filename:
            return ("No regex was given, so here is the outline of the file instead. To search, pass a regular expression in "
                    "`regex`.\n" + _outline_text(filename))
        return "Missing `regex`: pass a regular expression to search for."
    try:
        compiled = re.compile(regex)
    except re.error as exc:
        return f"Invalid regular expression: {exc}"
    try:
        if filename:
            paths = [_safe_path(filename)]
        else:
            paths = []
            for folder, dirs, files in os.walk(SANDBOX_DIR, followlinks=False):
                dirs[:] = [d for d in dirs if d not in _SKIPPED_DIRS and not (Path(folder) / d).is_symlink()]
                paths += [Path(folder) / f for f in sorted(files) if not (Path(folder) / f).is_symlink()]
    except ValueError as exc:
        return str(exc)
    hits: list[str] = []
    for path in sorted(paths):
        if not path.is_file() or path.suffix not in SEARCHABLE_SUFFIXES or path.name in PROTECTED_FILES:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if compiled.search(line):
                hits.append(f"{path.relative_to(SANDBOX_DIR).as_posix()}:{number}: {line.strip()[:160]}")
    if not hits:
        return "No matches."
    extra = len(hits) - MAX_SEARCH_HITS
    return "\n".join(hits[:MAX_SEARCH_HITS] + ([f"... and {extra} more matches."] if extra > 0 else []))


@tool("Write Sandbox File")
@_no_immediate_repeat
def write_sandbox_file(filename: str, content: str) -> str:
    """
    Write text to a file in the sandbox directory, replacing any existing
    file with the same name.

    Args:
        filename: The name of the file to write (e.g. "solution.py").
        content: The text content to write.
    Returns:
        A confirmation message.
    """
    try:
        path = _safe_path(filename, for_write=True)
    except ValueError as e:
        return str(e)
    if path.suffix == ".py":
        error = _syntax_error(content)
        if error:
            return f"Not written: {filename} would not be valid Python ({error}). Send the complete, corrected file."
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {filename}."


def _docker_uv_run(*uv_run_args: str) -> list[str]:
    """Build the `docker run ... uv run <args>` command that executes code in the sandbox."""
    return [
        "docker", "run", "--rm",
        "-v", f"{SANDBOX_DIR}:/workspace",
        "-w", "/workspace",
        # Keep the Linux venv inside the container, out of the host-mounted sandbox.
        "-e", "UV_PROJECT_ENVIRONMENT=/tmp/venv",
        # Scripts in scripts/ can import the modules in the sandbox root without touching sys.path.
        "-e", "PYTHONPATH=/workspace",
        "ghcr.io/astral-sh/uv:python3.13-bookworm-slim",
        "uv", "run", *uv_run_args,
    ]


@tool("Replace In Sandbox File")
@_no_immediate_repeat
def replace_in_sandbox_file(filename: str, old_text: str, new_text: str) -> str:
    """
    Edit an existing file in the sandbox by replacing one exact piece of text with another,
    leaving the rest of the file untouched. Prefer this over rewriting a whole file when
    changing existing code.

    Args:
        filename: The name of the file to edit (e.g. "accounting.py").
        old_text: The exact text to replace, including indentation and line breaks. It must
            appear exactly once in the file; include enough surrounding lines to make it unique.
        new_text: The text that replaces it.
    Returns:
        A confirmation, or the reason the edit was not applied.
    """
    try:
        path = _safe_path(filename, for_write=True)
    except ValueError as e:
        return str(e)
    if not path.is_file():
        return f"No such file in the sandbox: {filename}"
    if not old_text:
        return "old_text must not be empty."
    content = path.read_text(encoding="utf-8")
    count = content.count(old_text)
    if count == 0:
        return f"old_text was not found in {filename}. Read the file again and copy the text exactly."
    if count > 1:
        return f"old_text appears {count} times in {filename}; add surrounding lines so it is unique."
    updated = content.replace(old_text, new_text, 1)
    # Never turn a valid Python file into a broken one (a truncated block once corrupted accounting.py).
    if path.suffix == ".py" and _syntax_error(content) is None:
        error = _syntax_error(updated)
        if error:
            return f"Not applied: the edit would leave {filename} with a syntax error ({error}). Replace a complete block."
    path.write_text(updated, encoding="utf-8")
    return f"Replaced 1 occurrence in {filename}."


@tool("Run Sandbox Python File")
@_no_immediate_repeat
def run_sandbox_python(filename: str) -> str:
    """
    Execute a Python file from the sandbox directory inside an ephemeral
    Docker container, with the sandbox mounted as the working directory,
    using `uv run` to run the code in the uv project.

    Returns the exit code, stdout, and stderr, clearly labeled. Note that
    Python's unittest module prints test results — including failures and
    tracebacks — to stderr by default, not stdout, so stderr is just as
    important as stdout for understanding what happened.

    Args:
        filename: The name of the Python file to run (e.g. "solution.py").
    Returns:
        A labeled block containing the exit code, stdout, and stderr.
    """
    try:
        result = subprocess.run(
            _docker_uv_run(filename),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        return (
            f"Exit code: {result.returncode}\n\n"
            f"--- stdout ---\n{result.stdout or '(empty)'}\n\n"
            f"--- stderr ---\n{result.stderr or '(empty)'}"
        )
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return (
            "The script timed out after 300 seconds.\n\n"
            f"--- stdout so far ---\n{stdout or '(empty)'}\n\n"
            f"--- stderr so far ---\n{stderr or '(empty)'}"
        )

# Fixed script (never editable by agents) that dumps the Gradio component tree of
# sandbox/app.py. It is shipped to the container base64-encoded to avoid quoting issues.
_LAYOUT_SCRIPT = r"""
import sys
sys.path.insert(0, ".")
import app

demo = getattr(app, "demo", None)
if demo is None:
    sys.exit("app.py does not expose a module-level `demo` (gr.Blocks).")

def short(v, n=60):
    v = " ".join(str(v).split())
    return v if len(v) <= n else v[:n] + "..."

def walk(block, depth):
    kind = type(block).__name__
    info = []
    for attr in ("label", "value", "scale", "min_width", "visible", "open", "variant"):
        v = getattr(block, attr, None)
        if v is None or v == "":
            continue
        if attr == "value" and kind not in ("Button", "Markdown", "HTML", "Textbox", "Number", "Dropdown"):
            continue
        if attr == "visible" and v is True:
            continue
        info.append(f"{attr}={short(v)!r}" if isinstance(v, str) else f"{attr}={v}")
    print("  " * depth + kind + (" [" + ", ".join(info) + "]" if info else ""))
    for child in getattr(block, "children", None) or []:
        walk(child, depth + 1)

walk(demo, 0)
"""


@tool("Inspect Gradio Layout")
@_no_immediate_repeat
def inspect_gradio_layout() -> str:
    """
    Print the component tree of the Gradio app in the sandbox (app.py, which must
    expose a module-level `demo`): tabs, rows, columns, accordions, tables, buttons,
    with their labels, relative sizes (scale / min_width) and visibility.
    Use it to judge the layout (what is central, what sits behind a button, how many
    elements compete for the screen) without launching the app.

    Returns:
        The indented component tree, or the error if app.py cannot be imported.
    """
    code = base64.b64encode(_LAYOUT_SCRIPT.encode()).decode()
    try:
        result = subprocess.run(
            _docker_uv_run("python", "-c", f"import base64;exec(base64.b64decode('{code}'))"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return "Inspecting the layout timed out after 300 seconds."
    if result.returncode != 0:
        return f"Could not inspect the layout (exit {result.returncode}).\n{result.stderr or result.stdout}"
    return result.stdout or "(empty layout)"


# ---------------------------------------------------------------------------
# Static code-quality gate (reads and parses the code; never executes it)
# ---------------------------------------------------------------------------
MAX_FUNCTION_LINES = 40
MAX_COMPLEXITY = 10
MAX_REPORTED_ISSUES = 40

_BRANCH_NODES = (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.BoolOp, ast.IfExp, ast.comprehension)
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _complexity(fn: ast.AST) -> int:
    """Approximate cyclomatic complexity of a function, not counting nested functions."""
    total, stack = 1, list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (*_FUNCTION_NODES, ast.Lambda, ast.ClassDef)):
            continue
        total += isinstance(node, _BRANCH_NODES)
        stack.extend(ast.iter_child_nodes(node))
    return total


def _public_api(body: list) -> list:
    """Public classes, functions and methods (names without a leading underscore)."""
    found = []
    for node in body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            found.append(node)
            found.extend(_public_api(node.body))
        elif isinstance(node, _FUNCTION_NODES) and not node.name.startswith("_"):
            found.append(node)
    return found


def _missing_annotations(fn: ast.AST) -> list[str]:
    args = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
    missing = [a.arg for a in args if a.annotation is None and a.arg not in ("self", "cls")]
    if fn.returns is None:
        missing.append("retorno")
    return missing


def _quality_issues(source: str) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, ValueError) as exc:
        return [(0, f"no se puede analizar el archivo: {exc}")]
    issues = []
    for node in _public_api(tree.body):
        if not ast.get_docstring(node):
            issues.append((node.lineno, f"{node.name}: falta docstring"))
        if isinstance(node, _FUNCTION_NODES):
            missing = _missing_annotations(node)
            if missing:
                issues.append((node.lineno, f"{node.name}: faltan anotaciones de tipo ({', '.join(missing)})"))
    for node in ast.walk(tree):
        if not isinstance(node, _FUNCTION_NODES):
            continue
        length = node.end_lineno - node.lineno + 1
        if length > MAX_FUNCTION_LINES:
            issues.append((node.lineno, f"{node.name}: {length} líneas (máximo {MAX_FUNCTION_LINES})"))
        complexity = _complexity(node)
        if complexity > MAX_COMPLEXITY:
            issues.append((node.lineno, f"{node.name}: complejidad {complexity} (máximo {MAX_COMPLEXITY})"))
    return sorted(issues)


@tool("Check Code Quality")
@_no_immediate_repeat
def check_code_quality(filename: str = "") -> str:
    """
    Statically check the Python code of the sandbox against the team's quality standards:
    functions/methods of at most 40 lines, cyclomatic complexity of at most 10, a docstring on
    every public class, function and method, and type annotations on all parameters and return
    values of public functions. The code is parsed, never executed.

    Run it before declaring any code task finished, and keep fixing until the result is PASS.
    Test files and scratch scripts (names starting with "test_" or "_") are not checked.

    Args:
        filename: A single .py file to check (e.g. "accounting.py"). Leave empty to check every
            module in the sandbox (e.g. accounting.py and app.py).
    Returns:
        PASS or FAIL, and the list of violations as "file:line name: problem".
    """
    try:
        if filename:
            files = [_safe_path(filename)]
        else:
            files = sorted(
                p for p in SANDBOX_DIR.glob("*.py")
                if not p.name.startswith(("test_", "_"))
            )
    except ValueError as exc:
        return str(exc)
    files = [p for p in files if p.is_file() and not p.is_symlink()]
    if not files:
        return "No hay archivos .py que comprobar en el sandbox."
    lines = []
    for path in files:
        for lineno, message in _quality_issues(path.read_text(encoding="utf-8", errors="replace")):
            lines.append(f"{path.name}:{lineno} {message}")
    header = f"Archivos comprobados: {', '.join(p.name for p in files)}"
    limits = f"Límites: {MAX_FUNCTION_LINES} líneas por función, complejidad {MAX_COMPLEXITY}, docstring y tipos en lo público."
    if not lines:
        return f"PASS\n{header}\n{limits}"
    shown = lines[:MAX_REPORTED_ISSUES]
    extra = len(lines) - len(shown)
    tail = [f"... y {extra} más (corrige estos y vuelve a ejecutar)."] if extra else []
    return "\n".join([f"FAIL: {len(lines)} problema(s)", header, limits, *shown, *tail])


sandbox_tools = [
    list_sandbox_files, read_sandbox_file, outline_sandbox_file, search_sandbox, write_sandbox_file,
    replace_in_sandbox_file, run_sandbox_python, check_code_quality,
]
# Read-only view of the sandbox (+ layout inspection) for reviewers and the manual writer.
ux_tools = [
    list_sandbox_files, read_sandbox_file, outline_sandbox_file, search_sandbox,
    inspect_gradio_layout, check_code_quality,
]


def _never_cache(*_args, **_kwargs) -> bool:
    return False


# Sandbox state changes between calls (files appear/change/run), so caching tool
# results would feed agents stale data. Opt out of CrewAI's default tool caching.
for _t in sandbox_tools + [inspect_gradio_layout]:
    _t.cache_function = _never_cache
