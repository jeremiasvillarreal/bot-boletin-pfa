"""
bot.main — Entrypoint del Bot Telegram modular 24/7.

Flujo:
  1. Carga config (TELEGRAM_TOKEN, PORT, etc.) con validación
  2. Inicia FastAPI /health en thread daemon (uvicorn) para Render + UptimeRobot keep-alive
  3. Construye telegram.ext.Application, registra handlers modulares y JobQueue
  4. Inicia polling bloqueante (run_polling) con manejo de señales y logging

Arquitectura modular:
  - bot/handlers/start.py       -> /start, /help
  - bot/handlers/scraper.py     -> /watch, /scrape_demo (+ placeholder /precio)
  - bot/handlers/utilidades.py  -> /ping, /hora, /eco
  - bot/handlers/boletin.py     -> /boletin, /boletin_add/rm/list/test/check + "go" manual (1ra)
  - bot/jobs/scheduler.py       -> polling cada 600s (demo)
  - bot/jobs/boletin_scheduler.py -> (desactivado modo manual) ex 07:00/08:00

Requisitos:
  pip install -r requirements-bot.txt
  # .env con TELEGRAM_TOKEN (ver .env.example)

Ejecución:
  python -m bot.main
  # o
  python bot/main.py

Healthcheck (para Render / UptimeRobot):
  GET /health -> {"status":"ok"}
  GET /       -> {"status":"ok","bot":"telegram-modular","mode":"local|cloud"}
"""

import logging
import signal
import threading

import uvicorn
from fastapi import FastAPI
from telegram.ext import Application

from bot.config import MODO, PORT, TELEGRAM_TOKEN
from bot.handlers import register_handlers
from bot.jobs.boletin_scheduler import setup_boletin_jobs
from bot.jobs.scheduler import setup_jobs

# --- Logging ---

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
# Silenciar librerías ruidosas
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- FastAPI health server ---

health_app = FastAPI(title="Telegram Bot Health")


@health_app.get("/health")
async def health():
    """Endpoint para Render healthCheckPath y UptimeRobot."""
    return {"status": "ok"}


@health_app.get("/")
async def root():
    """Info básica del bot."""
    return {"status": "ok", "bot": "telegram-modular", "mode": MODO}


def start_health_server() -> threading.Thread:
    """Lanza uvicorn en thread daemon en puerto PORT."""

    def _run() -> None:
        logger.info("[health] Iniciando FastAPI en 0.0.0.0:%d (/health)", PORT)
        # log_level warning para no spamear cada ping de UptimeRobot
        uvicorn.run(health_app, host="0.0.0.0", port=PORT, log_level="warning")

    thread = threading.Thread(target=_run, name="health-server", daemon=True)
    thread.start()
    return thread


def build_application() -> Application:
    """Construye Application de PTB, registra handlers y jobs."""
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    register_handlers(app)
    logger.info("[bot] Handlers registrados (start, scraper, utilidades, boletin)")

    setup_jobs(app)
    logger.info("[bot] Jobs demo configurados")
    # Modo manual "go" — jobs programados desactivados (activar si querés 07:00/08:00):
    # setup_boletin_jobs(app)
    # logger.info("[bot] Jobs boletín 07:00/08:00 configurados")
    logger.info("[bot] Boletín modo manual 'go' — sin jobs programados")

    return app


def main() -> None:
    """Entrypoint principal."""
    logger.info("[bot] Iniciando bot modular — MODO=%s PORT=%d", MODO, PORT)

    # 1) Health server en thread separado (no bloquea polling)
    start_health_server()

    # 2) Application PTB
    application = build_application()

    # 3) Manejo de señales (PTB ya maneja SIGINT/SIGTERM en run_polling,
    #    pero logueamos para visibilidad)
    def _signal_handler(signum, _frame):
        logger.info("[bot] Señal recibida %s, cerrando...", signal.Signals(signum).name)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except ValueError:
            # En thread no-main signal.signal falla; ignorar
            pass

    # 4) Polling bloqueante (hasta Ctrl+C / SIGTERM en Render)
    logger.info("[bot] Iniciando polling...")
    application.run_polling(
        allowed_updates=None,  # todos
        drop_pending_updates=False,  # changed from True: preserve pending updates (e.g. first "go") across restarts
    )
    logger.info("[bot] Polling detenido. Bye!")


if __name__ == "__main__":
    main()
