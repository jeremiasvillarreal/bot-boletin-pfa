"""
bot.handlers.start — Comandos /start y /help.

Mensaje introductorio menciona scraping + utilidades + hosting 24/7 gratis.
"""

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

INTRO_MSG = (
    "👋 ¡Hola! Soy tu *Bot Modular* 🤖\n"
    "\n"
    "¿Qué puedo hacer?\n"
    "🔍 *Scraping* — `/watch <url>` para monitorear una URL, `/scrape\\_demo` para demo en vivo "
    "con `scraper/ejemplo_publico.py` (quotes.toscrape.com + APIs públicas).\n"
    "🛠️ *Utilidades* — `/ping`, `/hora`, `/eco <texto>`.\n"
    "🚀 *24/7 Gratis* — corriendo en Render Free + UptimeRobot ping a `/health` cada 5 min, "
    "sin tarjeta, auto-deploy desde GitHub.\n"
    "\n"
    "Escribí /help para ver todos los comandos."
)

HELP_MSG = (
    "📖 *Comandos disponibles*\n"
    "\n"
    "*Generales*\n"
    "• /start — Mensaje de bienvenida\n"
    "• /help — Esta ayuda\n"
    "\n"
    "*Scraping* 🔍\n"
    "• /watch <url> — Guarda una URL en memoria para monitoreo (ej: `/watch https://quotes.toscrape.com/`)\n"
    "• /scrape\\_demo — Demo scraping Playwright + BeautifulSoup + httpx\n"
    "• /precio — _(placeholder)_ Próximamente: tracking de precios\n"
    "\n"
    "*Utilidades* 🛠️\n"
    "• /ping — Latencia del bot\n"
    "• /hora — Hora actual del servidor\n"
    "• /eco <texto> — Repite tu texto\n"
    "\n"
    "💡 *Tip:* Cada feature es un handler modular en `bot/handlers/`. "
    "Agregar un nuevo bot = nuevo archivo + 1 línea en `register_handlers`.\n"
    "\n"
    "❤️ Hosting 24/7 gratis vía `GET /health` (FastAPI + UptimeRobot)."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /start."""
    await update.message.reply_text(INTRO_MSG, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /help."""
    await update.message.reply_text(HELP_MSG, parse_mode="Markdown")


def register_start_handlers(application: Application) -> None:
    """Registra handlers de start/help en la Application."""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
