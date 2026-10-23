# Plan: LangGraph para la app de gestión integral (punto de entrada)

Escrito el 23/10/2026 al cerrar una sesión larga de trabajo con CrewAI. Esta carpeta contiene el plan para retomarlo **sin necesidad del contexto de esa sesión**.

## En una frase
Estudiar LangGraph construyendo **dos cosas**: (a) un **asistente dentro de la app** de gestión de la PYME y (b) un **sistema de agentes que construya la app** (el sustituto del crew de CrewAI), controlando el gasto de la API desde el primer día.

## Dónde está todo

| Qué | Dónde |
|---|---|
| **El plan completo** | [`plan.md`](plan.md) (en esta carpeta) |
| La app (repositorio propio, privado) | `3_crewai/coursework/engineering_team/sandbox/` → <https://github.com/gabrielsolana/gestion-integral-pyme> |
| Hoja de ruta de la app y peticiones A y B | `sandbox/docs/hoja_de_ruta.md` y `sandbox/docs/peticiones/` |
| Lo aprendido para gastar menos con agentes | `3_crewai/guia_ahorro_agentes_crewai.md` |
| El crew de CrewAI (abandonado, como referencia) | `3_crewai/coursework/engineering_team/src/engineering_team/` |
| Material del curso de LangGraph | esta misma carpeta `4_langchain_langgraph/` (labs 1–5, `sidekick.py`…) |
| LangGraph con modelos locales gratuitos (Ollama) | `community_contributions/review_4_langchain_langgraph_ollama_GiulioRusso.ipynb` |

## Cómo retomarlo (tres pasos)
1. Lee [`plan.md`](plan.md), sección 1 (decisiones ya tomadas) y sección 3 (control de gasto).
2. Decide las preguntas abiertas de la sección 7.
3. Empieza por la **fase 1a**, que no gasta nada de API.

## Aviso importante sobre el gasto
Un grafo de LangGraph llama a la API de Anthropic, que se factura **aparte** de la suscripción de Claude. La suscripción **no** sirve para ejecutar agentes propios. Antes de ejecutar cualquier grafo con un modelo de pago, lee la sección 3 del plan.
