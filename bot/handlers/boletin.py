"""
bot.handlers.boletin — Comandos /boletin para gestión Boletín Oficial 1ra

- /boletin → status + palabras + última ejecución
- /boletin_add palabra1, palabra2 → añade a lista global (persistida)
- /boletin_rm palabra → quita
- /boletin_list → lista palabras
- /boletin_test [palabra] → scrape en vivo hoy y muestra hits + resumen IA
- /boletin_check → fuerza poll manual (admin)
"""

import json
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bot.config import HF_TOKEN, get_boletin_palabras

logger = logging.getLogger(__name__)
BA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "boletin_palabras.json")
ULTIMO_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "boletin_ultimo.json")

def _load_palabras() -> list[str]:
    return get_boletin_palabras()

def _save_palabras(palabras: list[str]) -> None:
    try:
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump({"palabras": palabras, "updated": datetime.now(BA_TZ).isoformat()}, f, ensure_ascii=False, indent=2)
        # también actualizar env en memoria
        os.environ["BOLETIN_PALABRAS"] = ",".join(palabras)
    except Exception as e:
        logger.warning("No se pudo guardar palabras: %s", e)

def _get_notify_chat_id(update: Update) -> str:
    from bot.config import BOLETIN_NOTIFY_CHAT_ID
    if BOLETIN_NOTIFY_CHAT_ID.strip():
        return BOLETIN_NOTIFY_CHAT_ID.strip()
    if update.effective_chat:
        return str(update.effective_chat.id)
    return ""

async def boletin_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    palabras = _load_palabras()
    # leer ultimo
    ultimo = "—"
    try:
        if os.path.exists(ULTIMO_PATH):
            with open(ULTIMO_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                ultimo = data.get("fecha", "?") + " hits=" + str(data.get("hits", "?"))
    except Exception:
        pass
    now = datetime.now(BA_TZ).strftime("%Y-%m-%d %H:%M %Z")
    txt = (
        "📋 *Boletín Oficial 1ra+3ra* — modo manual `go`\n"
        f"🕐 Ahora: `{now}`\n"
        f"▶️ `go` (hoy) o `go DD/MM/AAAA`\n"
        f"🔑 Palabras: `{', '.join(palabras)}`\n"
        f"📊 Último: {ultimo}\n"
        f"💡 Tip: `go 03/08/2026` busca esa fecha"
    )
    await update.message.reply_text(txt, parse_mode="Markdown")

async def boletin_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    palabras = _load_palabras()
    if not palabras:
        await update.message.reply_text("🔑 Lista vacía. Usá `/boletin_add palabra1, palabra2`", parse_mode="Markdown")
        return
    await update.message.reply_text(f"🔑 Palabras globales ({len(palabras)}):\n• " + "\n• ".join(palabras))

async def boletin_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("📌 Uso: `/boletin_add gde, firma digital, modernización`\nSe añaden a lista global (separadas por coma)", parse_mode="Markdown")
        return
    raw = " ".join(context.args)
    nuevas = [p.strip() for p in raw.split(",") if p.strip()]
    if not nuevas:
        nuevas = [raw.strip()]
    actuales = _load_palabras()
    agregadas = []
    for n in nuevas:
        if n.lower() not in [a.lower() for a in actuales]:
            actuales.append(n)
            agregadas.append(n)
    _save_palabras(actuales)
    if agregadas:
        await update.message.reply_text(f"✅ Agregadas: `{', '.join(agregadas)}`\n📋 Lista ahora ({len(actuales)}): `{', '.join(actuales)}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ Ya estaban todas. Lista: `{', '.join(actuales)}`", parse_mode="Markdown")

async def boletin_rm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("📌 Uso: `/boletin_rm firma digital`", parse_mode="Markdown")
        return
    target = " ".join(context.args).strip()
    actuales = _load_palabras()
    nuevas = [p for p in actuales if p.lower() != target.lower()]
    if len(nuevas) == len(actuales):
        await update.message.reply_text(f"⚠️ No encontrada `{target}`. Lista: `{', '.join(actuales) if actuales else '(vacía)'}`", parse_mode="Markdown")
        return
    _save_palabras(nuevas)
    await update.message.reply_text(f"🗑️ Eliminada `{target}`\n📋 Quedan ({len(nuevas)}): `{', '.join(nuevas) if nuevas else '(vacía)'}`", parse_mode="Markdown")

async def boletin_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    palabras = _load_palabras()
    override = []
    if context.args:
        override = [p.strip() for p in " ".join(context.args).split(",") if p.strip()]
        if override:
            palabras = override
    if not palabras:
        await update.message.reply_text("⚠️ Sin palabras. Usá `/boletin_add palabra` o `/boletin_test gde`", parse_mode="Markdown")
        return
    await update.message.reply_text(f"🔍 Scrapeando Boletín 1ra de hoy para: `{', '.join(palabras)}`…", parse_mode="Markdown")
    try:
        from scraper.boletin import filtrar_por_palabras, resumir_ia, scrape_detalle, scrape_primera
        avisos = await scrape_primera()
        if not avisos:
            await update.message.reply_text("⚠️ Hoy no hay avisos o el sitio no respondió (¿SPA?). Probá `/boletin_check` en 5 min o revisá https://www.boletinoficial.gob.ar/seccion/primera")
            return
        hits = filtrar_por_palabras(avisos, palabras)
        if not hits:
            await update.message.reply_text(f"✅ Scrape ok: {len(avisos)} avisos hoy, 0 hits para `{', '.join(palabras)}`")
            return
        await update.message.reply_text(f"✅ {len(hits)} hit(s) de {len(avisos)} avisos\nProcesando resumen IA…")
        for h in hits[:5]:
            detalle = await scrape_detalle(h.url)
            resumen = await resumir_ia(detalle, h.titulo, HF_TOKEN)
            msg = (
                f"🔔 *{h.titulo[:120]}*\n"
                f"🔑 Match: `{', '.join(h.matched)}`\n"
                f"📝 Resumen: {resumen[:900]}\n"
                f"🔗 {h.url}"
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
        if len(hits) > 5:
            await update.message.reply_text(f"… y {len(hits)-5} más")
    except Exception as e:
        logger.exception("boletin_test falló")
        await update.message.reply_text(f"❌ Error test: {e}")

async def boletin_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # fuerza poll del scheduler (reusa lógica)
    await update.message.reply_text("⏳ Forzando poll 07:00 (feriado/finde check + scrape)…")
    try:
        from bot.jobs.boletin_scheduler import poll_boletin_once
        result = await poll_boletin_once(context.bot, force_notify=True, chat_id=str(update.effective_chat.id) if update.effective_chat else None)
        await update.message.reply_text(f"✅ Check done: {result}")
    except Exception as e:
        logger.exception("boletin_check error")
        await update.message.reply_text(f"❌ Error check: {e}")

async def boletin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /boletin sin args → status
    await boletin_status(update, context)

def _parse_fecha_arg(text: str | None) -> tuple[object, str]:
    """Parsea fecha de arg 'go 27/08/2026' → (date, label). Soporta DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD. Si vacío → hoy."""
    from datetime import date as _date
    if not text or not text.strip():
        hoy = datetime.now(BA_TZ).date()
        return hoy, "último (hoy)"
    t = text.strip()
    # extraer primer token que parezca fecha
    import re
    m = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})", t)
    candidate = m.group(1) if m else t
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            d = datetime.strptime(candidate, fmt).date()
            return d, d.strftime("%d/%m/%Y")
        except Exception:
            continue
    # fallback hoy
    hoy = datetime.now(BA_TZ).date()
    return hoy, f"último (hoy) — fecha '{candidate}' no válida, uso hoy"


async def go_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger manual 'go' — busca Boletín 1ra+3ra con palabras globales. Soporta 'go' y 'go 27/08/2026'. Busca en detalle completo."""
    logger.debug("[go_handler] dispatch called, context.args=%s, update.message.text=%s", 
                 context.args, update.message.text if update.message else None)
    raw_text = ""
    if context.args:
        raw_text = " ".join(context.args)
    elif update.message and update.message.text:
        txt = update.message.text.strip()
        raw_text = re.sub(r"(?i)^\s*/?go\s*", "", txt).strip()
    fecha, label = _parse_fecha_arg(raw_text)

    palabras = _load_palabras()
    status_msg = await update.message.reply_text(f"🚀 *GO {label}* — buscando Boletín 1ra+3ra del {label} para: `{', '.join(palabras)}`…\n⏳ Esto puede tardar 15-25s (scrape + IA)", parse_mode="Markdown")
    logger.info("[go_handler] GO %s palabras=%s chat=%s", label, palabras, update.effective_chat.id if update.effective_chat else "?")
    try:
        from scraper.boletin import filtrar_por_palabras_full, resumir_ia, scrape_ambas, scrape_detalle
        import asyncio
        # watchdog: timeout global 55s para no trabarse nunca
        try:
            avisos = await asyncio.wait_for(scrape_ambas(fecha), timeout=35)
        except asyncio.TimeoutError:
            await update.message.reply_text(f"⚠️ Timeout buscando {label} (boletinoficial.gob.ar lento). Probá de nuevo en 1 min o usá otra fecha.")
            logger.warning("[go_handler] timeout scrape_ambas %s", label)
            return
        if not avisos:
            await update.message.reply_text(f"⚠️ Sin avisos para {label} (¿no publicado/finde/feriado?). Probá otra fecha: `go 27/08/2026`")
            return
        # limitar a 25 detalles para no colgarse (watchdog externo también vigila)
        try:
            hits = await asyncio.wait_for(filtrar_por_palabras_full(avisos, palabras, max_detalle=25), timeout=30)
        except asyncio.TimeoutError:
            await update.message.reply_text(f"⚠️ Timeout filtrando {len(avisos)} avisos (demasiados detalles). Probá `go` sin fecha para hoy que es más rápido.")
            logger.warning("[go_handler] timeout filtrar %s", label)
            return
        if not hits:
            # mostrar conteo por sección para debug
            c1 = sum(1 for a in avisos if a.get("seccion")=="primera")
            c3 = sum(1 for a in avisos if a.get("seccion")=="tercera")
            await update.message.reply_text(f"✅ Boletín {label}: {len(avisos)} avisos (1ra:{c1} 3ra:{c3}), 0 hits para `{', '.join(palabras)}` (indistinto tildes/mayúsculas, busca en texto completo)")
            return
        await update.message.reply_text(f"✅ {len(hits)} hit(s) de {len(avisos)} avisos del {label} (1ra+3ra) — generando resumen IA…")
        for h in hits[:6]:
            # detalle ya está en preview si vino de filtrado full, sino fetch
            detalle = await scrape_detalle(h.url)
            if not detalle or len(detalle) < 200:
                detalle = h.preview
            resumen = await resumir_ia(detalle, h.titulo, HF_TOKEN)
            sec = "1ra" if h.seccion=="primera" else "3ra"
            msg = (
                f"🔔 *{h.titulo[:140]}* — {sec} — {label}\n"
                f"🔑 Match: `{', '.join(h.matched)}`\n"
                f"📝 {resumen[:900]}\n"
                f"🔗 {h.url}"
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
        if len(hits) > 6:
            await update.message.reply_text(f"… y {len(hits)-6} más")
    except Exception as e:
        logger.exception("go falló")
        await update.message.reply_text(f"❌ Error GO: {e}")

async def go_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para texto plano 'go' sin slash — robusto a mayúsculas y fecha."""
    logger.debug("[go_text_handler] recibido: %r", update.message.text if update.message else None)
    if not update.message or not update.message.text:
        return
    txt = update.message.text.strip().lower()
    # solo si empieza con go (descarta comandos como /start, /help, etc.)
    if not txt.startswith("go"):
        return
    # evitar que procese "/go" que ya maneja CommandHandler (evita duplicado)
    if txt.startswith("/"):
        return
    # debe ser "go" solo o "go " + algo
    if txt != "go" and not txt.startswith("go "):
        return
    logger.debug("[go_text_handler] dispatch a go_handler")
    await go_handler(update, context)

def register_boletin_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("boletin", boletin_handler))
    application.add_handler(CommandHandler("boletin_list", boletin_list))
    # alias con underscore para compat
    application.add_handler(CommandHandler("boletin_add", boletin_add))
    application.add_handler(CommandHandler("boletin_test", boletin_test))
    application.add_handler(CommandHandler("boletin_rm", boletin_rm))
    application.add_handler(CommandHandler("boletin_check", boletin_check))
    # modo manual: "go" y "go 27/08/2026" — ambos slash y sin slash
    application.add_handler(CommandHandler("go", go_handler))
    # MessageHandler con regex: solo mensajes que empiecen con "go" (case-insensitive).
    # Usamos patrones (?i) inline en lugar de re.IGNORECASE pq el API de PTB Regex
    # no acepta flags como arg posicional en todas las versiones.
    # Esto evita que el handler se dispare por /go (lo captura CommandHandler primero)
    # ni por texto aleatorio; solo "go", "GO", "go 27/08/2026", etc.
    application.add_handler(MessageHandler(filters.Regex(r"(?i)^go"), go_text_handler))
