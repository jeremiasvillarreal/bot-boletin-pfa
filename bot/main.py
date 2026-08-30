"""
bot.main — Entrypoint del Bot Telegram modular 24/7 con watchdog.

Arquitectura:
  - Main thread: FastAPI /health (uvicorn.run) — keep-alive para Render + UptimeRobot
  - Thread separado: Telegram polling con auto-restart (watchdog)
  - Si el polling muere (Render sleep, network blip, exception) → se reconstruye
    la Application y se relanza automáticamente después de un cooldown.

Flujo:
  1. Carga config (TELEGRAM_TOKEN, PORT, etc.) con validación
  2. Lanza health server en main thread (bloquea aquí)
  3. Polling corre en thread watchdog con restart automático

Requisitos:
  pip install -r requirements-bot.txt
  # .env con TELEGRAM_TOKEN (ver .env.example)

Healthcheck (para Render / UptimeRobot):
  GET /health -> {"status":"ok"}
  GET /       -> {"status":"ok","bot":"telegram-modular","mode":"local|cloud"}
"""

import logging
import signal
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
)
# Silenciar librerías ruidosas
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- FastAPI health server ---

health_app = FastAPI(title="Telegram Bot Health")

# Flag global para monitorear estado del polling desde health endpoint
# None = startup (aún no arrancó), True = vivo, False = muerto tras haber estado vivo
_polling_alive: bool | None = None
_polling_restarts = 0


@health_app.get("/health")
async def health():
    """Endpoint para Render healthCheckPath y UptimeRobot.

    Estados:
      - _polling_alive is None  → startup, aún no arrancó → 200
      - _polling_alive is True  → todo OK → 200
      - _polling_alive is False → polling murió → 503 (Render reinicia)
    """
    if _polling_alive is False and _polling_restarts > 0:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "polling": "down", "restarts": _polling_restarts},
        )
    status = "starting" if _polling_alive is None else "ok"
    return {"status": status, "polling": "alive" if _polling_alive else status, "restarts": _polling_restarts}


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


def start_health_server() -> None:
    """Lanza uvicorn en thread daemon en puerto PORT."""
    # Se ejecuta en el main thread (uvicorn.run bloquea)
    logger.info("[health] Iniciando FastAPI en 0.0.0.0:%d (/health)", PORT)
    uvicorn.run(health_app, host="0.0.0.0", port=PORT, log_level="warning")


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


# --- Polling watchdog ---

# Cooldowns para restart del polling
POLL_RESTART_DELAY = 30       # segundos antes de reconstruir tras crash
POLL_COOLDOWN_SUCCESS = 10    # segundos de espera si terminó sin error (parada limpia)
POLL_MAX_DELAY = 300          # tope máximo de espera entre reintentos (5 min)


def _polling_watchdog() -> None:
    """Thread watchdog que mantiene el polling vivo.

    Si run_polling() termina (por exception o return), espera un cooldown
    y reconstruye la Application para relanzar polling limpio.
    """
    global _polling_alive, _polling_restarts

    delay = POLL_RESTART_DELAY

    while True:
        _polling_alive = True
        application = None

        try:
            logger.info("[polling] Construyendo Application...")
            application = build_application()

            # Manejo de señales dentro del thread (PTB los necesita)
            def _signal_handler(signum, _frame):
                logger.info("[polling] Señal recibida %s", signal.Signals(signum).name)

            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    signal.signal(sig, _signal_handler)
                except ValueError:
                    pass

            logger.info("[polling] Iniciando run_polling...")
            application.run_polling(
                allowed_updates=None,
                drop_pending_updates=False,
                # Tuning de reconexión
                poll_interval=2.0,         # 2s entre polls (default: 0, lo pone PTB)
                read_timeout=15,           # timeout de lectura
                connect_timeout=15,        # timeout de conexión
                # No limitar reintentos internos — PTB maneja reconnect
            )
            # run_polling() terminó sin exception (parada limpia, e.g. SIGTERM)
            logger.warning("[polling] run_polling terminó limpiamente (return). Reiniciando...")
            delay = POLL_COOLDOWN_SUCCESS

        except Exception:
            logger.exception("[polling] Excepción en run_polling. Reiniciando...")
            delay = POLL_RESTART_DELAY

        finally:
            _polling_alive = False

        # Si la aplicación existía, intentar shutdown limpio
        if application:
            try:
                # Dar tiempo a PTB para cerrar conexiones
                pass
            except Exception:
                pass

        _polling_restarts += 1

        # Backoff exponencial con tope
        wait = min(delay, POLL_MAX_DELAY)
        logger.info(
            "[polling] Reinicio #%d en %ds (backoff=%ds)...",
            _polling_restarts, wait, delay,
        )
        time.sleep(wait)

        # Backoff progresivo: duplicar cada vez, hasta el tope
        delay = min(delay * 2, POLL_MAX_DELAY)


def main() -> None:
    """Entrypoint principal.

    Main thread → health server (uvicorn.run bloquea).
    Thread separado → polling watchdog (auto-restart).
    """
    logger.info("[bot] Iniciando bot modular — MODO=%s PORT=%d", MODO, PORT)

    # 1) Lanzar polling watchdog en thread NO-daemon (sobrevive al main)
    polling_thread = threading.Thread(
        target=_polling_watchdog,
        name="polling-watchdog",
        daemon=False,
    )
    polling_thread.start()
    logger.info("[bot] Polling watchdog lanzado en thread separado")

    # 2) Health server en main thread (bloquea aquí — Render necesita proceso vivo)
    start_health_server()

    # Si llegamos acá, uvicorn terminó (nunca debería pasar en Render)
    logger.critical("[bot] Health server terminó inesperadamente. Saliendo.")
    # Forzar salida — Render reiniciará el servicio
    import os
    os._exit(1)


if __name__ == "__main__":
    main()
