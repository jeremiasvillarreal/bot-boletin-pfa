"""
scraper.boletin — Scraping Boletín Oficial 1ra Sección + matching + resumen IA

Flujo nube gratis (MODO=cloud):
  httpx GET /seccion/primera/{fecha} -> BeautifulSoup -> lista avisos
  si 0 resultados -> fallback playwright headless (scraper/base.py)
  scrape_detalle para texto completo -> filtrar por palabras -> resumir IA (HF) -> notificar

Investigación horario: publicación 00:00-06:00 ART, ventana bot 07:00/08:00

Uso:
  python -m scraper.boletin --fecha 2026-08-29 --palabras "gde,firma digital"
  python -m scraper.boletin --test-vivo
"""

import asyncio
import logging
import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from scraper.base import close_browser, get_context_and_page

BASE = "https://www.boletinoficial.gob.ar"
BA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9",
}

class Aviso(BaseModel):
    id: str = Field(description="ID aviso extraído de URL detalleAviso")
    titulo: str
    organismo: str = ""
    fecha: str = ""
    url: str
    preview: str = ""
    seccion: str = "primera"
    matched: list[str] = Field(default_factory=list)

def normalizar(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s

def palabras_desde_env(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]

def _parse_html(html: str, fecha_str: str = "", seccion: str = "primera") -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    resultados = []
    # Estrategia 1: enlaces a detalleAviso/{seccion}
    for a in soup.select(f'a[href*="detalleAviso/{seccion}"]'):
        href = a.get("href", "")
        if not href:
            continue
        url = href if href.startswith("http") else BASE + href if href.startswith("/") else BASE + "/" + href
        m = re.search(rf"detalleAviso/{seccion}/(\d+)", href)
        aviso_id = m.group(1) if m else href[-20:]
        titulo = a.get_text(strip=True)
        if not titulo or len(titulo) < 5:
            parent = a.find_parent("div") or a
            titulo = parent.get_text(" ", strip=True)[:300]
        if not titulo:
            continue
        organismo = ""
        preview = ""
        card = a.find_parent("div", class_=re.compile("item|aviso|result", re.I)) or a.parent
        if card:
            preview = card.get_text(" ", strip=True)[:600]
        resultados.append({
            "id": aviso_id,
            "titulo": titulo[:400],
            "organismo": organismo,
            "fecha": fecha_str,
            "url": url,
            "preview": preview,
            "seccion": seccion,
        })
    # Dedupe por id
    seen = set()
    uniq = []
    for r in resultados:
        if r["id"] not in seen:
            seen.add(r["id"])
            uniq.append(r)
    # Estrategia 2: si 0 resultados, probar selectores genéricos fallback
    if not uniq:
        for el in soup.select("div, article, li"):
            txt = el.get_text(" ", strip=True)
            if len(txt) > 40 and any(k in txt.lower() for k in ["resolucion", "decreto", "disposicion", "aviso oficial"]):
                link = el.select_one('a[href*="detalleAviso"]')
                if link:
                    href = link.get("href", "")
                    url = href if href.startswith("http") else BASE + href
                    m = re.search(rf"detalleAviso/{seccion}/(\d+)", href)
                    aviso_id = m.group(1) if m else str(hash(txt))[:10]
                    uniq.append({"id": aviso_id, "titulo": txt[:400], "organismo": "", "fecha": fecha_str, "url": url, "preview": txt[:600], "seccion": seccion})
        seen = set()
        uniq2 = []
        for r in uniq:
            if r["id"] not in seen:
                seen.add(r["id"])
                uniq2.append(r)
        uniq = uniq2
    return uniq

def _parse_primera_html(html: str, fecha_str: str = "") -> list[dict]:
    return _parse_html(html, fecha_str, "primera")

def _parse_tercera_html(html: str, fecha_str: str = "") -> list[dict]:
    return _parse_html(html, fecha_str, "tercera")

async def _scrape_seccion_httpx(seccion: str, fecha: date | None = None) -> list[dict]:
    if fecha is None:
        fecha = datetime.now(BA_TZ).date()
    fecha_str = fecha.strftime("%Y%m%d")
    fecha_iso = fecha.strftime("%Y-%m-%d")
    urls = [
        f"{BASE}/seccion/{seccion}/{fecha_str}",
        f"{BASE}/seccion/{seccion}",
        f"{BASE}/seccion/{seccion}/{fecha_iso}",
    ]
    last_html = ""
    parser = _parse_primera_html if seccion == "primera" else _parse_tercera_html
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=15.0, headers=HEADERS, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                html = resp.text
                if "loader.gif" in html and len(html) < 5000:
                    last_html = html
                    continue
                parsed = parser(html, fecha_str)
                if parsed:
                    return parsed
                last_html = html
        except Exception:
            continue
    if last_html:
        parsed = parser(last_html, fecha_str)
        return parsed
    return []

async def scrape_primera_httpx(fecha: date | None = None) -> list[dict]:
    return await _scrape_seccion_httpx("primera", fecha)

async def scrape_tercera_httpx(fecha: date | None = None) -> list[dict]:
    return await _scrape_seccion_httpx("tercera", fecha)

async def _scrape_seccion_playwright(seccion: str, fecha: date | None = None) -> list[dict]:
    if fecha is None:
        fecha = datetime.now(BA_TZ).date()
    fecha_str = fecha.strftime("%Y%m%d")
    url = f"{BASE}/seccion/{seccion}/{fecha_str}"
    from playwright.async_api import async_playwright
    parser = _parse_primera_html if seccion == "primera" else _parse_tercera_html
    async with async_playwright() as p:
        browser, context, page = await get_context_and_page(p)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            try:
                await page.wait_for_selector('a[href*="detalleAviso"]', timeout=8000)
            except Exception:
                await page.wait_for_timeout(3000)
            html = await page.content()
        finally:
            await close_browser(browser)
    return parser(html, fecha_str)

async def scrape_primera_playwright(fecha: date | None = None) -> list[dict]:
    return await _scrape_seccion_playwright("primera", fecha)

async def scrape_tercera_playwright(fecha: date | None = None) -> list[dict]:
    return await _scrape_seccion_playwright("tercera", fecha)

async def scrape_primera(fecha: date | None = None) -> list[dict]:
    res = await scrape_primera_httpx(fecha)
    if res:
        return res
    try:
        res2 = await scrape_primera_playwright(fecha)
        return res2
    except Exception as e:
        print(f"[boletin] playwright primera fallback falló: {e}")
        return res

async def scrape_tercera(fecha: date | None = None) -> list[dict]:
    res = await scrape_tercera_httpx(fecha)
    if res:
        return res
    try:
        res2 = await scrape_tercera_playwright(fecha)
        return res2
    except Exception as e:
        print(f"[boletin] playwright tercera fallback falló: {e}")
        return res

async def scrape_ambas(fecha: date | None = None) -> list[dict]:
    """Scrapea 1ra + 3ra en paralelo."""
    r1, r3 = await asyncio.gather(scrape_primera(fecha), scrape_tercera(fecha))
    # dedupe por id manteniendo seccion
    seen = set()
    out=[]
    for r in r1 + r3:
        k=(r.get("seccion",""), r.get("id",""))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out

async def scrape_detalle(url: str) -> str:
    # intenta httpx primero
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.text) > 500:
                soup = BeautifulSoup(resp.text, "lxml")
                # texto principal suele estar en div con contenido
                # probar múltiples selectores
                for sel in ["div#cuerpoAviso", "div.aviso", "div.detalle", "article", "div.container"]:
                    el = soup.select_one(sel)
                    if el:
                        txt = el.get_text(" ", strip=True)
                        if len(txt) > 200:
                            return txt[:8000]
                # fallback todo el body
                txt = soup.get_text(" ", strip=True)
                if len(txt) > 200:
                    return txt[:8000]
    except Exception:
        pass
    # fallback playwright si httpx no trajo contenido útil
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser, context, page = await get_context_and_page(p)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
                html = await page.content()
            finally:
                await close_browser(browser)
        soup = BeautifulSoup(html, "lxml")
        txt = soup.get_text(" ", strip=True)
        return txt[:8000]
    except Exception:
        return ""

def filtrar_por_palabras(avisos: list[dict], palabras: list[str]) -> list[Aviso]:
    if not palabras:
        return []
    palabras_n = [normalizar(p) for p in palabras]
    hits: list[Aviso] = []
    for av in avisos:
        texto = normalizar(f"{av.get('titulo','')} {av.get('preview','')} {av.get('organismo','')}")
        matched = []
        for orig, norm in zip(palabras, palabras_n):
            if norm and norm in texto:
                matched.append(orig)
            elif norm and re.search(rf"\b{re.escape(norm)}\b", texto):
                matched.append(orig)
        if matched:
            hits.append(Aviso(
                id=av.get("id",""),
                titulo=av.get("titulo","")[:400],
                organismo=av.get("organismo",""),
                fecha=av.get("fecha",""),
                url=av.get("url",""),
                preview=av.get("preview","")[:600],
                seccion=av.get("seccion","primera"),
                matched=matched,
            ))
    return hits

async def filtrar_por_palabras_full(avisos: list[dict], palabras: list[str], max_detalle: int = 40) -> list[Aviso]:
    """Filtra por palabras buscando también en el texto completo del detalle (fetch concurrente)."""
    if not palabras:
        return []
    palabras_n = [normalizar(p) for p in palabras]
    # primero filtrado rápido por titulo
    hits_rapidos = filtrar_por_palabras(avisos, palabras)
    ya_ids = {h.id for h in hits_rapidos}
    # para los no matcheados, buscar en detalle (limitado a max_detalle para no saturar)
    candidatos = [av for av in avisos if av.get("id") not in ya_ids][:max_detalle]
    # fetch detalle en paralelo con límite
    sem = asyncio.Semaphore(6)
    async def fetch_one(av):
        async with sem:
            try:
                txt = await scrape_detalle(av.get("url",""))
                return av, txt
            except Exception:
                return av, ""
    results = await asyncio.gather(*[fetch_one(av) for av in candidatos])
    extra_hits=[]
    for av, detalle in results:
        texto = normalizar(f"{av.get('titulo','')} {av.get('preview','')} {detalle}")
        matched=[]
        for orig, norm in zip(palabras, palabras_n):
            if norm and norm in texto:
                matched.append(orig)
        if matched:
            extra_hits.append(Aviso(
                id=av.get("id",""),
                titulo=av.get("titulo","")[:400],
                organismo=av.get("organismo",""),
                fecha=av.get("fecha",""),
                url=av.get("url",""),
                preview=detalle[:600] if detalle else av.get("preview","")[:600],
                seccion=av.get("seccion","primera"),
                matched=matched,
            ))
    # combinar manteniendo orden original
    todos = hits_rapidos + extra_hits
    # dedupe
    seen=set()
    uniq=[]
    for h in todos:
        if h.id not in seen:
            seen.add(h.id)
            uniq.append(h)
    return uniq
def _resumen_extractivo(texto: str, titulo: str = "") -> str:
    """Resumen claro en 1-2 oraciones para normativa del Boletín Oficial.

    Estrategia: buscar la frase con verbo legal + scoring por datos concretos.
    """
    if not texto or len(texto.strip()) < 50:
        texto = titulo
    txt = texto.replace("\n", " ").replace("\r", " ").strip()
    txt = txt.replace("�", " ")
    txt = re.sub(r"\s+", " ", txt)
    frases = re.split(r"(?<=[\.。])\s+", txt)

    todos_verbos = [
        "dispone", "establece", "fija", "determina", "reglamenta",
        "otorg", "conced", "asigna", "adjudica", "suma fija", "bonif",
        "autoriza", "habilita", "permite", "aprueba",
        "designa", "nombr", "remueve", "separa", "cesa",
        "crea", "constit", "instaura", "modifica", "deroga", "suspende",
        "declara", "reconoce", "resuelve",
    ]

    mejor_frase = ""
    mejor_score = 0
    for f in frases:
        fl = f.lower().strip()
        if len(fl) < 15:
            continue
        score = 0
        for v in todos_verbos:
            if v in fl:
                score += 2
                break
        if re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", fl):
            score += 1
        if re.search(r"\$|pesos|USD|U\$S", fl):
            score += 1
        if re.search(r"art[íi]culo|ley|decreto|resoluci[oó]n|disposici[oó]n", fl):
            score += 1
        if score > mejor_score:
            mejor_score = score
            mejor_frase = f.strip()

    if not mejor_frase or mejor_score < 2:
        sustanciales = [f.strip() for f in frases if len(f.strip()) > 25]
        if sustanciales:
            mejor_frase = ". ".join(sustanciales[:2])

    partes = []
    if titulo:
        partes.append(titulo.strip()[:150])
    if mejor_frase:
        if len(mejor_frase) > 350:
            mejor_frase = mejor_frase[:350].rstrip()
            last_dot = mejor_frase.rfind(".")
            if last_dot > 100:
                mejor_frase = mejor_frase[:last_dot + 1]
            else:
                mejor_frase += "…"
        partes.append(mejor_frase)
    elif txt:
        partes.append(txt[:400])

    resumen = " — ".join(partes) if len(partes) > 1 else (partes[0] if partes else txt[:400])
    return resumen[:950]


async def resumir_ia(texto: str, titulo: str = "", hf_token: str | None = None) -> str:
    """Resumen en 1-2 oraciones: de qué trata la norma del Boletín Oficial.

    Cadena: Qwen2.5-3B (generativo, rápido) → bart-large-cnn (extractivo) → extractivo local.
    """
    if not texto or len(texto.strip()) < 50:
        texto = titulo
    texto = texto[:7000]

    if not (hf_token and hf_token.strip().startswith("hf_")):
        return _resumen_extractivo(texto, titulo)

    token = hf_token.strip()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1) Qwen2.5-3B-Instruct — rápido, buen español, formato chat
    try:
        url = "https://router.huggingface.co/hf-inference/models/Qwen/Qwen2.5-3B-Instruct"
        messages = [
            {"role": "system", "content": (
                "Sos un asistente que resume normas del Boletín Oficial argentino. "
                "Escribí UNA sola oración clara en español que explique qué hace la norma, "
                "a quién va dirigida y qué habilita. Sé directo, sin intro ni conclusión."
            )},
            {"role": "user", "content": f"Título: {titulo}\n\nTexto de la norma:\n{texto[:2500]}"}
        ]
        payload = {
            "messages": messages,
            "parameters": {"max_new_tokens": 150, "temperature": 0.2}
        }
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                gen = ""
                if isinstance(data, list) and data:
                    gen = data[0].get("generated_text", "")
                elif isinstance(data, dict):
                    gen = data.get("generated_text", "")
                gen = gen.strip()
                gen = re.sub(
                    r"^(Resumen:|La norma|Esta norma|El decreto|Según|De acuerdo)\s*",
                    "", gen, flags=re.I
                ).strip()
                if gen and len(gen) > 25:
                    return gen[:950]
    except Exception as e:
        logging.getLogger(__name__).debug("Qwen falló: %s", e)

    # 2) bart-large-cnn — extractivo como respaldo
    try:
        url2 = "https://router.huggingface.co/hf-inference/models/facebook/bart-large-cnn"
        payload2 = {
            "inputs": texto[:2200],
            "parameters": {"max_length": 130, "min_length": 25, "do_sample": False},
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp2 = await client.post(url2, headers=headers, json=payload2)
            if resp2.status_code == 200:
                data2 = resp2.json()
                summ = None
                if isinstance(data2, list) and data2:
                    summ = data2[0].get("summary_text", "").strip()
                elif isinstance(data2, dict):
                    summ = data2.get("summary_text", "").strip()
                if summ and len(summ) > 30:
                    return summ[:950]
    except Exception:
        pass

    # 3) Fallback: extractivo mejorado (local, siempre funciona)
    return _resumen_extractivo(texto, titulo)

# CLI para testing
async def main():
    import argparse, os
    parser = argparse.ArgumentParser()
    parser.add_argument("--fecha", default=None, help="YYYY-MM-DD o YYYYMMDD")
    parser.add_argument("--palabras", default="", help="comma separated")
    parser.add_argument("--test-vivo", action="store_true", help="scrape hoy sin palabras")
    args = parser.parse_args()
    if args.fecha:
        try:
            if "-" in args.fecha:
                f = datetime.strptime(args.fecha, "%Y-%m-%d").date()
            else:
                f = datetime.strptime(args.fecha, "%Y%m%d").date()
        except Exception:
            f = datetime.now(BA_TZ).date()
    else:
        f = datetime.now(BA_TZ).date()
    print(f"[boletin] fecha {f} seccion primera")
    avisos = await scrape_primera(f)
    print(f"Avisos encontrados: {len(avisos)}")
    for av in avisos[:5]:
        print(f" - {av['titulo'][:120]} | {av['url'][:80]}")
    if args.palabras:
        palabras = [p.strip() for p in args.palabras.split(",") if p.strip()]
        hits = filtrar_por_palabras(avisos, palabras)
        print(f"\nHits para {palabras}: {len(hits)}")
        for h in hits:
            print(f" * {h.titulo[:120]} matched={h.matched}")
            det = await scrape_detalle(h.url)
            print(f"   detalle len {len(det)} -> {det[:200]}")
            hf = os.getenv("HF_TOKEN", "")
            res = await resumir_ia(det, h.titulo, hf)
            print(f"   resumen: {res[:300]}")

if __name__ == "__main__":
    asyncio.run(main())
