"""
bot.jobs.scheduler — JobQueue periódico para scraping demo.

Registra un job run_repeating cada 600s (10 min) que:
  - Ejecuta scraper demo (scrape_api / scrape_quotes)
  - Detecta cambios simples vs última ejecución (hash del resultado)
  - Loguea y, si hay cambios, prepara notificación (extender para enviar a chats).

Uso: setup_jobs(application) se llama desde bot/main.py después de register_handlers.
"""

import hashlib
import json
import logging

from telegram.ext import Application, ContextTypes

logger = logging.getLogger(__name__)

# Estado en memoria para detección de cambios (se pierde al reiniciar)
_last_hash: str | None = None
_last_data_preview: str = ""


async def _poll_demo_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback ejecutado cada 600s por JobQueue.

    Hace scraping demo y loguea si hubo cambios.
    Para notificar a usuarios, iterar sobre WATCHED_URLS o guardar chat_ids.
    """
    global _last_hash, _last_data_preview

    logger.info("[scheduler] Ejecutando poll cada 600s — scraping demo...")

    try:
        from scraper.ejemplo_publico import scrape_api
    except ImportError as exc:
        logger.warning("[scheduler] No se pudo importar scrape_api: %s", exc)
        return

    try:
        data = await scrape_api()
        # Normalizar a JSON estable para hash
        payload = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
        current_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        preview = payload[:300]

        if _last_hash is None:
            logger.info("[scheduler] Primera ejecución, hash=%s preview=%s", current_hash[:8], preview[:120])
            _last_hash = current_hash
            _last_data_preview = preview
            return

        if current_hash != _last_hash:
            logger.info(
                "[scheduler] ¡Cambio detectado! prev=%s new=%s preview=%s",
                _last_hash[:8],
                current_hash[:8],
                preview[:200],
            )
            # Ejemplo notificación: enviar a todos los chats con /watch
            # Descomentar si querés notificar:
            # from bot.handlers.scraper import WATCHED_URLS
            # for chat_id in list(WATCHED_URLS.keys()):
            #     try:
            #         await context.bot.send_message(
            #             chat_id=chat_id,
            #             text=f"🔔 Cambio detectado en scraping demo!\n```\n{preview[:1000]}\n```",
            #             parse_mode="Markdown",
            #         )
            #     except Exception as e:
            #         logger.warning("[scheduler] No se pudo notificar chat %s: %s", chat_id, e)

            _last_hash = current_hash
            _last_data_preview = preview
        else:
            logger.debug("[scheduler] Sin cambios (hash %s)", current_hash[:8])

    except Exception as exc:
        logger.exception("[scheduler] Error en poll_demo_job: %s", exc)


def setup_jobs(application: Application) -> None:
    """Registra jobs periódicos en application.job_queue.

    Args:
        application: Instancia de telegram.ext.Application ya construida.
    """
    if application.job_queue is None:
        logger.warning("[scheduler] JobQueue no disponible (¿falta python-telegram-bot[job-queue]?). Skip.")
        return

    # run_repeating cada 600s, primera ejecución a los 10s del arranque
    application.job_queue.run_repeating(
        _poll_demo_job,
        interval=600,
        first=10,
        name="scrape_demo_poll",
    )
    logger.info("[scheduler] Job 'scrape_demo_poll' registrado cada 600s (first=10s)")
