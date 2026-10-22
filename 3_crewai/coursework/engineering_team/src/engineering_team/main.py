#!/usr/bin/env python
import re
import sys
import warnings
from pathlib import Path
from datetime import datetime

import engineering_team.patch  # noqa: F401 — applies CrewAI MCP monkey-patch on import
from engineering_team.crew import EngineeringTeam
from .tools.release_tools import init_version_files
from .tools.sandbox_tools import SANDBOX_DIR, backup_sandbox, reset_sandbox

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# The agents read and print text with emojis and accents (app.py has them). When stdout is piped
# (for example `| Tee-Object`) Windows falls back to cp1252 and CrewAI's console output would crash.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

requirements = """
Un sistema sencillo de gestión contable para una PYME que presta servicios de automatización con IA.
El sistema debe permitir registrar clientes y crear proyectos o servicios para cada cliente (por ejemplo: chatbot, automatización de flujos de trabajo, desarrollo de agentes de IA, cuota mensual de mantenimiento).
El sistema debe permitir emitir facturas a los clientes, con líneas de detalle (descripción, cantidad, precio unitario), número de factura secuencial, fecha de emisión, fecha de vencimiento e IVA aplicado.
El sistema debe permitir registrar los cobros recibidos de una factura, admitiendo cobros parciales, y llevar el estado de cada factura (borrador, emitida, parcialmente cobrada, cobrada, vencida).
El sistema debe permitir registrar gastos con una categoría (por ejemplo: suscripciones de software, uso de APIs de LLM, hosting en la nube, autónomos colaboradores, marketing, oficina, impuestos), una fecha, un proveedor y un importe con IVA incluido.
El sistema debe permitir definir cargos y gastos recurrentes mensuales (por ejemplo: cuotas de mantenimiento, suscripciones SaaS) y generarlos para un mes determinado.
El sistema debe calcular la cuenta de pérdidas y ganancias de cualquier periodo: ingresos totales, gastos totales por categoría y beneficio neto.
El sistema debe poder informar de las cuentas por cobrar (facturas pendientes de cobro, destacando las vencidas) y del saldo de caja en cualquier momento.
El sistema debe poder informar del saldo de IVA de un periodo (IVA repercutido en facturas menos IVA soportado deducible en gastos).
El sistema debe poder informar de los ingresos y la rentabilidad por cliente y por proyecto, incluyendo el coste de uso de APIs de LLM asociado a cada proyecto.
El sistema debe poder listar todas las transacciones (facturas, cobros y gastos) a lo largo del tiempo, filtradas por rango de fechas, cliente o categoría.
El sistema debe impedir operaciones inválidas: cobrar más del importe pendiente de una factura, modificar o borrar una factura emitida (solo se puede anular mediante una factura rectificativa), importes negativos o cero, y registrar operaciones para clientes inexistentes.
Principio de usabilidad de la interfaz: en cada pestaña el listado (por ejemplo, la cartera de clientes) es el elemento central y ocupa la mayor parte de la pantalla; los formularios de alta se abren mediante un botón (por ejemplo, "Nuevo cliente") en lugar de estar siempre visibles.
"""


def run():
    """
    Run the crew.
    """
    inputs = {
        'requirements': requirements,
    }

    try:
        reset_sandbox()
        init_version_files("0.0.0")
        EngineeringTeam().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def _print_final_report(result) -> None:
    """Show the lead's closing report (cost, time and comments) at the end of the run."""
    line = "=" * 78
    print(f"\n{line}\nINFORME FINAL: coste, tiempo y comentarios\n{line}\n{result.raw}\n{line}\n", flush=True)


def _read_change_request(argv: list[str]) -> str:
    """The change request comes from `--file <path>` or from the remaining arguments."""
    if argv[:1] == ["--file"]:
        if len(argv) < 2:
            raise SystemExit("Uso: change --file <archivo con la petición de cambio>")
        with open(argv[1], "r", encoding="utf-8") as fh:
            return fh.read().strip()
    return " ".join(argv).strip()


def change():
    """
    Apply a change request to the application already in the sandbox, without rebuilding it.
    Usage: change "texto del cambio"   |   change --file cambio.md
    """
    request = _read_change_request(sys.argv[1:])
    if not request:
        raise SystemExit('Uso: change "texto del cambio"  |  change --file cambio.md')
    if len(re.findall(r"\w", request)) < MIN_REQUEST_LETTERS:
        raise SystemExit(f"La petición {request!r} es demasiado corta para ser un cambio real; descríbelo con una frase completa.")
    if not (SANDBOX_DIR / "app.py").is_file():
        raise SystemExit("No hay una aplicación en el sandbox (falta app.py). Usa run_crew para construirla primero.")

    backup = backup_sandbox()
    if backup:
        print(f"Copia del sandbox antes del cambio: {backup}")
    init_version_files("1.0.0", "Versión inicial: estado de la aplicación anterior a la introducción del control de versiones.")
    inputs = {
        "cambio": request,
        "cambio_id": datetime.now().strftime("%Y%m%d_%H%M"),
    }
    try:
        result = EngineeringTeam().change_crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while applying the change: {e}")
    _print_final_report(result)


DEFAULT_MAX_CHANGES = 5
MIN_REQUEST_LETTERS = 15  # a placeholder such as "..." must not reach the (paid) crew


def _resolve_review_file(argument: str) -> str:
    """Path of a review report relative to the sandbox, accepted as given, inside docs/, or absolute."""
    sandbox = SANDBOX_DIR.resolve()
    given = Path(argument)
    for candidate in (given, sandbox / given, sandbox / "docs" / given):
        resolved = candidate.resolve()
        if resolved.is_file() and resolved.suffix == ".md" and resolved.is_relative_to(sandbox):
            return resolved.relative_to(sandbox).as_posix()
    raise SystemExit(f"No encuentro el informe {argument!r} dentro del sandbox (ni en docs/).")


def _parse_apply_args(argv: list[str]) -> tuple[str, int]:
    """`apply_review <informe> [--max N]` -> (informe, N)."""
    max_changes, rest = DEFAULT_MAX_CHANGES, list(argv)
    if "--max" in rest:
        i = rest.index("--max")
        try:
            max_changes = int(rest[i + 1])
        except (IndexError, ValueError):
            raise SystemExit("Uso: apply_review <informe> [--max N]")
        del rest[i:i + 2]
    if len(rest) != 1 or max_changes < 1:
        raise SystemExit("Uso: apply_review <informe> [--max N]   (por ejemplo: apply_review docs/code_review_20261022_1703.md)")
    return rest[0], max_changes


def apply_review():
    """
    Apply the findings of a review report to the application already in the sandbox:
    the lead accepts or rejects them, then the change pipeline implements the accepted ones.
    Usage: apply_review docs/code_review_<fecha>.md [--max N]
    """
    argument, max_changes = _parse_apply_args(sys.argv[1:])
    if not (SANDBOX_DIR / "app.py").is_file():
        raise SystemExit("No hay una aplicación en el sandbox (falta app.py). Usa run_crew para construirla primero.")
    review_file = _resolve_review_file(argument)

    backup = backup_sandbox()
    if backup:
        print(f"Copia del sandbox antes de aplicar la revisión: {backup}")
    init_version_files("1.0.0", "Versión inicial: estado de la aplicación anterior a la introducción del control de versiones.")
    cambio_id = datetime.now().strftime("%Y%m%d_%H%M")
    inputs = {
        "review_file": review_file,
        "max_cambios": max_changes,
        "cambio_id": cambio_id,
        "cambio": (
            f"Aplica SOLO los cambios aceptados (sección «Aceptados») del documento docs/aplicar_{cambio_id}_decision.md, "
            f"que sale de la revisión {review_file}. No hagas nada de la sección «Rechazados» ni nada que no figure en los aceptados."
        ),
    }
    try:
        result = EngineeringTeam().apply_review_crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while applying the review: {e}")
    _print_final_report(result)


def review():
    """
    Run only the code reviewer on the application already in the sandbox (no rebuild, no changes).
    Usage: review_code
    """
    if not (SANDBOX_DIR / "app.py").is_file():
        raise SystemExit("No hay una aplicación en el sandbox (falta app.py). Usa run_crew para construirla primero.")
    inputs = {"review_id": datetime.now().strftime("%Y%m%d_%H%M")}
    try:
        result = EngineeringTeam().review_crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while reviewing the code: {e}")
    print(f"Tokens usados: {result.token_usage}")


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "topic": "AI LLMs",
        'current_year': str(datetime.now().year)
    }
    try:
        EngineeringTeam().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        EngineeringTeam().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        "topic": "AI LLMs",
        "current_year": str(datetime.now().year)
    }

    try:
        EngineeringTeam().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "topic": "",
        "current_year": ""
    }

    try:
        result = EngineeringTeam().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")
