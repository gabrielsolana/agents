import time
from pathlib import Path

import yaml
from crewai.tools import tool

from .sandbox_tools import reset_repeat_guard

TARIFAS_PATH = Path(__file__).parents[1] / "config" / "tarifas.yaml"

_crew = None
_start: float | None = None
_done: list[tuple[str, str, float]] = []  # (task name, agent role, finished_at)


def register_crew(crew) -> None:
    """Remember the running crew so the cost tool can read the token counters of its LLMs."""
    global _crew
    _crew = crew


def mark_start(inputs: dict | None = None) -> dict | None:
    """before_kickoff callback: start the run clock and forget any previous run's timings."""
    global _start
    _start = time.time()
    _done.clear()
    reset_repeat_guard()
    return inputs


# Tasks whose result is shown to the user as soon as they finish, with the banner to print above it.
_ANNOUNCE = {"apply_decision_task": "RIESGO Y CAMBIOS PREVISTOS (el trabajo continúa a continuación)"}


def mark_task_done(output) -> None:
    """task_callback: record when each task finished and which agent ran it, and announce key results."""
    reset_repeat_guard()
    name = getattr(output, "name", None) or "?"
    _done.append((name, str(getattr(output, "agent", "") or "?").strip(), time.time()))
    if name in _ANNOUNCE:
        line = "=" * 78
        print(f"\n{line}\n{_ANNOUNCE[name]}\n{line}\n{getattr(output, 'raw', '')}\n{line}\n", flush=True)


def _fmt(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


def _timing_section() -> list[str]:
    """Markdown with wall-clock time per task and per agent, from the callbacks above."""
    if _start is None or not _done:
        return ["", "Tiempo: no disponible (no se registró el inicio de la ejecución o aún no terminó ninguna tarea)."]
    rows, per_agent, prev = [], {}, _start
    for name, role, end in _done:
        dur = end - prev
        prev = end
        per_agent[role] = per_agent.get(role, 0.0) + dur
        rows.append(f"| {name} | {role} | {_fmt(dur)} |")
    elapsed = time.time() - _start
    return [
        "",
        "| Tarea | Agente | Duración |", "|---|---|---|", *rows,
        "",
        "| Agente | Tiempo en sus tareas |", "|---|---|",
        *[f"| {r} | {_fmt(t)} |" for r, t in sorted(per_agent.items(), key=lambda x: -x[1])],
        "",
        f"Tiempo transcurrido desde el inicio hasta esta medición: **{_fmt(elapsed)}** "
        f"(las {len(_done)} tareas ya terminadas suman {_fmt(prev - _start)}; el resto es la tarea de informe en curso).",
    ]


def _load_tarifas() -> dict:
    with open(TARIFAS_PATH, "r", encoding="utf-8") as fh:
        modelos = (yaml.safe_load(fh) or {}).get("modelos") or {}
    # CrewAI stores the model without the provider prefix ("claude-..." not "anthropic/claude-...").
    return {name.split("/", 1)[-1]: tarifa for name, tarifa in modelos.items()}


def _cost(usage: dict, tarifa: dict | None) -> float | None:
    """USD cost of a usage dict, or None if the model has no complete price."""
    campos = ("entrada", "salida", "lectura_cache", "escritura_cache")
    if not tarifa or any(tarifa.get(c) is None for c in campos):
        return None
    return (
        usage["prompt_tokens"] * tarifa["entrada"]
        + usage["completion_tokens"] * tarifa["salida"]
        + usage["cached_prompt_tokens"] * tarifa["lectura_cache"]
        + usage["cache_creation_tokens"] * tarifa["escritura_cache"]
    ) / 1_000_000


@tool("Report Token Usage")
def report_token_usage() -> str:
    """
    Report the real tokens consumed so far in this crew run, per agent and in total,
    and the estimated cost in USD computed with the price table in config/tarifas.yaml.
    Also report the wall-clock time of the run: per task, per agent and total elapsed.

    Tokens are the counters kept by CrewAI for every LLM call of this run. The cost is an
    estimate from those tokens and the prices the user wrote in tarifas.yaml; it is not the
    Anthropic invoice. Models without a complete price show "sin tarifa" instead of a cost.
    Calls made after this tool runs (including this reporting task) are not included.

    Returns:
        Markdown tables with tokens and cost per agent plus a total row, tables with the time per task
        and per agent, and notes on their limits.
    """
    if _crew is None:
        return "No hay ninguna ejecución del crew registrada: no se pueden leer los tokens."
    tarifas = _load_tarifas()

    agents = list(_crew.agents)
    if _crew.manager_agent is not None:
        agents.append(_crew.manager_agent)

    rows, seen = [], set()
    total = {"prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0,
             "cache_creation_tokens": 0, "successful_requests": 0}
    total_cost, sin_tarifa = 0.0, []
    for a in agents:
        llm = a.llm
        if id(llm) in seen or not hasattr(llm, "get_token_usage_summary"):
            continue
        seen.add(id(llm))
        u = llm.get_token_usage_summary()
        usage = {k: getattr(u, k, 0) or 0 for k in total}
        for k in total:
            total[k] += usage[k]
        model = getattr(llm, "model", "?")
        cost = _cost(usage, tarifas.get(model))
        if cost is None:
            sin_tarifa.append(model)
        else:
            total_cost += cost
        cost_txt = "sin tarifa" if cost is None else f"{cost:,.4f}"
        rows.append(
            f"| {a.role.strip()} | {model} | {usage['successful_requests']} | {usage['prompt_tokens']:,} | "
            f"{usage['cached_prompt_tokens']:,} | {usage['cache_creation_tokens']:,} | "
            f"{usage['completion_tokens']:,} | {cost_txt} |"
        )

    out = [
        "| Agente | Modelo | Llamadas | Entrada | Lectura caché | Escritura caché | Salida | Coste USD |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
        f"| **TOTAL** | | {total['successful_requests']} | {total['prompt_tokens']:,} | "
        f"{total['cached_prompt_tokens']:,} | {total['cache_creation_tokens']:,} | {total['completion_tokens']:,} | "
        f"{total_cost:,.4f}{' (parcial)' if sin_tarifa else ''} |",
        "",
        "Notas:",
        "- Tokens reales contados por CrewAI hasta este momento; no incluyen las llamadas posteriores (ni la propia tarea de informe).",
        "- El coste es una estimación con las tarifas de config/tarifas.yaml, no la factura de Anthropic.",
    ]
    if sin_tarifa:
        out.append(f"- Sin tarifa completa para: {', '.join(sorted(set(sin_tarifa)))}. El coste total es parcial.")
    out += _timing_section()
    out.append("- Los tiempos son de reloj (incluyen esperas de la API y ejecución de herramientas); la duración de cada tarea se mide entre el final de la anterior y el suyo.")
    return "\n".join(out)


report_token_usage.cache_function = lambda *_a, **_k: False
cost_tools = [report_token_usage]
