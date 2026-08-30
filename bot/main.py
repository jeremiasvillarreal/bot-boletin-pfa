"""
bot.main — Entrypoint del Bot Telegram modular 24/7.

Arquitectura:
  - Main thread: Telegram polling (run_polling) con restart loop
  - Daemon thread: FastAPI /health (uvicorn) para Render + UptimeRobot
  - Si run_polling() muere → rebuild Application → retry con backoff

Healthcheck:
  GET /health -> SIEMPRE 200 (nunca 503, para que Render no mate el servicio)
"""

import logging
import signal
import sys
import threading
import time

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
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- FastAPI health server ---

health_app = FastAPI(title="Telegram Bot Health")

_polling_restarts = 0


@health_app.get("/health")
async def health():
    """Health endpoint para Render y UptimeRobot.

    SIEMPRE devuelve 200 para que Render no reinicie el servicio.
    La info de estado va en el body.
    """
    return {"status": "ok", "restarts": _polling_restarts}


@health_app.get("/")
async def root():
    return {"status": "ok", "bot": "telegram-modular", "mode": MODO, "restarts": _polling_restarts}


def start_health_server() -> None:
    """Health server en daemon thread."""
    def _run():
        logger.info("[health] FastAPI en 0.0.0.0:%d", PORT)
        uvicorn.run(health_app, host="0.0.0.0", port=PORT, log_level="warning")
    t = threading.Thread(target=_run, name="health-server", daemon=True)
    t.start()


def build_application() -> Application:
    """Construye Application de PTB con handlers y jobs."""
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    register_handlers(app)
    setup_jobs(app)
    logger.info("[bot] Application OK")
    return app


def main() -> None:
    """Entrypoint.

    Main thread  → polling Telegram (run_polling + restart loop)
    Daemon thread → health server FastAPI
    """
    global _polling_restarts

    logger.info("[bot] Iniciando — MODO=%s PORT=%d", MODO, PORT)

    # 1) Health server en daemon thread
    start_health_server()

    # 2) Señales — solo main thread
    def _on_signal(signum, _frame):
        logger.info("[bot] Señal %s, saliendo...", signal.Signals(signum).name)
        sys.exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass

    # 3) Polling loop con restart
    delay = 30

    while True:
        try:
            logger.info("[bot] Build Application...")
            application = build_application()

            logger.info("[bot] run_polling()...")
            application.run_polling(
                allowed_updates=None,
                drop_pending_updates=False,
                poll_interval=2.0,
                read_timeout=15,
                connect_timeout=15,
            )
            # Limpio
            logger.warning("[bot] Polling terminó limpiamente. Restart en 10s...")
            delay = 10

        except Exception:
            logger.exception("[bot] Polling crasheado. Restart en %ds...", delay)
            delay = min(delay * 2, 300)

        finally:
            _polling_restarts += 1

        time.sleep(delay)
        delay = 30


if __name__ == "__main__":
    main()
