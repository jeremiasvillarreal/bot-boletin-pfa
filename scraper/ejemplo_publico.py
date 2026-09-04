"""
scraper.ejemplo_publico — Ejemplo de scraping datos públicos

Demuestra flujo completo:
  base.get_context_and_page → page.goto → page.content → BeautifulSoup → pydantic

Fuentes públicas:
  - HTML: https://quotes.toscrape.com/  (sitio de prueba para scraping)
  - API JSON: https://api.github.com/zen  +  https://httpbin.org/json

Uso:
  python -m scraper.ejemplo_publico
  # o
  python scraper/ejemplo_publico.py

Requisitos: playwright, beautifulsoup4, lxml, httpx, pydantic
  pip install playwright beautifulsoup4 lxml httpx pydantic
  playwright install chromium
"""

import asyncio

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from scraper.base import PLAYWRIGHT_AVAILABLE, close_browser, get_context_and_page


# --- Modelos pydantic ---


class Quote(BaseModel):
    """Quote extraída de quotes.toscrape.com."""

    text: str = Field(description="Texto de la cita")
    author: str = Field(description="Autor de la cita")
    tags: list[str] = Field(default_factory=list, description="Tags asociados")


class ApiZenResponse(BaseModel):
    """Respuesta de https://api.github.com/zen (texto plano)."""

    message: str
    source: str = "api.github.com/zen"


class HttpBinSlide(BaseModel):
    """Slide de https://httpbin.org/json."""

    title: str
    type: str


# --- Scrapers ---


async def scrape_quotes(url: str = "https://quotes.toscrape.com/") -> list[dict]:
    """Scrapea quotes vía Playwright + BeautifulSoup.

    Flujo: get_context_and_page → page.goto → page.content → BeautifulSoup

    Returns:
        list[dict]: Lista de dicts validados por Quote.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return []
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, context, page = await get_context_and_page(p)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            html = await page.content()
        finally:
            await close_browser(browser)

    soup = BeautifulSoup(html, "lxml")
    results: list[dict] = []

    for el in soup.select("div.quote"):
        text_el = el.select_one("span.text")
        author_el = el.select_one("small.author")
        tag_els = el.select("div.tags a.tag")

        raw = {
            "text": text_el.get_text(strip=True) if text_el else "",
            "author": author_el.get_text(strip=True) if author_el else "Unknown",
            "tags": [t.get_text(strip=True) for t in tag_els],
        }

        # Validar con pydantic (descarta vacíos)
        if not raw["text"]:
            continue
        quote = Quote(**raw)
        results.append(quote.model_dump())

    return results


async def scrape_api() -> dict:
    """Ejemplo con httpx a APIs públicas (sin browser).

    Intenta api.github.com/zen, fallback a httpbin.org/json.

    Returns:
        dict: Datos validados.
    """
    headers = {"User-Agent": "Mozilla/5.0 (scraper-ejemplo)"}

    async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True) as client:
        # 1) Intentar GitHub Zen (texto plano)
        try:
            resp = await client.get("https://api.github.com/zen")
            if resp.status_code == 200 and resp.text.strip():
                validated = ApiZenResponse(message=resp.text.strip())
                return validated.model_dump()
        except Exception as e:
            print(f"[scrape_api] api.github.com/zen fallo: {e}")

        # 2) Fallback httpbin.org/json
        try:
            resp = await client.get("https://httpbin.org/json")
            resp.raise_for_status()
            data = resp.json()
            # httpbin devuelve {"slideshow": {"title": ..., "slides": [...]}}
            slideshow = data.get("slideshow", {})
            slides_raw = slideshow.get("slides", [])
            slides = []
            for s in slides_raw:
                try:
                    slides.append(HttpBinSlide(title=s.get("title", ""), type=s.get("type", "")).model_dump())
                except Exception:
                    continue
            return {
                "source": "httpbin.org/json",
                "title": slideshow.get("title", ""),
                "slides": slides,
                "raw": data,
            }
        except Exception as e:
            print(f"[scrape_api] httpbin.org/json fallo: {e}")
            return {"source": "none", "error": str(e), "slides": []}


async def main() -> None:
    """Ejecuta ambos scrapers y printea resultados."""
    print("=== scrape_quotes() — https://quotes.toscrape.com/ ===")
    try:
        quotes = await scrape_quotes()
        print(f"Quotes encontradas: {len(quotes)}")
        for q in quotes[:3]:
            print(f'  - "{q["text"][:80]}..." — {q["author"]} tags={q["tags"]}')
        if len(quotes) > 3:
            print(f"  ... y {len(quotes) - 3} más")
    except Exception as e:
        print(f"[main] scrape_quotes error: {e}")

    print("\n=== scrape_api() — httpx a API pública ===")
    try:
        api_data = await scrape_api()
        print(f"API resultado: {api_data}")
    except Exception as e:
        print(f"[main] scrape_api error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
