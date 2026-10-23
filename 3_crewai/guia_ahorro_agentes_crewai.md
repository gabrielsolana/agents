# Guía: afinar agentes de CrewAI para que hagan su trabajo gastando menos

Lo aprendido construyendo y evolucionando una app con un crew (`coursework/engineering_team`, octubre de 2026). Pensada para consultarla al empezar un proyecto nuevo. Está ordenada por **impacto**, y lo medido va separado de lo que es una hipótesis.

> **Alcance y límites.** Versiones: CrewAI 1.14.4, SDK de Anthropic 0.73.0, modelos Claude Fable 5.1 (lead) y Sonnet 5.5 (el resto). Todas las cifras de coste son **estimaciones** calculadas con los tokens que cuenta CrewAI y las tarifas que escribimos en `config/tarifas.yaml`; no son la factura de la consola. Los precios y los multiplicadores de caché hay que **volver a comprobarlos** en la página oficial. Los errores de CrewAI de la sección 4 son de esta versión: al actualizar, comprueba si siguen.

---

## 0. Resumen en diez líneas

1. **El coste es entrada, no salida.** Cada vuelta del bucle de herramientas reenvía todo el historial. En un cambio medido, la entrada fue el **89 %** del coste.
2. **Activa el caché de prompts.** CrewAI no lo hace solo. Con 65 llamadas, ahorró un **65 %** (sección 3.2).
3. **Mide antes de optimizar:** una herramienta que lea los contadores de tokens por agente y un fichero de tarifas (3.1).
4. **El modelo caro, solo donde hay juicio** (diseñar, decidir). El resto, al barato (3.4).
5. **Lee menos por iteración:** esquema + búsqueda + lectura por rangos, no archivos enteros (3.3).
6. **Quita tareas que repiten trabajo** y haz condicionales las que no siempre hacen falta (3.5).
7. **Evoluciona, no reconstruyas:** una construcción completa costó 17 USD; un cambio pequeño, 1,3–2,5 (3.6).
8. **Acota las peticiones** y valida que no lleguen vacías (3.7).
9. **Revisa los esquemas de tus herramientas:** CrewAI borra parámetros con ciertos nombres (`pattern`…) y los agentes entran en bucle (4.1).
10. **No te fíes del informe del crew:** comprueba tú el resultado (6).

---

## 1. Qué costó cada cosa (datos reales)

Tarifas usadas, en USD por millón de tokens: Fable 5.1 entrada 10 / salida 50 / lectura de caché 0,25 / escritura 12,5; Sonnet 5.5 entrada 2 / salida 10 / lectura 0,10 / escritura 2,5.

| Ejecución | Coste | Caché | Qué pasó |
|---|---|---|---|
| Construcción completa inicial | 17,26 | no | 61 llamadas. 3,82 M tokens de entrada frente a 0,39 M de salida. |
| Cambio pequeño (exportar CSV) | 12,91 | no | Entrada = 11,48 USD (**89 %**). El frontend, 22 llamadas y 2,4 M de entrada. |
| `apply_review`, 3 refactors | 7,17 | **sí** | 65 llamadas. Sin caché habrían costado ≈ 20,76: **−65 %**. |
| Cambio v1.2.0 (petición vacía) | 6,26 | sí | El lead inventó una funcionalidad a partir de «…» (3.7). |
| Ejecución rota por un parámetro `pattern` | 2,33 | sí | **Sin valor**: cuatro agentes agotaron las iteraciones (4.1). |
| Cierre pequeño v1.2.1 | 2,55 | sí | El lead, 72 % del gasto. |
| Cierre pequeño v1.2.2 | 1,34 | sí | Manual saltado. |
| Consolidar pruebas | 4,11 | sí | 71 llamadas; el backend, 41 llamadas y 14 min. |

Lo que bajó el coste, por orden de efecto: **caché de prompts**, **cambiar de «reconstruir» a «evolucionar»**, **sacar al modelo caro de las tareas mecánicas**, **lectura selectiva de archivos** y **saltarse tareas que no aportan**. Las ejecuciones no son comparables 1:1 (el trabajo era distinto), pero la tendencia es clara.

El gasto acumulado en los informes que vimos superó los **54 USD**, y una parte fue **desperdicio por fallos nuestros** (sección 4).

---

## 2. Por qué cuesta lo que cuesta

Un agente con herramientas funciona en bucle: llama al modelo, ejecuta una herramienta, añade el resultado al historial y vuelve a llamar. **Cada llamada reenvía el historial completo.** Si el agente lee un archivo de 60 KB en la iteración 2, esos tokens se pagan de nuevo en las iteraciones 3, 4, 5… hasta que acaba la tarea.

Consecuencias:
- El coste crece de forma **cuadrática** con el número de iteraciones, no lineal.
- Reducir el **tamaño de lo que entra al historial** y el **número de iteraciones** pesa más que acortar las respuestas.
- Dos tareas que releen los mismos archivos pagan dos veces.

Fórmula de una llamada (los tokens de caché se facturan aparte de la «entrada normal»):

```
coste = ( entrada_normal × p_entrada + lectura_caché × p_lectura
        + escritura_caché × p_escritura + salida × p_salida ) / 1_000_000
```

Ojo con los contadores de CrewAI: `prompt_tokens` y `total_tokens` **excluyen** los tokens de caché. Un `total_tokens=19072` puede esconder ≈ 205.000 tokens de entrada procesados.

---

## 3. Las palancas, por impacto

### 3.1 Medir primero
Sin medir no sabes dónde está el dinero. Lo que montamos:
- Un **fichero de tarifas** por modelo (`config/tarifas.yaml`) que rellenas tú desde la página de precios. Si falta un precio, el informe dice «sin tarifa»; nunca se inventa.
- Una **herramienta** (`Report Token Usage`) que recorre `crew.agents` (más el `manager_agent`) y lee `agent.llm.get_token_usage_summary()`. Cada agente debe tener **su propia** instancia de `LLM` para que el desglose sea limpio.
- **Callbacks** del crew para medir tiempo: `before_kickoff_callbacks=[mark_start]` y `task_callback=mark_task_done`, que anotan cuándo termina cada tarea.
- Una **última tarea** que llama a esa herramienta y redacta el informe (coste, tiempo, concentración del gasto, comentarios). Imprímelo al final de la ejecución.

Lo que descubrimos con esto: el lead (Fable) concentró entre el 37 % y el 72 % del gasto según la ejecución, con pocas llamadas, y el backend fue quien más tiempo gastó moviendo código.

### 3.2 Caché de prompts de Anthropic (el mayor ahorro)
CrewAI 1.14.4 **no envía `cache_control`**. Se vio porque la lectura y escritura de caché eran 0 en todos los informes. La API admite **caché automático**: un único campo `cache_control: {"type": "ephemeral"}` en la raíz de la petición, cuyo punto de corte avanza solo al crecer la conversación.

- El SDK 0.73.0 no tiene parámetro para ello, pero `extra_body` lo deja pasar. El parche está en el apéndice A.1 (probado con CrewAI y con llamadas directas).
- Precios según la documentación: escritura **1,25×** la entrada (caché de 5 min), lectura **0,1×** (Fable 5.1: 0,025×; Sonnet 5.5: 0,05×). Mínimo cacheable: 512 tokens para estos modelos. Vida de 5 minutos, renovada con cada uso. Documentación: <https://platform.claude.com/docs/en/build-with-claude/prompt-caching>.
- **Cuanto más largo el bucle, más ahorro.** Modelo teórico (el historial crece por igual en cada llamada): 4 llamadas ≈ 47 %, 10 ≈ 73 %, 22 ≈ 85 %. Lo medido: **24 %** en una ejecución de 4 llamadas y **65 %** en una de 65. En tareas de una sola llamada, la escritura (+25 %) cuesta más de lo que se ahorra, pero apenas se nota.
- Comprueba que funciona mirando `cached_prompt_tokens` y `cache_creation_tokens` en el informe. Si son 0, no está activo.
- Ponle un interruptor (`ANTHROPIC_PROMPT_CACHE=0`) para poder comparar.

### 3.3 Leer menos en cada iteración
El archivo grande que un agente lee entero se paga en cada vuelta. Herramientas que lo evitan:
- **Esquema** (`Outline`): para un `.py`, clases y funciones con su rango de líneas; para un `.md`, los encabezados. El esquema de un archivo de 64 KB ocupó **3,2 KB (el 5 %)**.
- **Búsqueda** (`Search`) con expresión regular, que devuelve `archivo:línea: texto`, con tope de resultados.
- **Lectura por rangos** (`Read` con `start_line` y `end_line`), con las líneas numeradas.
- Y en los prompts: «no leas archivos grandes enteros; localiza y lee solo el rango».

Advertencia: esta mejora falló dos veces por culpa de la herramienta (4.1 y 4.3). Pruébala con un agente suelto antes de ponerla en un crew (sección 5).

### 3.4 Modelo caro solo donde hay juicio
- **Fable (caro):** diseñar y decidir qué hallazgos se aplican.
- **Sonnet (barato):** implementar, probar, auditar, versionar, redactar informes.
- Pasamos las tareas mecánicas del lead (registrar la versión y escribir el informe de coste) a un agente aparte en Sonnet. El gasto del lead bajó en las ejecuciones siguientes (4,46 → 3,04 → 1,83 → 0,75 USD), pero eran trabajos distintos y a la vez cambiaron otras cosas (lectura selectiva, caché): no se puede atribuir la bajada solo a esto. Cuidado: ese agente debe ir **en la lista de agentes del crew**, o sus tokens no se cuentan en el informe.
- Antes de poner un modelo caro, pregunta: ¿esta tarea cambia de calidad si la hace uno barato? Si la respuesta es «no» o «no lo sé», empieza por el barato y mide.

### 3.5 Menos tareas, y condicionales las que no siempre hacen falta
- **Quita tareas que repiten.** En el modo «aplicar una revisión», el diseño (27,9 KB) repetía la decisión (15,4 KB) con otras palabras. Se eliminó y la decisión pasó a ser la especificación (**efecto todavía sin medir**: no se ha vuelto a ejecutar ese modo).
- **`ConditionalTask`** para lo que solo a veces es necesario. Ejemplo: actualizar el manual de usuario solo si el cambio es visible para el usuario. Detalles: no puede ser la primera tarea, la condición recibe la salida de la tarea anterior (puedes ignorarla y mirar tu propio estado), y una tarea saltada produce una salida vacía y **no dispara `task_callback`** (apéndice A.5).
- **Revisores (UX, fiscal, calidad…) solo en construcciones completas**, no en cada cambio pequeño: un informe que nadie aplica es dinero tirado.
- Un agente que solo informa no debería tener herramientas de escritura.

### 3.6 Evolucionar, no reconstruir
Una construcción completa borra y regenera todo: 17 USD. Un cambio sobre lo existente: 1,3–2,5 USD. Para eso:
- Un modo «cambio» que **no resetea** el espacio de trabajo y recibe la petición como entrada.
- Una **copia de seguridad automática** antes de cada ejecución.
- Una herramienta de edición por **sustitución exacta** (`Replace`) en lugar de reescribir archivos enteros: ahorra tokens de salida y evita truncados. Con una comprobación de sintaxis antes de escribir un `.py` (una escritura truncada llegó a corromper un módulo).
- Si el espacio de trabajo es un repositorio git, **impide que el modo de reconstrucción lo borre**, y que los agentes lean o escriban en `.git` (los hooks se ejecutan en tu máquina).

### 3.7 Peticiones acotadas y validadas
- Un texto de petición vacío o de relleno (`"…"`) llegó al crew: el lead **inventó una funcionalidad** y la ejecución costó 6,26 USD. Valida una longitud mínima antes de lanzar nada.
- Una buena petición lleva: contexto breve, **qué hacer** numerado, **qué NO tocar**, comprobaciones **objetivas** con números (por ejemplo «el JSON de salida debe ser idéntico byte a byte», «273 componentes y 123 eventos», un ejemplo con cifras exactas), y los nombres de los archivos que debe crear.
- Pide que, si descubren un defecto fuera del alcance, **lo describan y no lo corrijan**.
- Parte en peticiones pequeñas y ordenadas (la 2 depende de la 1…); las grandes se quedan a medias o se encarecen.

### 3.8 Límite de iteraciones y contención de bucles
- `max_iter` por defecto: 25. Las tareas con docenas de ediciones pequeñas necesitan ~40 (`max_iter=40` en los ingenieros).
- Subirlo sin más aumenta el coste de un bucle. Acompáñalo de un **guardián de llamadas repetidas** (apéndice A.3): una llamada idéntica a la anterior, sin otra distinta en medio, se responde con un mensaje de una línea en vez de ejecutarse. Reinícialo al terminar cada tarea.
- Idea no implementada: un **tope de gasto** que aborte al terminar una tarea si el coste estimado supera un límite. Con saldo bajo vale la pena.

---

## 4. Errores que cuestan dinero (en CrewAI 1.14.4)

### 4.1 Un parámetro llamado `pattern` desaparece del esquema (el más caro)
- **Síntoma:** el agente llama a la herramienta sin ese argumento, recibe «Field required», y repite lo mismo hasta agotar las iteraciones. En el log, `Args:` no muestra el parámetro. Cuatro agentes acabaron con exactamente 26 llamadas (25 + la respuesta forzada).
- **Causa:** `sanitize_tool_params_for_anthropic_strict` borra de forma recursiva toda clave llamada como una palabra reservada de JSON Schema, **incluso cuando es el nombre de un parámetro**. Se borran: `pattern`, `patternProperties`, `propertyNames`, `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `multipleOf`, `minLength`, `maxLength`, `minItems`, `maxItems`, `uniqueItems`, `minProperties`, `maxProperties`, `minContains`, `maxContains`, `dependentRequired`, `dependentSchemas`, y también las de metadatos `default`, `title`, `example`, `examples`, `deprecated`, `readOnly`, `writeOnly`, `$comment`.
- **Arreglo:** no uses esos nombres como parámetros (nosotros renombramos `pattern` a `regex`).
- **Prevención:** un script que compare las propiedades antes y después de sanitizar (apéndice A.4). Ejecútalo sobre **todas** las herramientas de todos los agentes.

### 4.2 La respuesta final forzada rompe la ejecución con los modelos nuevos
- **Síntoma:** al agotar `max_iter`, `400: This model does not support assistant message prefill. The conversation must end with a user message`. Toda la ejecución cae.
- **Causa:** CrewAI añade la instrucción «da tu respuesta final» como un mensaje de rol `assistant`.
- **Arreglo:** parche que la envía como mensaje de `user` (apéndice A.2). Probado con Fable.
- Ojo: este error puede **ocultarse** tras otro. Si tu crew «termina» con tareas vacías, mira si hubo «Maximum iterations reached».

### 4.3 Llamadas idénticas en ráfaga
- **Síntoma:** decenas de llamadas iguales a la misma herramienta en una sola respuesta (113 en una ejecución), cada una devolviendo un resultado grande.
- **Arreglo:** el guardián del apéndice A.3. No evita que el modelo las emita, pero evita pagar cada resultado.

### 4.4 Un veredicto «cumplido» o «no cumplido» sin valor
Cuando los agentes agotan sus iteraciones, el crew sigue y su auditor puede decir «NO CUMPLIDO» porque no llegó a ejecutar nada. El coste fue bajo (2,33 USD) precisamente porque no trabajaron. **Un informe barato no es un buen informe.** Busca en el log «Maximum iterations reached».

### 4.5 Una prueba que lanza el pipeline de pago
Probar una protección con un texto de ejemplo válido arrancó el crew real. Prueba las guardas con entradas que **no puedan** pasar la validación, o con el crew sustituido, y avisa antes de cualquier llamada que cueste dinero.

---

## 5. Cómo probar sin gastar

1. **Esquemas de herramientas:** el script del apéndice A.4, sin llamadas a la API.
2. **Un agente suelto, de 2–4 llamadas** (céntimos): una tarea mínima («¿en qué línea empieza la función X?») con `max_iter=8` y la lista de herramientas a probar. Sirvió para reproducir el bucle de `pattern`, para confirmar que Search funciona tras renombrarlo y para ver que Sonnet y Fable usan bien la herramienta. Imprime `agent.llm.get_token_usage_summary().successful_requests`: si pasa de 3–4, algo falla.
3. **Llamada directa a la API** con el esquema de CrewAI para ver qué emite el modelo: así se separó «el modelo no lo envía» de «CrewAI lo pierde».
4. **Guardas y parches con simulaciones**: 30 hilos llamando a la vez a una herramienta para el guardián de repetidos; una conversación acabada en `assistant` para el parche de la respuesta final.
5. **Primeras ejecuciones del crew, pequeñas y vigiladas:** `2>&1 | Tee-Object` a un fichero y Ctrl+C en cuanto veas el mismo mensaje repetido.

---

## 6. Verificar lo que dice el crew

Los agentes informan de lo que creen haber hecho, y los auditores no tienen un `diff`. Lo que sí funcionó:
- **Comparar con la copia de seguridad previa** (`cmp` de los archivos que no deberían cambiar).
- **Ejecutar tú todas las pruebas y los scripts** de comprobación, no confiar en la cifra del informe.
- **Demostrar que un cambio «sin efecto» lo es:** comparar el árbol sintáctico (`ast`) antes y después, quitando docstrings y anotaciones; si coincide, el comportamiento no ha cambiado.
- **Comprobar que los datos reales no se tocaron** (`cmp` del fichero de datos).
- **Cuidado con los recuentos:** al consolidar pruebas, el crew documentaba «Smoke::*» en bloque y renombraba pruebas. Hay que comprobar por nombre qué desapareció y dónde está su equivalente.
- Incoherencias entre informes (el manual decía «comprobado con X» mientras el auditor decía que nadie tenía X) son una señal para mirar el código, no el informe.

---

## 7. Lo que NO compensó

- **Imponer métricas de calidad** (40 líneas, complejidad 10, docstring en todo). Generaron 142 avisos y tres peticiones de limpieza que no aportaban nada visible; el coste de cumplirlos, más los tokens extra en cada ejecución, no justificó el beneficio. Elige estándares que sirvan a un propósito, no cifras redondas.
- **Reorganizar pruebas por tema** (4,11 USD): útil, pero sin cambio visible. Hazlo solo cuando las suites estorben de verdad.
- **Un manual de usuario en cada cambio.** Sustituido por una tarea condicional.
- **Revisión de código en cada cambio.** Reservada a las construcciones completas.

---

## 8. Lista de comprobación para un proyecto nuevo

1. **Fija versiones** (CrewAI y SDK) y mira el changelog. Todo lo de la sección 4 puede haberse arreglado, o puede haber errores nuevos.
2. **Antes de la primera ejecución:** fichero de tarifas, herramienta de informe de coste, callbacks de tiempo, y una tarea final de informe.
3. **Aplica el parche de caché** (A.1) y comprueba que `cached_prompt_tokens` > 0 desde la primera ejecución real.
4. **Aplica el parche de la respuesta final** (A.2).
5. **Revisa los esquemas** de todas las herramientas con el script A.4. Nada de parámetros llamados como palabras reservadas.
6. **Un `LLM` por agente**; modelo caro solo para diseñar y decidir.
7. **Herramientas de lectura selectiva** (esquema, búsqueda, rangos) y de edición por sustitución, con comprobación de sintaxis. Protege los ficheros de configuración y `.git`.
8. **`max_iter` razonable** y el guardián de llamadas repetidas.
9. **Modos de ejecución:** construir, cambiar, revisar. El de cambio no resetea; hay copia de seguridad automática.
10. **Valida las peticiones** (longitud mínima) y escríbelas con «qué hacer / qué NO tocar / comprobaciones objetivas».
11. **Primeras ejecuciones pequeñas**, con log a fichero, vigilando repeticiones.
12. **Verifica tú los resultados** (sección 6). Mide el coste de cada ejecución y compara con las anteriores.
13. **Fija un presupuesto** y comprueba el saldo antes de lanzar una petición grande. Si puedes, implementa el tope de gasto.

---

## Apéndice A — Código reutilizable

Los originales están en `coursework/engineering_team/src/engineering_team/` (`patch.py`, `tools/cost_tools.py`, `tools/sandbox_tools.py`). Se importa `patch.py` al arrancar (`import engineering_team.patch`).

### A.1 Caché de prompts (parche)
```python
import functools, os
from anthropic.resources.messages import AsyncMessages, Messages

def _with_prompt_cache(original):
    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        body = dict(kwargs.get("extra_body") or {})
        body.setdefault("cache_control", {"type": "ephemeral"})   # caché automático
        kwargs["extra_body"] = body
        return original(self, *args, **kwargs)
    wrapper._prompt_cache_patched = True
    return wrapper

if os.environ.get("ANTHROPIC_PROMPT_CACHE", "1") != "0":          # interruptor para comparar
    for cls in (Messages, AsyncMessages):
        for name in ("create", "stream"):
            if not getattr(getattr(cls, name), "_prompt_cache_patched", False):
                setattr(cls, name, _with_prompt_cache(getattr(cls, name)))
```

### A.2 Respuesta final forzada como mensaje de usuario (parche)
```python
from crewai.agents import crew_agent_executor
from crewai.utilities import agent_utils

def _handle_max_iterations_exceeded(formatted_answer, printer, messages, llm, callbacks, verbose=True):
    instruction = agent_utils.I18N_DEFAULT.errors("force_final_answer")
    if formatted_answer and hasattr(formatted_answer, "text"):
        instruction = formatted_answer.text + f"\n{instruction}"
    messages.append(agent_utils.format_message_for_llm(instruction, role="user"))   # antes: "assistant"
    answer = llm.call(messages, callbacks=callbacks)
    if answer is None or answer == "":
        raise ValueError("Invalid response from LLM call - None or empty.")
    formatted = agent_utils.format_answer(answer=answer)
    if isinstance(formatted, agent_utils.AgentFinish):
        return formatted
    return agent_utils.AgentFinish(thought=formatted.thought, output=formatted.text, text=formatted.text)

agent_utils.handle_max_iterations_exceeded = _handle_max_iterations_exceeded
crew_agent_executor.handle_max_iterations_exceeded = _handle_max_iterations_exceeded  # se importó por nombre
```

### A.3 Guardián de llamadas idénticas repetidas
```python
import functools, threading
_lock, _last_call = threading.Lock(), None
REPEATED = ("Repeated call ignored: identical to the previous one; its result is already above. "
            "Change the arguments or use another tool.")

def reset_repeat_guard():            # llamar al terminar cada tarea y al empezar el crew
    global _last_call
    with _lock: _last_call = None

def no_immediate_repeat(func):       # @tool("...") encima, @no_immediate_repeat debajo
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        global _last_call
        sig = (func.__name__, repr(args), repr(sorted(kwargs.items())))
        with _lock:
            repeated, _last_call = sig == _last_call, sig
        return REPEATED if repeated else func(*args, **kwargs)
    return wrapper
```

### A.4 Comprobar que CrewAI no borra parámetros de tus herramientas
```python
from crewai.utilities import pydantic_schema_utils as psu
from crewai.utilities.agent_utils import convert_tools_to_openai_schema

for tool in todas_las_herramientas:                       # de todos los agentes
    params = convert_tools_to_openai_schema([tool])[0][0]["function"]["parameters"]
    perdidos = set(params["properties"]) - set(
        psu.sanitize_tool_params_for_anthropic_strict(params)["properties"])
    assert not perdidos, f"{tool.name}: parámetros que el modelo no verá: {perdidos}"
```

### A.5 Coste por agente, tiempo por tarea y tarea condicional
```python
# Coste: tarifas en USD por millón de tokens
def coste(u, t):   # u = agent.llm.get_token_usage_summary(); t = tarifas del modelo
    return (u.prompt_tokens * t["entrada"] + u.completion_tokens * t["salida"]
            + u.cached_prompt_tokens * t["lectura_cache"]
            + u.cache_creation_tokens * t["escritura_cache"]) / 1_000_000
# el nombre del modelo en CrewAI no lleva prefijo de proveedor: "claude-sonnet-5-5", no "anthropic/claude-sonnet-5-5"

# Tiempo y condición en el crew
Crew(agents=[...], tasks=[...],
     before_kickoff_callbacks=[mark_start],      # pone en marcha el reloj
     task_callback=mark_task_done)               # anota el fin de cada tarea

from crewai.tasks.conditional_task import ConditionalTask
@task
def manual_task(self) -> Task:
    return ConditionalTask(config=self.tasks_config["manual_task"],
                           condition=lambda _salida_anterior: hay_cambio_visible())
```

---

## Apéndice B — Trampas de Windows, uv y Docker (no son de coste, pero hacen perder tiempo)

- **Salida de `subprocess` en Windows:** con `text=True` decodifica con cp1252 y revienta con emojis o tildes. Usa `encoding="utf-8", errors="replace"`.
- **`| Tee-Object` y caracteres raros:** pasa `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` en PowerShell antes de lanzar, y en Python `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` al arrancar (sin esto, CrewAI cae al imprimir emojis cuando la salida va a una tubería).
- **`uv init` dentro de otro proyecto** añade el subproyecto como miembro del *workspace* del padre y abre un riesgo de seguridad. Usa `uv init --no-workspace`.
- **Docker con la carpeta montada:** `uv run` crea un `.venv` de Linux dentro de tu carpeta y Windows luego no puede borrarlo. Usa `-e UV_PROJECT_ENVIRONMENT=/tmp/venv`, y `-e PYTHONPATH=/workspace` si los scripts de una subcarpeta importan módulos de la raíz.
- **Enlaces simbólicos:** las herramientas que escriben en el host (versionado, listados) deben rechazarlos o no seguirlos; un script ejecutado en Docker puede crearlos.
- **`Crew(tracing=True)`** mostró enlaces a `app.crewai.com`: parece que se suben trazas. No lo he verificado; revisa qué sale de tu máquina antes de usarlo con datos reales.

---

## Apéndice C — Qué no se ha comprobado

- **El tope de gasto** (abortar si el coste estimado supera un límite) no está implementado.
- **Si versiones posteriores de CrewAI corrigen** el borrado de `pattern`, la respuesta final forzada o el caché automático. Revísalo al actualizar.
- **Otros modelos** (por ejemplo Haiku) y otros proveedores: no se han probado.
- **Las cifras de coste** son estimaciones; no se contrastaron con la factura de la consola.
- **El ahorro del caché** depende del tipo de tarea. Los 65 % medidos son de un caso concreto.
- **Si el modelo caro es necesario** para el diseño: lo asumimos, pero no hicimos la comparación con Sonnet.
