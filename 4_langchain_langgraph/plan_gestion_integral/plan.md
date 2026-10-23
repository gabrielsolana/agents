# Plan: aprender LangGraph construyendo agentes para la app de gestión integral

> Estado: **solo plan**, nada de esto está construido. Fecha: 23/10/2026. Lo marcado como *verificado* se comprobó en la documentación oficial ese día; lo marcado como *sin verificar* hay que comprobarlo antes de apoyarse en ello. Consulta siempre la documentación actual (por ejemplo con Context7: biblioteca `/websites/langchain_oss_python_langgraph`), porque LangGraph cambia deprisa.

---

## 1. Contexto y decisiones ya tomadas

**La persona y el negocio.** Gabi será **autónomo y trabajará solo**; la empresa aún no existe y no hay fecha para la primera factura. Vende servicios de automatización con IA a pymes. Quiere una app de **gestión integral** de su negocio.

**La app.** Gradio, en el repositorio privado `gestion-integral-pyme` (versión 1.2.2). Hoy es solo el módulo de **contabilidad**: clientes, proyectos, facturas, cobros, gastos, recurrentes, informes (pérdidas y ganancias, cuentas por cobrar, IVA, rentabilidad) y exportación a CSV, con 237 pruebas. **No contiene ningún agente ni usa ningún modelo de IA**: solo importa la biblioteca estándar y `gradio`. Los datos reales viven en `accounting_data.json`, que está en `.gitignore` y nunca debe subirse.

**Cómo se construyó.** Con un crew de CrewAI (lead en Fable, ingenieros en Sonnet). Costó más de 54 USD en total, con parte desperdiciada por fallos. Se **abandona CrewAI**.

**Decisiones:**
1. Estudiar **LangGraph**, en una rama aparte.
2. Usar agentes de **dos maneras**: un asistente *dentro* de la app (parte 1) y un sistema que *construye* la app (parte 2).
3. Los requisitos de las siguientes funciones de la app ya están escritos en markdown y valen para cualquier sistema: `sandbox/docs/peticiones/peticion_A_retencion_irpf.md` y `peticion_B_oportunidades_presupuestos.md` (etapas de oportunidad: nuevo → contactado → propuesta → ganado/perdido; el presupuesto lleva IVA e IRPF). Orden de módulos previsto en `sandbox/docs/hoja_de_ruta.md`.

**Lo que hay que saber de la sesión anterior:** en la fase de aprendizaje de CrewAI, Gabi pidió que Claude **no construyera la app a mano** para no vaciar de sentido el ejercicio. Con CrewAI abandonado, esa restricción ya no aplica. Aun así, **pregunta antes** de implementar funcionalidad grande.

---

## 2. Qué construir y en qué orden

| Fase | Qué | Modelo de IA | Coste de API |
|---|---|---|---|
| **1a** | Asistente dentro de la app, **sin LLM**: un grafo cuyos nodos son Python puro. Clasifica la pregunta («¿qué me deben?», «IVA del trimestre») y consulta `AccountingSystem`. | Ninguno | **0** |
| **1b** | Mismo asistente con un **LLM y herramientas de solo lectura** (facturas pendientes, pérdidas y ganancias, IVA…). Bucle agente → herramientas → agente. | Uno pequeño | Poco |
| **1c** | **Acciones con aprobación humana** (`interrupt`): por ejemplo, redactar el borrador de un presupuesto que el usuario confirma. Memoria con checkpointer SQLite. | Pequeño | Poco |
| **2** | **El sistema que construye la app**: supervisor, programador, probador, revisor, con aprobación humana antes de gastar en implementar. | Mixto | Más |

**Por qué este orden:** la parte 1 es pequeña, da valor al usuario y enseña lo central de LangGraph con pocas llamadas. La parte 2 hace muchas llamadas (es lo que se encareció con el crew) y se beneficia de lo aprendido.

**Criterios de aceptación de la fase 1a** (todo debe cumplirse):
- Un grafo `StateGraph` con estado tipado, al menos tres nodos y una arista condicional.
- Responde, sin LLM, al menos a: facturas pendientes de cobro, saldo de IVA de un periodo y beneficio del periodo, **con los mismos números** que las pestañas correspondientes de la app.
- Pruebas automáticas que lo comprueban con los datos demo.
- No importa ninguna biblioteca de modelos. El módulo `accounting.py` no cambia.

**Dónde va cada parte:**
- **Asistente:** en el repositorio de la app, rama `langgraph`, en un módulo propio `asistente/`, separado de `accounting.py`. El LLM debe ser una **dependencia opcional**, para que la contabilidad siga sin depender de ningún framework.
- **Sistema constructor:** en este repositorio (`agents`), en una carpeta propia dentro de `4_langchain_langgraph/`, porque es una herramienta y no parte de la app.

---

## 3. Control del gasto (leer antes de ejecutar nada de pago)

**La suscripción de Claude no sirve para LangGraph.** La suscripción es para Claude Code y claude.ai. Un grafo llama a la API, facturada aparte. Según la documentación de Anthropic, usar las credenciales de la suscripción desde herramientas de terceros no está permitido. Fuentes: <https://support.claude.com/en/articles/9876003-i-have-a-paid-claude-subscription-pro-max-team-or-enterprise-plans-why-do-i-have-to-pay-separately-to-use-the-claude-api-and-console> y <https://code.claude.com/docs/en/legal-and-compliance.md>.

**Frenos, de más a menos importante:**
1. **Tope duro en la cuenta.** Mantén la recarga automática **desactivada** y carga solo lo que estés dispuesto a gastar: el saldo es el tope. Anthropic permite además límites de gasto mensuales por organización y por workspace (<https://platform.claude.com/docs/en/api/beta/organization/spend_limits.md>; una guía de terceros indica que el workspace *Default* no admite límite propio; las rutas del menú no están confirmadas en fuente oficial: míralo en la Console). **Crea un workspace aparte, con su clave de API, para los experimentos de LangGraph y un límite bajo.**
2. **`recursion_limit` en cada ejecución** *(verificado)*: LangGraph corta el grafo tras N pasos y lanza `GraphRecursionError`. **Desde la versión 1.0.6 el valor por defecto es 1000**, muy alto. Pon un valor bajo (10–25) en cada `invoke`/`stream`, como clave propia de `config` (no dentro de `configurable`). Documentación: <https://docs.langchain.com/oss/python/langgraph/use-graph-api>. Esto frena bucles; no es un tope de dinero.
3. **Contador de coste propio en el estado del grafo**: acumular los tokens de cada llamada y abortar al superar un presupuesto. En el crew faltó y costó caro. Diseñarlo desde la fase 1b.
4. **Empezar sin modelo** (fase 1a): cuesta cero y enseña estado, nodos y aristas.
5. **Con modelo:** el más pequeño, `max_tokens` bajo, pruebas con un modelo simulado, y un informe de coste de cada ejecución desde la primera.

**Para aprender sin gastar:** LangGraph es independiente del modelo. El propio curso incluye un notebook que corre los labs con **modelos locales gratuitos (Ollama)**: `community_contributions/review_4_langchain_langgraph_ollama_GiulioRusso.ipynb`. La calidad y el soporte de herramientas dependen del modelo local. *Sin verificar* cómo se integra con tus herramientas.

**Lecciones de CrewAI que sí se trasladan** (detalle en `3_crewai/guia_ahorro_agentes_crewai.md`): el coste es sobre todo **entrada** (cada vuelta del bucle reenvía el historial); el modelo caro solo para decidir; herramientas de lectura selectiva; peticiones acotadas con comprobaciones objetivas; **no fiarse del informe de un agente y verificar con pruebas y `git diff`**. Lo específico de CrewAI (el borrado del parámetro `pattern`, el parche de la respuesta final forzada, `ConditionalTask`) no hace falta llevarlo.

---

## 4. Lo comprobado de LangGraph (documentación oficial, 23/10/2026)

- Un grafo es un **`StateGraph`** con un estado (por ejemplo un `TypedDict`), **nodos** (funciones) y **aristas**. Las **aristas condicionales** (`add_conditional_edges`) permiten el bucle agente → herramientas → agente.
- Se compila con `compile(checkpointer=...)`. Checkpointers: `InMemorySaver`/`MemorySaver` (memoria) y `SqliteSaver` (fichero SQLite). Se identifica la conversación con un `thread_id` en `config["configurable"]`.
- **Aprobación humana:** dentro de un nodo o herramienta se llama a **`interrupt({...})`**; el grafo se pausa y se reanuda con **`Command(resume=...)`**. Requiere checkpointer. Documentación: <https://docs.langchain.com/oss/python/langgraph/interrupts>.
- Hay una sintaxis de ejecución con `stream_events(..., version="v3")` en los ejemplos actuales; comprueba la versión instalada antes de copiarla.
- *Sin verificar:* cómo se activa el **caché de prompts de Anthropic** con LangChain/LangGraph; cómo medir los tokens por llamada; cómo probar un grafo con un **modelo simulado**.

---

## 5. Opcional: avanzar la app con subagentes de Claude Code (usa la suscripción, no la API)

Se preguntó si se puede montar en Claude Code un equipo equivalente al del crew. Resumen de la documentación (<https://code.claude.com/docs/en/sub-agents.md>, <https://code.claude.com/docs/en/workflows.md>, <https://code.claude.com/docs/en/hooks.md>, <https://code.claude.com/docs/en/costs.md>):

- Un subagente es un archivo `.md` con frontmatter (`name`, `description`, `tools`, `model`…) en `.claude/agents/` (proyecto) o `~/.claude/agents/` (usuario). Tiene su propio contexto y puede usar un modelo más barato.
- **Consumen de la suscripción**, no de la API. Más agentes = más consumo; los *agent teams* llegan a usar bastantes más tokens.
- **No hay garantía de corrección** por tener varios agentes. La corrección la da la **verificación objetiva**: pruebas, revisores de solo lectura, y un **hook** (`TaskCompleted`/`Stop`) que ejecute las pruebas y bloquee con código de salida 2 si fallan.
- Los **workflows** (script que orquesta subagentes) son lo más parecido a un pipeline fijo de CrewAI, con menos determinismo y sin entrada del usuario a mitad de ejecución.
- *Sin verificar:* *agent teams* en el panel de VS Code; detalle de cada evento de hooks; la cuota de workflows de tu plan.

**Equipo mínimo propuesto** (no creado), en `gestion-integral-pyme/.claude/agents/`:
1. **Lead:** el hilo principal de Claude Code.
2. **`probador`:** ejecuta las pruebas y los scripts y devuelve el resultado literal.
3. **`revisor`:** `tools: Read, Glob, Grep`, revisa el `git diff` buscando errores y cambios fuera de alcance.
4. **Un hook** que corra las pruebas antes de dar por terminado un cambio.
5. Front-end y back-end separados solo si una tarea grande se puede repartir en paralelo; para esta app no aportan.

Las pruebas de la app se ejecutan con `uv run test_accounting.py`, `uv run test_app.py` y `uv run scripts/_validate.py` (esperado: 273 componentes y 123 eventos, o más si se añaden pestañas).

---

## 6. Para la sesión de trabajo con LangGraph: primeros pasos concretos

1. Abrir la documentación actual y revisar los labs de esta carpeta (`1_lab1.ipynb` … `5_lab5.ipynb`, `sidekick.py`) como base.
2. En el repositorio de la app, crear la rama `langgraph` y el módulo `asistente/`.
3. Construir la **fase 1a** (sin LLM) con sus pruebas; comprobar los números contra la app.
4. Antes de la fase 1b: workspace aparte con límite bajo en la Console, y decidir el modelo (pequeño o local).
5. Escribir el contador de coste y el `recursion_limit` **antes** de conectar el primer LLM.

---

## 7. Preguntas abiertas (decidir antes de empezar)

1. **¿Quién escribe el código?** Gabi con guía y revisión de Claude, o Claude prepara el esqueleto de la fase 1a para que Gabi lo estudie y lo amplíe.
2. **¿Dónde va la rama de la parte 1?** Propuesta: `gestion-integral-pyme`, rama `langgraph`.
3. **Modelo para las fases 1b/1c:** uno pequeño de Anthropic con el workspace limitado, o uno local con Ollama para aprender sin coste.
4. **¿Se crea el equipo mínimo de subagentes** de la sección 5 para avanzar la app (por ejemplo las peticiones A y B) con la suscripción?
5. **⚖️ Antes de emitir facturas reales** (no es de este plan, pero no olvidar): confirmar con un gestor la retención de IRPF según el epígrafe del IAE y las obligaciones de facturación electrónica (Veri*Factu; las fechas están cambiando: constan 1 de enero y 1 de julio de 2027 con un aplazamiento a octubre de 2028 aún por formalizar). La app **no** cumple Veri*Factu.
