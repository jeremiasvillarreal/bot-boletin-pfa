"""
bot.handlers.utilidades — Comandos /ping, /hora, /eco.
"""

import time
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /ping — responde pong con latencia aproximada."""
    start = time.monotonic()
    msg = await update.message.reply_text("🏓 Pong!")
    latency_ms = (time.monotonic() - start) * 1000
    # Edita el mensaje para incluir latencia sin spamear
    try:
        await msg.edit_text(f"🏓 Pong! `{latency_ms:.0f}ms`", parse_mode="Markdown")
    except Exception:
        pass


async def hora(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /hora — hora actual del servidor."""
    now = datetime.now().astimezone()
    await update.message.reply_text(
        f"🕐 Hora del servidor:\n"
        f"`{now.strftime('%Y-%m-%d %H:%M:%S %Z')}`\n"
        f"ISO: `{now.isoformat()}`",
        parse_mode="Markdown",
    )


async def eco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /eco <texto> — repite el texto enviado."""
    if not context.args:
        await update.message.reply_text("📌 Uso: /eco <texto>\nEj: /eco Hola mundo!")
        return

    texto = " ".join(context.args)
    # Limite Telegram 4096 chars
    if len(texto) > 3500:
        texto = texto[:3500] + "… (truncado)"
    await update.message.reply_text(f"📣 {texto}")


def register_utilidades_handlers(application: Application) -> None:
    """Registra handlers de utilidades."""
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("hora", hora))
    application.add_handler(CommandHandler("eco", eco))
