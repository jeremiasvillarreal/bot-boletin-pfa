"""
bot.main — Entrypoint del Bot Telegram modular 24/7 con watchdog.

Arquitectura:
  - Main thread: FastAPI /health (uvicorn.run) — keep-alive para Render + UptimeRobot
  - Thread daemon: Telegram polling con auto-restart (watchdog)
  - Si el polling muere (Render sleep, network blip, exception) → se reconstruye
    la Application y se relanza automáticamente después de un cooldown.

Flujo:
  1. Carga config (TELEGRAM_TOKEN, PORT, etc.) con validación
  2. Lanza health server en main thread (bloquea aquí)
  3. Polling corre en thread watchdog con restart automático

Healthcheck (para Render / UptimeRobot):
  GET /health -> 200 si OK, 503 si polling caído
"""

import logging
import signal
import sys
import threading
import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
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
# Silenciar librerías ruidosas
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- FastAPI health server ---

health_app = FastAPI(title="Telegram Bot Health")

# Estado del polling:
#   None  = startup (aún no arrancó)
#   True  = polling vivo y funcionando
#   False = polling murió tras haber estado vivo → Render debe reiniciar
_polling_alive: bool | None = None
_polling_restarts = 0


@health_app.get("/health")
async def health():
    """Health endpoint para Render healthCheckPath y UptimeRobot.

    Retorna 200 durante startup y cuando todo OK.
    Retorna 503 solo si el polling estaba vivo y después murió
    (para que Render reinicie el servicio).
    """
    if _polling_alive is False and _polling_restarts > 0:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "polling": "down",
                "restarts": _polling_restarts,
            },
        )
    status = "starting" if _polling_alive is None else "ok"
    return {"status": status, "restarts": _polling_restarts}


@health_app.get("/")
async def root():
    """Info básica del bot."""
    return {
        "status": "ok",
        "bot": "telegram-modular",
        "mode": MODO,
        "polling": "starting" if _polling_alive is None else ("alive" if _polling_alive else "down"),
        "restarts": _polling_restarts,
    }


def build_application() -> Application:
    """Construye Application de PTB, registra handlers y jobs."""
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    register_handlers(app)
    logger.info("[bot] Handlers registrados")

    setup_jobs(app)
    logger.info("[bot] Jobs configurados")

    return app


# --- Polling watchdog ---

POLL_RESTART_DELAY = 30       # segundos antes de reconstruir tras crash
POLL_COOLDOWN_SUCCESS = 10    # segundos si terminó sin error (parada limpia)
POLL_MAX_DELAY = 300          # tope máximo de espera (5 min)


def _polling_watchdog() -> None:
    """Thread watchdog que mantiene el polling vivo.

    Loop infinito: si run_polling() termina (exception o return),
    espera cooldown → rebuild Application → relanza.
    """
    global _polling_alive, _polling_restarts

    delay = POLL_RESTART_DELAY

    while True:
        _polling_alive = True
        application = None

        try:
            logger.info("[polling] Construyendo Application...")
            application = build_application()

            logger.info("[polling] Iniciando run_polling (poll_interval=2s, timeouts=15s)...")
            application.run_polling(
                allowed_updates=None,
                drop_pending_updates=False,
                poll_interval=2.0,
                read_timeout=15,
                connect_timeout=15,
            )
            # Limpio: run_polling() retornó (e.g. SIGTERM)
            logger.warning("[polling] run_polling terminó limpiamente. Reiniciando...")
            delay = POLL_COOLDOWN_SUCCESS

        except Exception:
            logger.exception("[polling] Excepción en run_polling. Reiniciando...")
            delay = POLL_RESTART_DELAY

        finally:
            _polling_alive = False

        _polling_restarts += 1
        wait = min(delay, POLL_MAX_DELAY)
        logger.info("[polling] Reinicio #%d en %ds...", _polling_restarts, wait)
        time.sleep(wait)
        delay = min(delay * 2, POLL_MAX_DELAY)


def main() -> None:
    """Entrypoint principal.

    Main thread = uvicorn /health (bloquea).
    Thread daemon = polling watchdog (auto-restart).
    Si el main thread muere → proceso entero muere (daemon threads se cortan).
    """
    logger.info("[bot] Iniciando bot — MODO=%s PORT=%d", MODO, PORT)

    # 1) Polling watchdog en thread daemon
    #    daemon=True: si el main thread muere, el proceso entero sale limpio.
    polling_thread = threading.Thread(
        target=_polling_watchdog,
        name="polling-watchdog",
        daemon=True,
    )
    polling_thread.start()
    logger.info("[bot] Polling watchdog lanzado (daemon)")

    # 2) Health server en main thread (bloquea)
    logger.info("[health] Iniciando uvicorn en 0.0.0.0:%d", PORT)
    uvicorn.run(health_app, host="0.0.0.0", port=PORT, log_level="warning")

    # Si uvicorn.return (nunca debería en Render), salir forzado
    logger.critical("[bot] uvicorn terminó. Saliendo.")
    sys.exit(1)


if __name__ == "__main__":
    main()
