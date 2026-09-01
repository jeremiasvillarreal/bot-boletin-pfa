"""
bot.main — Entrypoint del Bot Telegram modular 24/7 (webhook mode).

Arquitectura:
  - FastAPI unificado: /health + /webhook (recibe updates de Telegram)
  - JobQueue corre via application.start() (async, en el event loop)
  - Render nunca duerme porque Telegram manda traffic a /webhook

Healthcheck:
  GET /health -> 200 OK

Webhook:
  POST /webhook -> procesa updates de Telegram
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
import uvicorn
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application

from bot.config import MODO, PORT, TELEGRAM_TOKEN
from bot.handlers import register_handlers
from bot.jobs.boletin_scheduler import setup_boletin_jobs
from bot.jobs.scheduler import setup_jobs

StartTime = datetime.now(timezone.utc)
SELF_PING_INTERVAL = 600  # 10 minutos (Render Free duerme a los 15)


async def _self_ping_loop():
    """Mantiene vivo el servicio en Render Free haciendo ping a /health."""
    # Esperar 30s antes del primer ping para que el servidor esté listo
    await asyncio.sleep(30)
    ping_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    if not ping_url:
        ping_url = os.getenv("SELF_PING_URL", "").strip()
    if not ping_url:
        # Si no hay URL externa, intentar localhost (desarrollo local)
        ping_url = f"http://127.0.0.1:{PORT}"
    ping_url = ping_url.rstrip("/") + "/health"
    logger.info("[self-ping] Monitoreando cada %ds -> %s", SELF_PING_INTERVAL, ping_url)
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            await asyncio.sleep(SELF_PING_INTERVAL)
            try:
                resp = await client.get(ping_url)
                logger.info("[self-ping] %s -> %d", ping_url, resp.status_code)
            except Exception as exc:
                logger.warning("[self-ping] Error: %s", exc)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Application (se construye una vez) ---

_application: Application | None = None


def build_application() -> Application:
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .read_timeout(30)
        .connect_timeout(15)
        .build()
    )
    register_handlers(app)
    setup_jobs(app)
    setup_boletin_jobs(app)
    logger.info("[bot] Application construida (handlers + jobs)")
    return app


# --- FastAPI ---

app = FastAPI(title="Telegram Bot")


@app.get("/health")
async def health():
    uptime = (datetime.now(timezone.utc) - StartTime).total_seconds()
    return {"status": "ok", "uptime_s": int(uptime), "mode": MODO}


@app.get("/")
async def root():
    uptime = (datetime.now(timezone.utc) - StartTime).total_seconds()
    return {"status": "ok", "bot": "telegram-modular", "mode": MODO, "uptime_s": int(uptime)}


@app.post("/webhook")
async def webhook(request: Request):
    """Recibe updates de Telegram y los procesa."""
    try:
        data = await request.json()
        update = Update.de_json(data, _application.bot)
        await _application.process_update(update)
    except Exception:
        logger.exception("[webhook] Error procesando update")
    return {"ok": True}


# --- Startup ---

@app.on_event("startup")
async def on_startup():
    global _application
    logger.info("=" * 50)
    logger.info("[bot] INICIANDO (webhook mode) — MODO=%s PORT=%d", MODO, PORT)
    logger.info("=" * 50)

    _application = build_application()

    # Inicializar y arrancar (arranca el JobQueue)
    await _application.initialize()
    await _application.start()

    # Construir URL del webhook
    # Render expone RENDER_EXTERNAL_URL automaticamente
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    if render_url:
        webhook_url = render_url.rstrip("/")
    else:
        # Fallback para local: requires WEBHOOK_URL env or localhost
        webhook_url = os.getenv("WEBHOOK_URL", "").strip()

    if not webhook_url:
        logger.error(
            "[bot] No hay WEBHOOK_URL ni RENDER_EXTERNAL_URL. "
            "Define WEBHOOK_URL en .env (ej: https://tu-app.onrender.com) "
            "o usa Render que lo inyecta solo."
        )
        # En local sin webhook URL, intentar modo polling como fallback
        logger.info("[bot] Fallback a polling mode (solo para testing local)")
        _application.drop_pending_updates = True
        asyncio.create_task(_run_polling_fallback())
        return

    # Limpiar updates pendientes antes de setear webhook
    await _application.bot.delete_webhook(drop_pending_updates=True)

    # Setear webhook con Telegram
    full_webhook_url = f"{webhook_url}/webhook"
    await _application.bot.set_webhook(
        url=full_webhook_url,
        allowed_updates=None,
    )
    logger.info("[bot] Webhook seteado: %s", full_webhook_url)
    logger.info("[bot] Health check: %s/health", webhook_url)
    logger.info("[bot] Bot listo — Telegram manda updates a /webhook")

    # Self-ping para evitar que Render Free duerma
    asyncio.create_task(_self_ping_loop())


@app.on_event("shutdown")
async def on_shutdown():
    if _application:
        await _application.stop()
        await _application.shutdown()
        logger.info("[bot] Application detenida")


async def _run_polling_fallback():
    """Fallback polling para testing local sin webhook URL."""
    if _application:
        logger.info("[bot] Polling fallback iniciado")
        await _application.run_polling(
            allowed_updates=None,
            drop_pending_updates=True,
        )


def main():
    """Entrypoint: uvicorn sirve FastAPI (health + webhook) en el puerto de Render."""
    logger.info("[bot] Levantando uvicorn en 0.0.0.0:%d", PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
