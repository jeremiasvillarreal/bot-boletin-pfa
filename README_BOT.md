# Bot Scraper - Guía Hosting Gratuito 24/7

Stack: `python-telegram-bot==20.7` + `Playwright` + `FastAPI /health` + `Render Free` + `UptimeRobot`. Sin tarjeta requerida.

---

## 1) Crear bot en BotFather -> Token

1. Abrí Telegram y buscá `@BotFather`.
2. Enviá `/newbot` -> elegí nombre (ej: `Mi Scraper Bot`) y username (ej: `miscraper_bot`, debe terminar en `bot`).
3. Copiá el **token** que te devuelve (formato `123456:ABC-...`). **No lo compartas.**
4. Opcional: `/setdescription` y `/setcommands` para configurar descripción y comandos.
5. Guardá el token para el paso 2 y 3 (variable `TELEGRAM_TOKEN`).

> Tip: si perdés el token, `/mybots` -> tu bot -> `API Token` -> `Revoke` genera uno nuevo.

---

## 2) Local: .env + instalación + Chrome Debug + run

### 2.1 .env

Creá `.env` en la raíz (está gitignored). Basate en `.env.example`:

```ini
TELEGRAM_TOKEN=123456:ABC-tu_token_aqui
CHROME_CDP_URL=http://localhost:9222
PORT=8000
MODO=local
```

### 2.2 Instalación

```powershell
pip install -r requirements-bot.txt
playwright install chromium
# o con deps si faltan libs:
# playwright install --with-deps chromium
```

Contenido esperado de `requirements-bot.txt`:
```
python-telegram-bot==20.7
playwright
beautifulsoup4
lxml
httpx
pydantic
fastapi
uvicorn
python-dotenv
```

### 2.3 Chrome Debug (Windows)

```powershell
# Opción A: script del repo
powershell -ExecutionPolicy Bypass -File scripts/launch_chrome_debug.ps1

# Opción B: manual
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=".chrome-debug"
```

Verificá: abrí `http://localhost:9222/json/version` -> debe responder JSON con `webSocketDebuggerUrl`.

> `scraper/base.py` hace `connect_over_cdp("http://localhost:9222")` si responde, si no hace `launch(headless=True)` (modo nube).

### 2.4 Run

```powershell
python bot/main.py
```

Debe loguear:
- `Bot iniciado @tu_bot`
- `Health server en :8000` -> probá `http://localhost:8000/health` -> `{"status":"ok"}`

Probá en Telegram: `/start` debe responder.

---

## 3) Deploy en Render (Free, sin tarjeta) - GitHub auto-deploy

### 3.1 Preparación

```powershell
git add Dockerfile render.yaml bot/ scraper/ requirements-bot.txt .dockerignore
git commit -m "feat: bot + devops free hosting"
git push origin main
```

Verificá que `Dockerfile` y `render.yaml` estén en la raíz (ya creados).

### 3.2 Crear servicio en Render

1. Entrá a https://dashboard.render.com -> `New +` -> `Web Service` -> conectá tu repo `Nueva carpeta` (o repo GitHub donde pusheaste).
2. Render detecta `render.yaml` (Blueprint) o configurá manual:
   - **Environment:** `Docker` (usa `Dockerfile`)
   - **Plan:** `Free`
   - **Docker Command:** `python bot/main.py`
   - **Health Check Path:** `/health`
3. En `Environment` -> `Add Environment Variable`:
   | Key | Value | Notas |
   |-----|-------|-------|
   | `TELEGRAM_TOKEN` | `123456:ABC...` | `sync: false` (secreto) |
   | `PORT` | `8000` | Render lo inyecta, pero dejalo en 8000 |
   | `MODO` | `cloud` | Activa `launch(headless=True)` |
   | `CHROME_CDP_URL` | `http://localhost:9222` | No se usa en cloud, pero requerido por `render.yaml` |
4. `Create Web Service` -> Deploy (5-10 min, instala `playwright install --with-deps chromium` dentro del Dockerfile).
5. Al terminar, copiá la URL: `https://bot-scraper-xxxx.onrender.com` -> probá `https://bot-scraper-xxxx.onrender.com/health` -> debe dar `200 {"status":"ok"}`.

> **Alternativa Blueprint:** `New +` -> `Blueprint` -> seleccioná repo -> Render lee `render.yaml` y crea el servicio automáticamente.

### 3.3 Logs

En Render Dashboard -> tu servicio -> `Logs` -> debe verse `Application started on port 8000` y polling del bot sin errores `401 Unauthorized` (si ves 401, el token está mal).

---

## 4) UptimeRobot: ping cada 5 min a /health para 24/7 real

Render Free duerme tras 15 min sin tráfico. UptimeRobot lo mantiene vivo.

1. Creá cuenta gratis en https://uptimerobot.com (sin tarjeta, 50 monitores gratis).
2. `Add New Monitor`:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `bot-scraper-health`
   - **URL:** `https://tu-app.onrender.com/health`
   - **Monitoring Interval:** `5 minutes`
3. `Create Monitor` -> debe mostrar `Up` en 1-2 minutos.
4. Opcional: activá alertas por email/Telegram si cae.

> Con esto el bot queda 24/7 dentro de las 750h/mes gratis de Render (suficiente para 1 servicio always-on). Si superás horas, Render pausa hasta el mes siguiente.

---

## 5) Cómo agregar un nuevo handler

Arquitectura modular: `bot/main.py` (Application + JobQueue) + `bot/handlers/` + `bot/jobs/scheduler.py`.

### 5.1 Crear handler

Creá `bot/handlers/mi_bot.py`:

```python
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

async def mi_comando(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Hola desde mi_bot!")

# handler exportable
handler = CommandHandler("micomando", mi_comando)
```

### 5.2 Registrar en main

En `bot/main.py`:

```python
from bot.handlers.mi_bot import handler as mi_handler

# dentro de build_application():
application.add_handler(mi_handler)
```

### 5.3 Si necesita scraping + JobQueue

```python
# bot/jobs/scheduler.py
from telegram.ext import ContextTypes
from scraper.ejemplo_publico import scrape

async def job_scrape(context: ContextTypes.DEFAULT_TYPE):
    data = await scrape()
    await context.bot.send_message(chat_id="@tu_canal", text=str(data))

# en main.py:
application.job_queue.run_repeating(job_scrape, interval=3600, first=10)
```

### 5.4 Deploy

```powershell
git add bot/handlers/mi_bot.py bot/main.py
git commit -m "feat: add mi_bot handler"
git push
# Render redeployeea solo -> UptimeRobot sigue pingueando sin cambios
```

---

## Troubleshooting

| Problema | Causa | Solución |
|----------|-------|----------|
| `401 Unauthorized` en logs | Token inválido/revocado | Regenerá en @BotFather, actualizá `TELEGRAM_TOKEN` en `.env` y en Render Dashboard -> `Environment` -> `Save` -> redeploy |
| `Timed out` / bot no responde | Render dormido sin UptimeRobot | Verificá UptimeRobot `Up` y que URL sea `/health` con `https`. Probá `curl https://tu-app.onrender.com/health` |
| `playwright install` falla en Docker | Falta lib o cache corrupto | Dockerfile ya instala `libnss3...libasound2`. Si falla, `docker build --no-cache .` local o `Clear build cache` en Render |
| `Target closed` / `Browser closed` | Chrome CDP no conectado en local | Lanzá `scripts/launch_chrome_debug.ps1` y verificá `http://localhost:9222/json/version`. En cloud debe ir por `launch(headless=True)` (`MODO=cloud`) |
| `/health` 404 | FastAPI thread no iniciado | Verificá `bot/main.py` lanza `uvicorn` en thread puerto `PORT`. Logs deben decir `Health server en :8000` |
| `Conflict: terminated by other getUpdates` | Dos instancias polling mismo token | Dejá solo una: detené local (`Ctrl+C`) si Render está corriendo, o viceversa. Un token = un polling |
| Build lento (>10min) | `playwright install --with-deps` pesado | Normal primer deploy. Siguientes usan cache. No canceles |
| `.env` subido a GitHub | Token expuesto | `git rm --cached .env`, rotá token en @BotFather, verificá `.gitignore` y `.dockerignore` incluyen `.env` |

### Comandos útiles

```powershell
# Ver logs locales
python bot/main.py --verbose

# Probar health
curl http://localhost:8000/health
curl https://tu-app.onrender.com/health

# Ver Chrome debug
curl http://localhost:9222/json/version

# Test Docker local
docker build -t bot-scraper .
docker run -p 8000:8000 --env-file .env bot-scraper
```

---

**Flujo resumen:** BotFather -> `.env` local + `pip install` + `launch_chrome_debug.ps1` -> `python bot/main.py` -> `git push` -> Render (Docker + env vars + /health) -> UptimeRobot cada 5 min -> nuevo handler en `bot/handlers/` + registro.
