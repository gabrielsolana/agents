from crewai.tools import tool
from pathlib import Path
import base64
import shutil
import subprocess


SANDBOX_DIR = Path(__file__).parents[3] / "sandbox"
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

# Project/build config the agents must not touch: it is only written by reset_sandbox.
PROTECTED_FILES = {"pyproject.toml", "uv.lock", ".python-version"}


def reset_sandbox() -> None:
    """Wipe the sandbox and re-initialize it as a fresh uv project with gradio."""
    if SANDBOX_DIR.exists():
        shutil.rmtree(SANDBOX_DIR)
    SANDBOX_DIR.mkdir(parents=True)

    subprocess.run(["uv", "init", "--bare", "--no-workspace", "--python", "3.13"], cwd=SANDBOX_DIR, check=True)
    subprocess.run(["uv", "add", "gradio"], cwd=SANDBOX_DIR, check=True)

def _safe_path(filename: str) -> Path:
    """Resolve filename inside the sandbox, rejecting anything that escapes it."""
    base = SANDBOX_DIR.resolve()
    p = (base / filename).resolve()
    if not p.is_relative_to(base) or p == base:
        raise ValueError(f"Path escapes the sandbox: {filename}")
    if p.parent == base and p.name.lower() in PROTECTED_FILES:
        raise ValueError(f"Protected file, not accessible: {filename}")
    return p


@tool("List Sandbox Files")
def list_sandbox_files() -> str:
    """
    List the filenames currently in the sandbox directory.

    Returns:
        A newline-separated list of filenames, or a message if the
        sandbox is empty.
    """
    names = sorted(p.name for p in SANDBOX_DIR.iterdir())
    return "\n".join(names) if names else "The sandbox is empty."


@tool("Read Sandbox File")
def read_sandbox_file(filename: str) -> str:
    """
    Read and return the text contents of a file in the sandbox directory.

    Args:
        filename: The name of the file to read (e.g. "solution.py").
    Returns:
        The file's contents, or a message if the file does not exist.
    """
    try:
        path = _safe_path(filename)
    except ValueError as e:
        return str(e)
    if not path.is_file():
        return f"No such file in the sandbox: {filename}"
    return path.read_text(encoding="utf-8")


@tool("Write Sandbox File")
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
        path = _safe_path(filename)
    except ValueError as e:
        return str(e)
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
        "ghcr.io/astral-sh/uv:python3.13-bookworm-slim",
        "uv", "run", *uv_run_args,
    ]


@tool("Run Sandbox Python File")
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


sandbox_tools = [list_sandbox_files, read_sandbox_file, write_sandbox_file, run_sandbox_python]
# Read-only view of the sandbox (+ layout inspection) for reviewers and the manual writer.
ux_tools = [list_sandbox_files, read_sandbox_file, inspect_gradio_layout]


def _never_cache(*_args, **_kwargs) -> bool:
    return False


# Sandbox state changes between calls (files appear/change/run), so caching tool
# results would feed agents stale data. Opt out of CrewAI's default tool caching.
for _t in sandbox_tools + [inspect_gradio_layout]:
    _t.cache_function = _never_cache
