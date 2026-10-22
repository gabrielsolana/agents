import re
from datetime import datetime

from crewai.tools import tool

from . import sandbox_tools as sb

VERSION_FILE = "version.py"
CHANGELOG_FILE = "docs/versiones.md"
BUMPS = ("major", "minor", "patch")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_CHANGELOG_HEADER = (
    "# Historial de versiones\n\n"
    "Versionado MAYOR.MENOR.PARCHE: la MAYOR cambia con modificaciones incompatibles (por ejemplo, en el formato de los datos "
    "guardados), la MENOR con cada funcionalidad nueva y el PARCHE con correcciones. "
    "Las versiones más recientes aparecen primero.\n"
)

_released_in_this_run = False
_last_release: dict[str, list[str]] = {}


def reset_release_flag(inputs: dict | None = None) -> dict | None:
    """before_kickoff callback: allow one release registration per run."""
    global _released_in_this_run
    _released_in_this_run = False
    _last_release.clear()
    return inputs


def user_visible_change(_previous_output=None) -> bool:
    """Condition for the manual task: the registered release added features or fixed bugs the user can notice.

    Internal improvements alone (refactors, tests) and runs without a registered release do not need a manual update.
    """
    return bool(_last_release.get("added") or _last_release.get("fixed"))


def _release_path(relative: str):
    """Path of a release file inside the sandbox; refuses symlinks (the file or any parent folder)
    and anything that resolves outside the sandbox, because these writes happen on the host."""
    raw = sb.SANDBOX_DIR / relative
    for candidate in (raw, *raw.parents):
        if candidate == sb.SANDBOX_DIR:
            break
        if candidate.is_symlink():
            raise ValueError(f"{relative} es o cuelga de un enlace simbólico; no se escribe.")
    return sb._safe_path(relative)


def _version_path():
    return _release_path(VERSION_FILE)


def _changelog_path():
    return _release_path(CHANGELOG_FILE)


def read_version() -> str | None:
    """Current version from version.py, or None if the file is missing or malformed."""
    path = _version_path()
    if not path.is_file():
        return None
    match = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", path.read_text(encoding="utf-8"))
    return match.group(1) if match and _VERSION_RE.match(match.group(1)) else None


def _write_version(version: str) -> None:
    _version_path().write_text(f'__version__ = "{version}"\n', encoding="utf-8")


def _bullets(items: list[str]) -> str:
    clean = [i.strip() for i in items if i and i.strip()]
    return "\n".join(f"- {i}" for i in clean) if clean else "- (ninguna)"


def _entry(version: str, summary: str, added: list[str], fixed: list[str], improved: list[str] | None = None) -> str:
    internal = f"\n### Mejoras internas\n{_bullets(improved)}\n" if improved and any(i.strip() for i in improved) else ""
    return (
        f"## v{version} — {datetime.now().strftime('%Y-%m-%d')}\n\n"
        f"{summary.strip()}\n\n"
        f"### Nueva funcionalidad\n{_bullets(added)}\n\n"
        f"### Correcciones\n{_bullets(fixed)}\n"
        f"{internal}"
    )


def _insert_entry(entry: str) -> None:
    path = _changelog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else _CHANGELOG_HEADER
    idx = text.find("\n## ")
    text = text.rstrip("\n") + "\n\n" + entry if idx == -1 else text[: idx + 1] + entry + "\n" + text[idx + 1:]
    path.write_text(text, encoding="utf-8")


def init_version_files(version: str, note: str | None = None) -> None:
    """Create version.py (and the changelog, with a baseline entry if a note is given) when absent."""
    if read_version() is None:
        _write_version(version)
    if note and not _changelog_path().is_file():
        _insert_entry(_entry(version, note, [], []))


def next_version(current: str, bump: str) -> str:
    """Semantic-versioning bump of MAJOR.MINOR.PATCH."""
    major, minor, patch = (int(x) for x in current.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _release_problem(
    current: str | None, bump: str, summary: str, added: list[str], fixed: list[str], improved: list[str]
) -> str | None:
    """Why a release request is invalid, or None if it is consistent."""
    has_added, has_fixed = any(i.strip() for i in added), any(i.strip() for i in fixed)
    has_improved = any(i.strip() for i in improved)
    if _released_in_this_run:
        return "Ya se registró una versión en esta ejecución; no se registra otra."
    if current is None:
        return "No se encuentra version.py en el sandbox."
    if bump not in BUMPS:
        return f"bump debe ser uno de {BUMPS}."
    if not summary.strip():
        return "Falta el resumen de la versión."
    if not (has_added or has_fixed or has_improved):
        return "Indica al menos una novedad, una corrección o una mejora interna."
    if has_added and bump == "patch":
        return "Una funcionalidad nueva exige subir como mínimo la versión MENOR (bump=minor)."
    if not has_added and bump != "patch":
        return "Sin funcionalidad nueva solo corresponde una subida de PARCHE (bump=patch)."
    return None


@tool("Register Release")
def register_release(
    bump: str, summary: str, added: list[str], fixed: list[str], improved: list[str] | None = None
) -> str:
    """
    Register a new version of the application: it raises the version number in version.py and
    adds an entry at the top of docs/versiones.md. These files can only be changed with this tool.
    Call it once per run, and only when the work is confirmed as done.

    Args:
        bump: "major" for incompatible changes (for example in the saved data format), "minor" when
            there is new functionality, "patch" when there are only fixes.
        summary: One or two sentences, in Spanish, describing the version for a non-technical reader.
        added: New functionality, one short user-oriented sentence per item, in Spanish (empty list if none).
        fixed: Bugs fixed, one short user-oriented sentence per item, in Spanish (empty list if none).
        improved: Internal improvements that do not change what the user sees or does (refactors, tests,
            documentation, code quality), one short sentence per item, in Spanish. They only justify a "patch" bump.
    Returns:
        The new version, or the reason it was not registered.
    """
    global _released_in_this_run
    try:
        current = read_version()
        _changelog_path()
    except ValueError as exc:
        return f"No registrada: {exc}"
    improved = improved or []
    problem = _release_problem(current, bump, summary, added, fixed, improved)
    if problem:
        return f"No registrada: {problem}"
    version = next_version(current, bump)
    try:
        _write_version(version)
        _insert_entry(_entry(version, summary, added, fixed, improved))
    except ValueError as exc:
        return f"No registrada: {exc}"
    _released_in_this_run = True
    _last_release.update(added=[i for i in added if i.strip()], fixed=[i for i in fixed if i.strip()], improved=[i for i in improved if i.strip()])
    return f"Versión registrada: {current} -> {version}. Entrada añadida a {CHANGELOG_FILE}."


register_release.cache_function = lambda *_a, **_k: False
release_tools = [register_release]
