"""
bot.jobs.boletin_scheduler — Poll Boletín 1ra cada hora + envío al arranque

Flujo:
  1. Al arranque: scrapea y envía lo último que no se envió antes
  2. Cada 60 min: scrapea, envía solo avisos nuevos (dedup por ID)
  3. Skip finde/feriado (no hace requests innecesarias)

Dedup: data/boletin_sent_ids.json guarda IDs de avisos ya enviados.
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
SENT_IDS_PATH = os.path.join(DATA_DIR, "boletin_sent_ids.json")
ULTIMO_PATH = os.path.join(DATA_DIR, "boletin_ultimo.json")
HASH_PATH = os.path.join(DATA_DIR, "boletin_hash.json")
FERIADOS_CACHE = os.path.join(DATA_DIR, "feriados_cache.json")

_last_hash = None


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


# --- Persistencia de IDs enviados ---

def _load_sent_ids() -> set[str]:
    """Carga IDs de avisos ya enviados."""
    try:
        if os.path.exists(SENT_IDS_PATH):
            with open(SENT_IDS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                ids = data.get("ids", [])
                return set(ids) if isinstance(ids, list) else set()
    except Exception:
        pass
    return set()


def _save_sent_ids(sent: set[str]) -> None:
    """Guarda IDs de avisos enviados."""
    _ensure_data_dir()
    try:
        with open(SENT_IDS_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "ids": sorted(sent),
                "updated": datetime.now(BA_TZ).isoformat(),
                "count": len(sent),
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("No se pudo guardar sent_ids: %s", e)


# --- Hash de edición (detecta cambios) ---

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


# --- Helpers ---

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


async def _enviar_hits(bot, hits, avisos_total: int, sent_ids: set[str]) -> int:
    """Envía hits que no están en sent_ids. Retorna cantidad enviada."""
    from bot.config import HF_TOKEN
    from scraper.boletin import resumir_ia, scrape_detalle

    chat_ids = await _get_notificar_chat_ids()
    if not chat_ids:
        logger.warning("No hay BOLETIN_NOTIFY_CHAT_ID, no se notifica")
        return 0

    enviados = 0
    for h in hits:
        if h.id in sent_ids:
            continue
        if enviados >= 10:
            break

        try:
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
            sent_ids.add(h.id)
            enviados += 1
        except Exception as e:
            logger.warning("Error enviando hit %s: %s", h.id, e)

    if len(hits) > enviados and enviados > 0:
        for cid in chat_ids:
            try:
                await bot.send_message(chat_id=cid,
                    text=f"… y {len(hits) - enviados} coincidencias más (ya enviadas anteriormente)")
            except Exception:
                pass

    return enviados


# --- Core: scrape + filter + dedup ---

async def _procesar_nuevos(bot, force_notify: bool = False, chat_id: str | None = None) -> str:
    """Scrapea 1ra, filtra por palabras, retorna string con resultado."""
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
        _save_ultimo(hoy.isoformat(), 0, 0)
        return "sin avisos (posible no publicado)"

    h = _hash_avisos(avisos)
    global _last_hash
    if _last_hash is None:
        _last_hash = _load_hash()

    sent_ids = _load_sent_ids()
    hits = filtrar_por_palabras(avisos, palabras) if palabras else []

    # Filtrar solo los que no se enviaron antes
    nuevos = [hit for hit in hits if hit.id not in sent_ids]

    if not nuevos:
        _save_ultimo(hoy.isoformat(), 0, len(avisos))
        if hits:
            return f"0 nuevos de {len(hits)} hits ({len(avisos)} avisos, ya enviados)"
        return f"sin cambios ({len(avisos)} avisos)"

    # Hay nuevos: enviar
    enviados = 0
    if force_notify and chat_id:
        from bot.config import HF_TOKEN
        from scraper.boletin import resumir_ia, scrape_detalle
        for hit in nuevos[:5]:
            if hit.id in sent_ids:
                continue
            try:
                det = await scrape_detalle(hit.url)
                res = await resumir_ia(det, hit.titulo, HF_TOKEN)
                msg = (
                    f"🔔 *{hit.titulo[:130]}*\n"
                    f"🔑 `{', '.join(hit.matched)}`\n"
                    f"📝 {res[:800]}\n"
                    f"🔗 {hit.url}"
                )
                await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                sent_ids.add(hit.id)
                enviados += 1
            except Exception as e:
                logger.warning("Error notificando %s: %s", hit.id, e)
    else:
        enviados = await _enviar_hits(bot, nuevos, len(avisos), sent_ids)

    _save_sent_ids(sent_ids)
    _save_ultimo(hoy.isoformat(), enviados, len(avisos))

    if _last_hash != h:
        _last_hash = h
        _save_hash(h, hoy.isoformat())

    return f"{enviados} nuevos enviados de {len(hits)} hits ({len(avisos)} avisos)"


# --- Jobs ---

async def _job_startup(context: ContextTypes.DEFAULT_TYPE):
    """Al arranque: envía todo lo nuevo sin importar la hora."""
    logger.info("[boletin] Startup job ejecutando — enviando contenido nuevo")
    result = await _procesar_nuevos(context.bot, force_notify=False)
    logger.info("[boletin] Startup result: %s", result)


async def _job_hourly(context: ContextTypes.DEFAULT_TYPE):
    """Cada 60 min: scrapea, envía solo avisos nuevos."""
    logger.info("[boletin] Hourly job ejecutando")
    result = await _procesar_nuevos(context.bot, force_notify=False)
    logger.info("[boletin] Hourly result: %s", result)


async def boletin_check_manual(bot, force_notify: bool = False, chat_id: str | None = None) -> str:
    """Check manual (desde /boletin_check). Retorna string status."""
    return await _procesar_nuevos(bot, force_notify=force_notify, chat_id=chat_id)


def setup_boletin_jobs(application: Application) -> None:
    if application.job_queue is None:
        logger.warning("[boletin] JobQueue no disponible")
        return

    # Startup: envía lo nuevo a los 20s del arranque
    application.job_queue.run_once(_job_startup, when=20, name="boletin_startup")
    logger.info("[boletin] Startup job: envía contenido nuevo a los 20s")

    # Hourly: cada 60 min
    application.job_queue.run_repeating(_job_hourly, interval=3600, first=3620, name="boletin_hourly")
    logger.info("[boletin] Hourly job: cada 60 min (primero a los ~60 min)")
