"""
bot.main — Entrypoint del Bot Telegram modular 24/7.

Arquitectura:
  - Main thread: Telegram polling (run_polling) con restart loop
  - Daemon thread: FastAPI /health (uvicorn) para Render + UptimeRobot
  - Daemon thread: Self-ping cada 10min para evitar Render Free spin-down
  - Daemon thread: Watchdog — si no hay updates en 20min, fuerza restart

Healthcheck:
  GET /health -> 200 OK (solo cuando bot está listo)
  GET /health -> 503 (durante startup, antes de polling)
"""

import gc
import logging
import os
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

_startup_ready = threading.Event()  # set cuando el bot está listo para recibir

# --- Watchdog: tracking de última actividad ---

_last_activity = time.monotonic()  # se actualiza con cada update de Telegram
_activity_lock = threading.Lock()

def touch_activity() -> None:
    """Llamar cuando llega un update de Telegram."""
    global _last_activity
    with _activity_lock:
        _last_activity = time.monotonic()

def get_last_activity_age() -> float:
    """Segundos desde la última actividad."""
    with _activity_lock:
        return time.monotonic() - _last_activity

# --- FastAPI health server ---

health_app = FastAPI(title="Telegram Bot Health")


@health_app.get("/health")
async def health(response: Response):
    """Endpoint para Render healthCheckPath y UptimeRobot.
    Retorna 503 durante startup para que Render no mate el proceso antes de tiempo.
    """
    if not _startup_ready.is_set():
        response.status_code = 503
        return {"status": "starting"}
    return {"status": "ok"}


@health_app.get("/")
async def root():
    """Info básica del bot."""
    ready = _startup_ready.is_set()
    age = get_last_activity_age()
    return {
        "status": "ok" if ready else "starting",
        "bot": "telegram-modular",
        "mode": MODO,
        "last_activity_sec_ago": int(age),
    }


def start_health_server() -> threading.Thread:
    """Lanza uvicorn en thread daemon en puerto PORT."""
    def _run() -> None:
        logger.info("[health] FastAPI en 0.0.0.0:%d (/health)", PORT)
        uvicorn.run(health_app, host="0.0.0.0", port=PORT, log_level="warning")
    thread = threading.Thread(target=_run, name="health-server", daemon=True)
    thread.start()
    return thread


# --- Self-ping para mantener Render Free vivo ---

_SELF_PING_INTERVAL = 600  # 10 minutos (Render Free spindown a los 15 min)


def _self_ping_loop() -> None:
    """Daemon thread que hace GET /health cada 10 min para evitar spin-down de Render Free."""
    url = f"http://localhost:{PORT}/health"
    logger.info("[self-ping] Iniciado — ping cada %ds a %s", _SELF_PING_INTERVAL, url)
    # Esperar a que el health server esté listo (máx 30s)
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
    """Lanza self-ping en thread daemon."""
    thread = threading.Thread(target=_self_ping_loop, name="self-ping", daemon=True)
    thread.start()
    return thread


# --- Watchdog: fuerza restart si el bot está muerto ---

_WATCHDOG_STALE_SECONDS = 20 * 60  # 20 minutos sin updates → reiniciar


def _watchdog_loop() -> None:
    """Daemon thread que verifica si el bot sigue vivo.

    Si pasan 20 minutos sin ningún update de Telegram, significa que:
    - Render durmió el servicio y la conexión de polling se rompió
    - El Updater está colgado en una conexión muerta
    - Hay un bug en el event loop

    En esos casos, fuerza restart con os._exit() para que Render reinicie el proceso.
    """
    logger.info("[watchdog] Iniciado — timeout de %ds sin actividad", _WATCHDOG_STALE_SECONDS)

    # Esperar a que el bot arranque
    while not _startup_ready.is_set():
        time.sleep(2)

    while True:
        time.sleep(120)  # check cada 2 minutos

        age = get_last_activity_age()

        # Solo alertar si el bot lleva mucho tiempo activo (>5min) sin updates
        # para no disparar durante arranque o si no hay tráfico
        uptime = (datetime.now(timezone.utc) - StartTime).total_seconds()
        if uptime < 300:
            continue  # primeros 5min, no alertar

        if age > _WATCHDOG_STALE_SECONDS:
            logger.critical(
                "[watchdog] BOT MUERTO — %ds sin actividad. "
                "Forzando restart para reconectar a Telegram. "
                "(posible Render sleep/wake o conexión colgada)",
                int(age),
            )
            # os._exit fuerza kill inmediato — Render reinicia el proceso
            os._exit(1)
        elif age > 600:
            logger.warning(
                "[watchdog] Alerta: %ds sin actividad (timeout a %ds)",
                int(age), _WATCHDOG_STALE_SECONDS,
            )


def start_watchdog() -> threading.Thread:
    """Lanza watchdog en thread daemon."""
    thread = threading.Thread(target=_watchdog_loop, name="watchdog", daemon=True)
    thread.start()
    return thread


# --- Activity tracker: se registra como handler de todos los updates ---

async def _activity_tracker(update, context) -> None:
    """Handler que se ejecuta con cada update para marcar actividad."""
    touch_activity()


def _setup_activity_tracking(application: Application) -> None:
    """Registra un handler de prioridad máxima que trackea actividad."""
    from telegram.ext import MessageHandler, filters
    # Group -1 = se ejecuta ANTES que todos los otros handlers
    application.add_handler(
        MessageHandler(filters.ALL, _activity_tracker), group=-1
    )


# --- Build & cleanup ---

def build_application() -> Application:
    """Construye Application de PTB, registra handlers y jobs."""
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .read_timeout(30)
        .connect_timeout(15)
        .build()
    )

    # Activity tracker (group -1, se ejecuta primero)
    _setup_activity_tracking(app)

    register_handlers(app)
    logger.info("[bot] Handlers registrados")

    setup_jobs(app)
    setup_boletin_jobs(app)
    logger.info("[bot] Jobs configurados (scrape_demo + boletin 07/08)")

    return app


def _cleanup_application(app: Application) -> None:
    """Limpia recursos de una Application anterior para evitar memory leaks."""
    try:
        if app.job_queue:
            app.job_queue.stop()
    except Exception:
        pass
    try:
        loop = app.bot_data.get("_loop")
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
    except Exception:
        pass
    gc.collect()


def main() -> None:
    """Entrypoint principal.

    Main thread  → polling Telegram (run_polling + restart loop)
    Daemon thread → health server FastAPI
    Daemon thread → self-ping (keep-alive Render Free)
    Daemon thread → watchdog (detecta bot muerto, fuerza restart)
    """
    logger.info("[bot] Iniciando — MODO=%s PORT=%d", MODO, PORT)

    # 1) Health server en thread separado (no bloquea polling)
    start_health_server()

    # 2) Self-ping para mantener vivo en Render Free
    start_self_ping()

    # 3) Watchdog para detectar bot muerto
    start_watchdog()

    # 4) Check rápido de Playwright (solo log)
    try:
        from scraper.base import PLAYWRIGHT_AVAILABLE
        if PLAYWRIGHT_AVAILABLE:
            logger.info("[bot] Playwright disponible (fallback scraping habilitado)")
        else:
            logger.info("[bot] Playwright no instalado — scraping usa solo httpx (OK en nube)")
    except Exception:
        pass

    # 5) Manejo de señales
    def _signal_handler(signum, _frame):
        logger.info("[bot] Señal recibida %s, cerrando...", signal.Signals(signum).name)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except ValueError:
            pass

    # 6) Polling con restart automático
    #    Si run_polling() muere (Render sleep, network, exception),
    #    reconstruye Application y relanza.
    restart_count = 0
    current_app = None
    while True:
        restart_count += 1
        try:
            # Limpiar app anterior si existe
            if current_app is not None:
                _cleanup_application(current_app)
                current_app = None

            application = build_application()
            current_app = application

            logger.info("[bot] Iniciando polling... (restart #%d)", restart_count)

            # Marcar como listo DESPUÉS de build pero ANTES de polling
            _startup_ready.set()

            application.run_polling(
                allowed_updates=None,
                drop_pending_updates=True,
            )
            # Limpio: run_polling retornó
            logger.warning("[bot] Polling terminó limpiamente. Restart en 10s...")
        except Exception:
            logger.exception("[bot] Polling crasheado. Restart en 30s...")
            time.sleep(30)
            continue
        time.sleep(10)


if __name__ == "__main__":
    main()
