"""
bot.handlers.info — Comandos /sysinfo y /calc.

- /sysinfo: muestra estado del bot, uptime, sistema, URLs monitoreadas, etc.
- /calc <expr>: calculadora simple (ej: /calc 2+2*3).
"""

import platform
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.config import MODO, get_boletin_palabras


async def sysinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /sysinfo — muestra estado y info del bot."""
    try:
        from bot.main import StartTime
    except ImportError:
        StartTime = datetime.now(timezone.utc)

    now = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
    uptime_sec = (datetime.now(timezone.utc) - StartTime).total_seconds()

    # Formatear uptime
    dias = int(uptime_sec // 86400)
    horas = int((uptime_sec % 86400) // 3600)
    mins = int((uptime_sec % 3600) // 60)
    secs = int(uptime_sec % 60)
    uptime_str = f"{dias}d {horas}h {mins}m {secs}s"

    # URLs monitoreadas
    try:
        from bot.handlers.scraper import WATCHED_URLS
        total_urls = sum(len(v) for v in WATCHED_URLS.values())
        chats_activos = len(WATCHED_URLS)
    except ImportError:
        total_urls = 0
        chats_activos = 0

    # Palabras boletín
    palabras = get_boletin_palabras()

    # Memoria (si psutil disponible)
    try:
        import psutil
        proc = psutil.Process()
        mem_mb = proc.memory_info().rss / 1024 / 1024
        mem_str = f"{mem_mb:.1f} MB"
    except ImportError:
        mem_str = "N/A (psutil no instalado)"

    msg = (
        "🖥️ *SysInfo — Estado del Bot*\n"
        "\n"
        f"⏱️ *Uptime:* `{uptime_str}`\n"
        f"🕐 *Hora AR:* `{now.strftime('%Y-%m-%d %H:%M:%S')}`\n"
        f"🌐 *Modo:* `{MODO}`\n"
        f"🐍 *Python:* `{sys.version.split()[0]}`\n"
        f"💻 *Plataforma:* `{platform.system()} {platform.release()[:20]}`\n"
        f"🧠 *RAM:* `{mem_str}`\n"
        f"\n📡 *Scraping:*\n"
        f"  • URLs monitoreadas: `{total_urls}` en `{chats_activos}` chat(s)\n"
        f"  • Jobs: `scrape_demo` (600s) + `boletin` (07:00/08:00 ART)\n"
        f"\n📋 *Boletín:*\n"
        f"  • Palabras: `{', '.join(palabras)}`\n"
        f"\n🔧 *Handlers activos:* 12 comandos\n"
        f"  • /start /help /sysinfo /calc\n"
        f"  • /ping /hora /eco\n"
        f"  • /watch /scrape_demo\n"
        f"  • /boletin /go /boletin_list /boletin_add /boletin_rm /boletin_test /boletin_check\n"
        f"\n❤️ Health: `GET /health` → UptimeRobot cada 5 min"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# --- Calculadora segura ---

_ALLOWED_CHARS = set("0123456789+-*/.() %")


def _safe_eval(expr: str) -> float | None:
    """Evalúa una expresión matemática simple de forma segura.
    Solo permite números, operadores y paréntesis.
    """
    clean = expr.replace(" ", "")
    if not clean:
        return None
    if not all(c in _ALLOWED_CHARS for c in clean):
        return None
    # Prevenir cosas raras tipo import, __, etc.
    if any(kw in clean for kw in ("__", "import", "exec", "eval", "open", "os.", "sys.")):
        return None
    try:
        result = eval(clean, {"__builtins__": {}}, {})
        return float(result)
    except Exception:
        return None


async def calc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /calc <expr> — calculadora simple."""
    if not context.args:
        await update.message.reply_text(
            "🧮 Uso: `/calc 2+2*3`\n"
            "Operadores: `+` `-` `*` `/` `()`\n"
            "Ej: `/calc (100+50)/3`",
            parse_mode="Markdown",
        )
        return

    expr = " ".join(context.args)
    result = _safe_eval(expr)

    if result is None:
        await update.message.reply_text(f"❌ No pude evaluar: `{expr}`", parse_mode="Markdown")
        return

    # Formatear: si es entero, mostrar sin decimales
    if result == int(result):
        display = str(int(result))
    else:
        display = f"{result:.6g}"

    await update.message.reply_text(f"🧮 `{expr}` = `{display}`", parse_mode="Markdown")


def register_info_handlers(application: Application) -> None:
    """Registra handlers de info."""
    application.add_handler(CommandHandler("sysinfo", sysinfo))
    application.add_handler(CommandHandler("calc", calc))
