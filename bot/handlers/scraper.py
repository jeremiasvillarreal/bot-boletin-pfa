"""
bot.handlers.scraper — Comandos /watch y /scrape_demo.

- /watch <url>: guarda URLs en memoria (dict por chat_id) para futuro polling.
- /scrape_demo: ejecuta scraper/ejemplo_publico en vivo y responde con resultado.
- Placeholder /precio: ejemplo de cómo agregar futuros bots.

Nota: almacenamiento en memoria (se pierde al reiniciar). Para persistencia usar DB/sheets.
"""

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)

# Memoria volátil: chat_id -> list[url]
WATCHED_URLS: dict[int, list[str]] = {}


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /watch <url> — guarda URL para monitoreo."""
    chat_id = update.effective_chat.id if update.effective_chat else 0

    if not context.args:
        await update.message.reply_text(
            "📌 Uso: /watch <url>\n"
            "Ej: /watch https://quotes.toscrape.com/\n"
            f"Monitoreadas en este chat: {len(WATCHED_URLS.get(chat_id, []))}"
        )
        return

    url = context.args[0].strip()

    # Validación mínima
    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_text(
            "❌ URL inválida. Debe empezar con http:// o https://\n"
            f"Recibido: {url!r}"
        )
        return

    urls = WATCHED_URLS.setdefault(chat_id, [])
    if url in urls:
        await update.message.reply_text(f"⚠️ Ya estás monitoreando:\n{url}")
        return

    urls.append(url)
    logger.info("[/watch] chat_id=%s agregó url=%s total=%d", chat_id, url, len(urls))

    await update.message.reply_text(
        f"✅ URL agregada para monitoreo:\n{url}\n"
        f"Total en este chat: {len(urls)}\n"
        "ℹ️ Almacenado en memoria (se pierde al reiniciar). "
        "El JobQueue revisa cambios cada 10 min (ver bot/jobs/scheduler.py)."
    )


async def scrape_demo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /scrape_demo — ejecuta scraper demo y responde."""
    await update.message.reply_text("🔍 Ejecutando demo scraping... (quotes.toscrape.com + API)")

    try:
        # Import lazy para no romper carga del bot si faltan deps opcionales
        from scraper.ejemplo_publico import scrape_api, scrape_quotes
    except ImportError as exc:
        logger.exception("Import scraper.ejemplo_publico falló")
        await update.message.reply_text(f"❌ No se pudo importar scraper: {exc}")
        return

    # 1) Quotes via Playwright + BeautifulSoup
    try:
        quotes = await scrape_quotes()
        if quotes:
            lines = [f'• "{q["text"][:90]}" — {q["author"]}' for q in quotes[:3]]
            msg = f"✅ *Quotes* encontradas: {len(quotes)}\n" + "\n".join(lines)
            if len(quotes) > 3:
                msg += f"\n... y {len(quotes) - 3} más"
        else:
            msg = "⚠️ No se encontraron quotes."
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as exc:
        logger.exception("scrape_quotes falló")
        await update.message.reply_text(f"❌ Error en scrape_quotes: {exc}")

    # 2) API via httpx
    try:
        api_data = await scrape_api()
        # Truncar para Telegram (4096 chars)
        preview = str(api_data)[:1500]
        await update.message.reply_text(f"🌐 *API demo:*\n```\n{preview}\n```", parse_mode="Markdown")
    except Exception as exc:
        logger.exception("scrape_api falló")
        await update.message.reply_text(f"❌ Error en scrape_api: {exc}")


# --- Placeholder para futuros bots ---
# Ejemplo: /precio <url> <selector>
# async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     await update.message.reply_text("🚧 /precio en construcción. Copiá este patrón para tu próximo scraper.")


def register_scraper_handlers(application: Application) -> None:
    """Registra handlers de scraping."""
    application.add_handler(CommandHandler("watch", watch))
    application.add_handler(CommandHandler("scrape_demo", scrape_demo))
    # Placeholder: descomentá cuando implementes /precio
    # application.add_handler(CommandHandler("precio", precio))
