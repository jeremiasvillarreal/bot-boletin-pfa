"""
bot.main — Entrypoint del Bot Telegram modular 24/7.

Arquitectura:
  - Main thread: Telegram polling (run_polling) con restart loop
  - Daemon thread: FastAPI /health (uvicorn) para Render + UptimeRobot
  - JobQueue: keepalive cada 5min (bot.get_me()) para mantener conexión viva

Healthcheck:
  GET /health -> 200 OK (solo cuando bot está listo)
  GET /health -> 503 (durante startup, antes de polling)
"""

import gc
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone

import httpx
import uvicorn
from fastapi import FastAPI, Response
from telegram.ext import Application

from bot.config import MODO, PORT, TELEGRAM_TOKEN
from bot.handlers import register_handlers
from bot.jobs.boletin_scheduler import setup_boletin_jobs
from bot.jobs.scheduler import setup_jobs

# Timestamp de inicio para /sysinfo
StartTime = datetime.now(timezone.utc)

# --- Logging ---

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Startup readiness flag ---

_startup_ready = threading.Event()

# --- FastAPI health server ---

health_app = FastAPI(title="Telegram Bot Health")


@health_app.get("/health")
async def health(response: Response):
    if not _startup_ready.is_set():
        response.status_code = 503
        return {"status": "starting"}
    return {"status": "ok"}


@health_app.get("/")
async def root():
    return {"status": "ok" if _startup_ready.is_set() else "starting",
            "bot": "telegram-modular", "mode": MODO}


def start_health_server() -> threading.Thread:
    def _run() -> None:
        logger.info("[health] FastAPI en 0.0.0.0:%d (/health)", PORT)
        uvicorn.run(health_app, host="0.0.0.0", port=PORT, log_level="warning")
    thread = threading.Thread(target=_run, name="health-server", daemon=True)
    thread.start()
    return thread


# --- Self-ping para mantener Render Free vivo ---

_SELF_PING_INTERVAL = 600  # 10 min


def _self_ping_loop() -> None:
    url = f"http://localhost:{PORT}/health"
    logger.info("[self-ping] Iniciado — ping cada %ds", _SELF_PING_INTERVAL)
    for _ in range(30):
        try:
            resp = httpx.get(url, timeout=5.0)
            if resp.status_code in (200, 503):
                break
        except Exception:
            pass
        time.sleep(1)
    while True:
        time.sleep(_SELF_PING_INTERVAL)
        try:
            resp = httpx.get(url, timeout=10.0)
            logger.info("[self-ping] OK — status=%d", resp.status_code)
        except Exception as e:
            logger.warning("[self-ping] Falló: %s", e)


def start_self_ping() -> threading.Thread:
    thread = threading.Thread(target=_self_ping_loop, name="self-ping", daemon=True)
    thread.start()
    return thread


# --- Keepalive de Telegram (via JobQueue) ---

_KEEPALIVE_INTERVAL = 300  # 5 minutos


async def _keepalive_job(context) -> None:
    """Job que hace getMe() cada 5min para mantener la conexión con Telegram viva.

    Si getMe() falla → la excepción llega al Updater → reconecta automáticamente.
    Si llega acá, la conexión está OK.
    """
    try:
        bot = context.bot
        me = await bot.get_me()
        logger.debug("[keepalive] Telegram OK — @%s", me.username)
    except Exception as e:
        logger.warning("[keepalive] getMe() falló (conexión rota?): %s", e)
        # No hacemos nada más — run_polling detectará el error y restarteará


# --- Build ---

def build_application() -> Application:
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .read_timeout(30)
        .connect_timeout(15)
        .build()
    )

    register_handlers(app)
    logger.info("[bot] Handlers registrados")

    setup_jobs(app)
    setup_boletin_jobs(app)

    # Keepalive: getMe() cada 5min para mantener conexión con Telegram
    if app.job_queue:
        app.job_queue.run_repeating(
            _keepalive_job,
            interval=_KEEPALIVE_INTERVAL,
            first=60,  # primer check a los 60s del arranque
            name="telegram_keepalive",
        )
        logger.info("[bot] Keepalive registrado cada %ds", _KEEPALIVE_INTERVAL)

    logger.info("[bot] Jobs configurados (keepalive + scrape_demo + boletin 07/08)")
    return app


def _cleanup_application(app: Application) -> None:
    try:
        if app.job_queue:
            app.job_queue.stop()
    except Exception:
        pass
    gc.collect()


def main() -> None:
    logger.info("[bot] Iniciando — MODO=%s PORT=%d", MODO, PORT)

    # 1) Health server
    start_health_server()

    # 2) Self-ping (mantiene Render Free vivo)
    start_self_ping()

    # 3) Check Playwright
    try:
        from scraper.base import PLAYWRIGHT_AVAILABLE
        logger.info("[bot] Playwright: %s", "OK" if PLAYWRIGHT_AVAILABLE else "no instalado (solo httpx)")
    except Exception:
        pass

    # 4) Señales
    def _signal_handler(signum, _frame):
        logger.info("[bot] Señal recibida %s, cerrando...", signal.Signals(signum).name)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except ValueError:
            pass

    # 5) Polling con restart automático
    restart_count = 0
    current_app = None
    while True:
        restart_count += 1
        try:
            if current_app is not None:
                _cleanup_application(current_app)
                current_app = None

            application = build_application()
            current_app = application

            logger.info("[bot] Iniciando polling... (restart #%d)", restart_count)
            _startup_ready.set()

            application.run_polling(
                allowed_updates=None,
                drop_pending_updates=True,
            )
            logger.warning("[bot] Polling terminó limpiamente. Restart en 10s...")
        except Exception:
            logger.exception("[bot] Polling crasheado. Restart en 30s...")
            time.sleep(30)
            continue
        time.sleep(10)


if __name__ == "__main__":
    main()
