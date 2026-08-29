# AGENTS - Reglas del proyecto

> Workspace: `Nueva carpeta` (Windows, sin git). Proyectos: `material/` (Python reportlab), `EscanerRed/` (.NET 8), `planificador-guardias/` (Apps Script), `reverse_linked_list.py` y otros sueltos.

## 1. Manejo de ambigüedad - Modo PERMISIVO (activo)

**Principio:** No molestar preguntando de más. Solo preguntar si hay duda real o múltiples caminos válidos.

### CUÁNDO SÍ preguntar (usar `question` tool):
1.  El pedido tiene 2+ interpretaciones válidas y elegir mal implica rehacer trabajo (ej: "mejora el planificador" -> ¿`Code.gs`, `Index.html`, o sheets?).
2.  El cambio es destructivo/irreversible (sobrescribir `material/salida/Guia_Redes_Servidores_DataCenters.pdf`, borrar filas en `EscanerRed`, `rm`).
3.  Falta info crítica para decidir parámetro/librería y no hay convención en el archivo (ej: "agrega autenticación" -> ¿SpreadsheetApp, OAuth, o nada?).
4.  El costo de asumir mal > costo de 1 pregunta.

Formato de pregunta: 2-3 opciones cortas, primera = recomendada. Ej:
> ¿Planificador? [Recomendado: solo lógica Code.gs] / [solo UI Index.html] / [ambos]

### CUÁNDO NO preguntar (ejecutar directo):
- Hay un camino obvio por convención del archivo o contexto previo.
- Cambio menor, reversible, de estilo/nombre/comentario.
- El usuario ya dio criterio explícito.
- Solo es informacional.

**Anti-patrón prohibido:** Preguntar por cada detalle trivial ("¿qué color?", "¿qué nombre de variable?") cuando hay default razonable. Asumí y documentá lo asumido en 1 línea.

### Comportamiento esperado:
- Si no preguntas, deja una nota corta de lo asumido: `// Asumido: ...` o en el mensaje final.
- Si preguntas, espera respuesta antes de editar. No edites y preguntes a la vez.

## 2. Notas de verificación y docs
- Verificación automática (tests/build) y fetch de docs externo están DESACTIVADOS a pedido del usuario. No ejecutar `dotnet build` / `pytest` automático tras cada edit.
- Si el usuario pide explícitamente verificar, ahí sí ejecutar.

## 3. Rutas con espacios
Siempre quotear paths: `"C:\Users\jerem\Desktop\Nueva carpeta\..."` en bash (PowerShell 5.1).

## 4. Capacidad instalada — SCRAPING + BOTS TELEGRAM + HOSTING 24/7 GRATUITO (actualizado 2026-08-27)

> **Stack operativo:** Playwright Python CDP (`chrome --remote-debugging-port=9222`) + `python-telegram-bot==20.7` modular + `FastAPI /health` + `Render Free` (sin tarjeta) + `UptimeRobot` keep-alive. **Modo multi-agente PERMANENTE ACTIVO para TODOS los pedidos:** todo pedido se delega en subagentes especializados (scraper / bot / devops / frontend / backend / presentaciones) y el agente principal supervisa integración y calidad.

- **Chrome debug (local, Windows):** `& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=".chrome-debug"` -> verificar `http://localhost:9222/json/version`. Código: `scraper/base.py` hace `connect_over_cdp("http://localhost:9222")` si responde, else `launch(headless=True)` para nube.
- **Scraping:** `playwright`, `beautifulsoup4`, `lxml`, `httpx`, `pydantic` (datos públicos/APIs). Plantilla: `scraper/ejemplo_publico.py`. Flujo: local debug -> prod headless sin cambios.
- **Bots Telegram:** `bot/main.py` (Application PTB polling + JobQueue) + `bot/handlers/` (`start`, `scraper`, `utilidades`) + `bot/jobs/scheduler.py`. Modular: cada nuevo bot = nuevo handler. Health endpoint `GET /health` en thread `uvicorn` puerto `8000`/`PORT`.
- **Hosting 24/7 gratuito SIN tarjeta (elegido):** `Render Free` (750h/mes, sleep 15min) + `UptimeRobot` ping cada 5min a `/health` = 24/7 real. Alternativa `Koyeb Free`/`PythonAnywhere` descartadas para polling. `Fly.io`/`Oracle` requieren tarjeta (no usar si usuario exige sin tarjeta).
- **Deploy:** `GitHub -> Render` auto-deploy, `Dockerfile` python:3.12-slim + `playwright install`, `render.yaml` healthCheckPath `/health`, secrets via `TELEGRAM_TOKEN` en dashboard Render.
- **Env:** `.env.example` -> `TELEGRAM_TOKEN`, `CHROME_CDP_URL`, `PORT`, `MODO`. `.env` gitignored.
- **Uso rápido:** usuario dice `creame un bot que haga X` -> agregar handler en `bot/handlers/` + job si necesita scraping + `git push`. No re-configurar nube.
- **Delegación FREE por fortaleza (solo modelos `*-free`, actualizado 2026-08-27):**
  | Modelo | Rol | Usar cuando |
  |---|---|---|
  | `opencode/mimo-v2.5-free` | **Visión** | Leer imágenes, OCR, screenshots, diagramas, validar slides (`presentaciones/`, `paint_screenshot.png`) |
  | `opencode/nemotron-3-ultra-free` | **Razonamiento/Arquitectura** | Scraping complejo, decisiones infra, jobs async |
  | `opencode/nemotron-3.5-lightning-free` | **Micro-tareas rápidas** | Handlers simples (`/ping`/`/eco`), fixes chicos |
  | `opencode/big-pickle` | **Código creativo** | PPTX/ilustraciones, `material/build_libro.py`, animaciones |
  | `opencode/hy3-free` | **Búsqueda/embeddings** | RAG en `material/`, indexado |
  | `opencode/muse-spark-1.2-contributor-free` | **Supervisor** | Coordina subagentes, valida `scraper/base.py`/`bot/main.py`, integra deploy |
  Regla: para cada pedido el supervisor elige modelo según tabla, siempre free. Si hay imagen -> obligatoriamente `mimo`.

## 5. Criterio visual para presentaciones — MODO ILUSTRACIONES (actualizado 2026-08-23)

> **Config ilustrada guardada:** `presentaciones/CONFIG_ILUSTRACIONES.json` + token `HF_TOKEN.txt` Fine-grained. Leer SIEMPRE si el usuario pide presentaciones con imágenes.

- **HF_TOKEN obligatorio Fine-grained:** Debe tener permiso **“Make calls to Inference Providers”** (Read solo da 403). Ubicación: `presentaciones/HF_TOKEN.txt` (37 chars, probado `hf_Dqf...` OK 2026-08-23). Endpoint: `router.huggingface.co/fal-ai/fast-sdxl`.
- **Generación:** `python presentaciones/generador_visual.py --prompt "..." --estilo ilustracion/foto --w 1024 --h 768` → API SDXL/FLUX (15-25s/img, cache `presentaciones/cache/<hash>.png`). Estilos: `foto` (FLUX.1-schnell), `ilustracion`/`diagrama` (SDXL). Pruebas OK: 572 KB, 1045 KB, 237 KB.
- **GPU:** Solo para 3D (Three.js/WebGL/Playwright/ffmpeg). **IA local desinstalada** (diffusers/accelerate borrados 2026-08-23, modelo 5.2GB eliminado) — no usar `torch.cuda` para difusión.
- **Reglas de composición:** sujeto >65% frame, fondo limpio oscuro `#0f141a` para foto o blanco para diagrama/ilustración, máx 6 palabras/título, paleta `#0f141a/#3498db/#2c3a4f` (médica teal `#0E7C8A`), tipografía Segoe UI, sombra suave. Negative: `blurry, low-res, deformed, watermark, text, logo`.
- **PPTX:** 16:9 (13.33×7.5"), `python-pptx`, imágenes 1024×768 vía `add_picture`, transición Morph. Plantillas: `generar_creatina.py` (2 slides prueba), `generar_higado_medico.py` (10 slides), `generar_piaget.py`.
- **Fallback:** Si 403 → pedir recrear token Fine-grained. Si no hay token → modo anónimo limitado o Pillow/rembg offline (avisar calidad menor).
