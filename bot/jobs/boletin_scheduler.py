"""
bot.jobs.boletin_scheduler — Poll Boletin 1ra 07:00 retry 08:00 ART, skip finde/feriado

Catch-up al arranque: si el bot se reinicia despues de las 07:00 y antes de las 12:00
en dia habil, ejecuta un poll inmediato para no perder la edicion del dia.
"""

import json
import logging
import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

logger = logging.getLogger(__name__)
BA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
ULTIMO_PATH = os.path.join(DATA_DIR, "boletin_ultimo.json")
HASH_PATH = os.path.join(DATA_DIR, "boletin_hash.json")
FERIADOS_CACHE = os.path.join(DATA_DIR, "feriados_cache.json")

_pending_07 = False
_last_hash = None


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_hash() -> str | None:
    try:
        if os.path.exists(HASH_PATH):
            with open(HASH_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("hash")
    except Exception:
        pass
    return None


def _save_hash(h: str, fecha: str):
    _ensure_data_dir()
    try:
        with open(HASH_PATH, "w", encoding="utf-8") as f:
            json.dump({"hash": h, "fecha": fecha}, f)
    except Exception:
        pass


def _save_ultimo(fecha: str, hits: int, total: int):
    _ensure_data_dir()
    try:
        with open(ULTIMO_PATH, "w", encoding="utf-8") as f:
            json.dump({"fecha": fecha, "hits": hits, "total": total,
                        "ts": datetime.now(BA_TZ).isoformat()}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


async def es_feriado(fecha: date) -> bool:
    if fecha.weekday() >= 5:
        return True
    year = fecha.year
    cache = {}
    if os.path.exists(FERIADOS_CACHE):
        try:
            with open(FERIADOS_CACHE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                if str(year) in cache:
                    return fecha.isoformat() in set(cache[str(year)])
        except Exception:
            pass
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"https://date.nager.at/api/v3/PublicHolidays/{year}/AR")
            if resp.status_code == 200:
                data = resp.json()
                fechas = [d.get("date") for d in data if d.get("date")]
                _ensure_data_dir()
                cache[str(year)] = fechas
                with open(FERIADOS_CACHE, "w", encoding="utf-8") as f:
                    json.dump(cache, f)
                return fecha.isoformat() in fechas
    except Exception as e:
        logger.warning("feriado API fallo: %s", e)
    return False


async def _get_notificar_chat_ids() -> list[str]:
    from bot.config import BOLETIN_NOTIFY_CHAT_ID
    ids = []
    if BOLETIN_NOTIFY_CHAT_ID.strip():
        for x in BOLETIN_NOTIFY_CHAT_ID.split(","):
            x = x.strip()
            if x:
                ids.append(x)
    return ids


def _hash_avisos(avisos: list[dict]) -> str:
    import hashlib
    payload = json.dumps(sorted([a.get("id", "") for a in avisos]), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


async def _enviar_hits(bot, hits, avisos_total: int):
    from bot.config import HF_TOKEN
    from scraper.boletin import resumir_ia, scrape_detalle
    chat_ids = await _get_notificar_chat_ids()
    if not chat_ids:
        logger.warning("No hay BOLETIN_NOTIFY_CHAT_ID, no se notifica")
        return
    for h in hits[:5]:
        detalle = await scrape_detalle(h.url)
        resumen = await resumir_ia(detalle, h.titulo, HF_TOKEN)
        msg = (
            f"🔔 *Boletín Oficial 1ra - {h.fecha or datetime.now(BA_TZ).strftime('%d/%m/%Y')}*\n"
            f"📌 *{h.titulo[:140]}*\n"
            f"🔑 Coincide: `{', '.join(h.matched)}`\n"
            f"📝 _{resumen[:850]}_\n"
            f"🔗 {h.url}\n"
            f"_{avisos_total} avisos hoy_"
        )
        for cid in chat_ids:
            try:
                await bot.send_message(chat_id=cid, text=msg, parse_mode="Markdown")
            except Exception as e:
                logger.warning("No se pudo notificar %s: %s", cid, e)
    if len(hits) > 5:
        for cid in chat_ids:
            try:
                await bot.send_message(chat_id=cid, text=f"… y {len(hits)-5} coincidencias más hoy")
            except Exception:
                pass


async def poll_boletin_once(bot, force_notify: bool = False, chat_id: str | None = None) -> str:
    from bot.config import get_boletin_palabras
    from scraper.boletin import filtrar_por_palabras, scrape_primera

    hoy = datetime.now(BA_TZ).date()
    if not force_notify and await es_feriado(hoy):
        return f"skip feriado/finde {hoy}"

    palabras = get_boletin_palabras()
    if not palabras and not force_notify:
        return "skip sin palabras"

    avisos = await scrape_primera(hoy)
    if not avisos:
        if force_notify:
            target = chat_id or (await _get_notificar_chat_ids())[0] if (await _get_notificar_chat_ids()) else None
            if target:
                try:
                    await bot.send_message(chat_id=target,
                        text=f"⚠️ Sin avisos 1ra hoy {hoy.strftime('%d/%m')} (¿aún no publicado o feriado?). Reintento 08:00.",
                        parse_mode="Markdown")
                except Exception:
                    pass
        _save_ultimo(hoy.isoformat(), 0, 0)
        return "sin avisos (posible no publicado)"

    h = _hash_avisos(avisos)
    global _last_hash
    if _last_hash is None:
        _last_hash = _load_hash()
    if not force_notify and _last_hash == h:
        _save_ultimo(hoy.isoformat(), 0, len(avisos))
        return f"sin cambios ({len(avisos)} avisos)"

    _last_hash = h
    _save_hash(h, hoy.isoformat())

    if not palabras:
        palabras = ["(test)"]
        hits = filtrar_por_palabras(avisos, palabras) if not force_notify else []
        _save_ultimo(hoy.isoformat(), len(hits), len(avisos))
        return f"sin palabras configuradas, {len(avisos)} avisos"

    hits = filtrar_por_palabras(avisos, palabras)
    _save_ultimo(hoy.isoformat(), len(hits), len(avisos))

    if hits:
        if force_notify and chat_id:
            from bot.config import HF_TOKEN
            from scraper.boletin import resumir_ia, scrape_detalle
            for hit in hits[:3]:
                det = await scrape_detalle(hit.url)
                res = await resumir_ia(det, hit.titulo, HF_TOKEN)
                msg = f"🔔 *{hit.titulo[:130]}*\n🔑 `{', '.join(hit.matched)}`\n📝 {res[:800]}\n🔗 {hit.url}"
                try:
                    await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                except Exception:
                    pass
            return f"{len(hits)} hits (notificado a {chat_id})"
        else:
            await _enviar_hits(bot, hits, len(avisos))
            return f"{len(hits)} hits notificados"
    else:
        if force_notify and chat_id:
            try:
                await bot.send_message(chat_id=chat_id,
                    text=f"✅ Boletín hoy {hoy.strftime('%d/%m')}: {len(avisos)} avisos, 0 coincidencias para `{', '.join(palabras)}`")
            except Exception:
                pass
        return f"0 hits de {len(avisos)}"


async def _job_07(context: ContextTypes.DEFAULT_TYPE):
    global _pending_07
    hoy = datetime.now(BA_TZ).date()
    if await es_feriado(hoy):
        _pending_07 = False
        return
    from bot.config import get_boletin_palabras
    if not get_boletin_palabras():
        return
    from scraper.boletin import scrape_primera
    avisos = await scrape_primera(hoy)
    if not avisos:
        logger.info("[boletin] 07:00 sin edicion aun, retry 08:00")
        _pending_07 = True
        return
    _pending_07 = False
    result = await poll_boletin_once(context.bot, force_notify=False)
    logger.info("[boletin] 07:00 result %s", result)


async def _job_08(context: ContextTypes.DEFAULT_TYPE):
    global _pending_07
    hoy = datetime.now(BA_TZ).date()
    if await es_feriado(hoy):
        _pending_07 = False
        return
    from bot.config import get_boletin_palabras
    if not get_boletin_palabras():
        return
    if not _pending_07:
        result = await poll_boletin_once(context.bot, force_notify=False)
        logger.info("[boletin] 08:00 (no pending) check %s", result)
        return
    _pending_07 = False
    from scraper.boletin import scrape_primera
    avisos = await scrape_primera(hoy)
    if not avisos:
        chat_ids = await _get_notificar_chat_ids()
        for cid in chat_ids:
            try:
                await context.bot.send_message(chat_id=cid,
                    text=f"⚠️ *Boletín 1ra sin publicación al 08:00 ART* hoy {hoy.strftime('%d/%m/%Y')}. Reintento mañana 07:00.",
                    parse_mode="Markdown")
            except Exception as e:
                logger.warning("08:00 notify fallo %s", e)
        return
    result = await poll_boletin_once(context.bot, force_notify=False)
    logger.info("[boletin] 08:00 retry result %s", result)


async def _catchup_job(context: ContextTypes.DEFAULT_TYPE):
    """Ejecuta un poll inmediato al arranque si es dia habil y estamos entre 07:15 y 12:00.
    Evita perder la edicion si el bot se reinicio despues de las 07:00."""
    now = datetime.now(BA_TZ)
    hoy = now.date()
    hora = now.hour

    if await es_feriado(hoy):
        return
    if hora < 7 or hora >= 12:
        return

    logger.info("[boletin] Catch-up arranque: dia habil %s, hora %d:%d — ejecutando poll", hoy, hora, now.minute)
    result = await poll_boletin_once(context.bot, force_notify=False)
    logger.info("[boletin] Catch-up result: %s", result)


def setup_boletin_jobs(application: Application) -> None:
    if application.job_queue is None:
        logger.warning("[boletin] JobQueue no disponible")
        return

    application.job_queue.run_daily(_job_07, time(hour=7, minute=0, tzinfo=BA_TZ), name="boletin_07")
    application.job_queue.run_daily(_job_08, time(hour=8, minute=0, tzinfo=BA_TZ), name="boletin_08")
    logger.info("[boletin] Jobs 07:00 y 08:00 ART registrados")

    # Catch-up: poll inmediato a los 15s del arranque si es dia habil 07:15-12:00
    application.job_queue.run_once(_catchup_job, when=15, name="boletin_catchup")
    logger.info("[boletin] Catch-up job programado a los 15s del arranque")
