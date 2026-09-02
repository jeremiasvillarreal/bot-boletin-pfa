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
    "🖥️ *SysInfo* — `/sysinfo` para ver estado del bot y sistema.\n"
    "🧮 *Calculadora* — `/calc 2+2*3` para matemáticas rápidas.\n"
    "🔍 *Scraping* — `/watch <url>` para monitorear una URL, `/scrape\\_demo` para demo en vivo.\n"
    "📋 *Boletín* — `/boletin` para gestión del Boletín Oficial Oficial.\n"
    "🛠️ *Utilidades* — `/ping`, `/hora`, `/eco <texto>`.\n"
    "🚀 *24/7 Gratis* — corriendo en Render Free + UptimeRobot.\n"
    "\n"
    "Escribí /help para ver todos los comandos."
)

HELP_MSG = (
    "📖 *Comandos disponibles*\n"
    "\n"
    "*Generales*\n"
    "• /start — Mensaje de bienvenida\n"
    "• /help — Esta ayuda\n"
    "• /sysinfo — Estado del bot, uptime, sistema\n"
    "\n"
    "*Utilidades* 🛠️\n"
    "• /ping — Latencia del bot\n"
    "• /hora — Hora actual del servidor\n"
    "• /eco <texto> — Repite tu texto\n"
    "• /calc <expr> — Calculadora (ej: `/calc 2+2*3`)\n"
    "\n"
    "*Scraping* 🔍\n"
    "• /watch <url> — Guarda una URL en memoria para monitoreo\n"
    "• /scrape\\_demo — Demo scraping Playwright + BeautifulSoup + httpx\n"
    "\n"
    "*Boletín Oficial* 📋\n"
    "• /boletin — Status del boletín\n"
    "• /go — Scrapea Boletín 1ra+3ra de hoy\n"
    "• /go DD/MM/AAAA — Scrapea una fecha específica\n"
    "• /boletin\\_list — Lista palabras clave\n"
    "• /boletin\\_add palabra — Agrega palabra\n"
    "• /boletin\\_rm palabra — Quita palabra\n"
    "• /boletin\\_test — Test en vivo\n"
    "\n"
    "💡 *Tip:* Cada feature es un handler modular en `bot/handlers/`.\n"
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
