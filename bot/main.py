"""
bot.main — Entrypoint del Bot Telegram modular 24/7.

Arquitectura:
  - Main thread: Telegram polling (run_polling) con restart loop
  - Daemon thread: FastAPI /health (uvicorn) para Render + UptimeRobot

Healthcheck:
  GET /health -> 200 OK
"""

import logging
import signal
import sys
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
        logger.info("[health] FastAPI en 0.0.0.0:%d (/health)", PORT)
        uvicorn.run(health_app, host="0.0.0.0", port=PORT, log_level="warning")
    thread = threading.Thread(target=_run, name="health-server", daemon=True)
    thread.start()
    return thread


def build_application() -> Application:
    """Construye Application de PTB, registra handlers y jobs."""
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    register_handlers(app)
    logger.info("[bot] Handlers registrados")

    setup_jobs(app)
    logger.info("[bot] Jobs configurados")

    return app


def main() -> None:
    """Entrypoint principal.

    Main thread  → polling Telegram (run_polling + restart loop)
    Daemon thread → health server FastAPI
    """
    logger.info("[bot] Iniciando — MODO=%s PORT=%d", MODO, PORT)

    # 1) Health server en thread separado (no bloquea polling)
    start_health_server()

    # 2) Manejo de señales
    def _signal_handler(signum, _frame):
        logger.info("[bot] Señal recibida %s, cerrando...", signal.Signals(signum).name)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except ValueError:
            pass

    # 3) Polling con restart automático
    #    Si run_polling() muere (Render sleep, network, exception),
    #    reconstruye Application y relanza.
    while True:
        try:
            application = build_application()
            logger.info("[bot] Iniciando polling...")
            application.run_polling(
                allowed_updates=None,
                drop_pending_updates=False,
            )
            # Limpio: run_polling retornó
            logger.warning("[bot] Polling terminó limpiamente. Restart en 10s...")
        except Exception:
            logger.exception("[bot] Polling crasheado. Restart en 30s...")
            import time
            time.sleep(30)
            continue
        import time
        time.sleep(10)


if __name__ == "__main__":
    main()
