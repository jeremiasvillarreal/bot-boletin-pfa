"""
scraper.base — Browser helper CDP ↔ headless fallback

Uso local vs nube:
------------------
- LOCAL (dev Windows):
    1. Lanzar Chrome con debug:
       & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir=".chrome-debug"
    2. Verificar: http://localhost:9222/json/version  (debe responder JSON)
    3. get_browser() hará connect_over_cdp(CHROME_CDP_URL) con timeout 2s.
       Si conecta, reutiliza la ventana visible (útil para debug / Cloudflare).
       Si falla, cae a launch(headless=True).

- NUBE (Render / Docker / CI):
    Sin Chrome debug disponible. Define env MODO=cloud y el helper va
    directo a playwright.chromium.launch(headless=True) sin intentar CDP.
    También funciona con MODO=local si CDP no responde (fallback automático).

Env vars:
    CHROME_CDP_URL  default http://localhost:9222
    MODO            local | cloud   (default: local)

Asumido: Chrome debug puerto 9222
"""

import os

import httpx
from playwright.async_api import Playwright

CHROME_CDP_URL: str = os.getenv("CHROME_CDP_URL", "http://localhost:9222")
MODO: str = os.getenv("MODO", "local").lower()

# Cache de disponibilidad de Playwright browser (evita re-check en cada uso)
_playwright_available: bool | None = None


def check_playwright_browser() -> bool:
    """Verifica si Chromium de Playwright está instalado. Cachea resultado."""
    global _playwright_available
    if _playwright_available is not None:
        return _playwright_available
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        _playwright_available = True
    except Exception:
        _playwright_available = False
    return _playwright_available


def is_cdp_available(url: str | None = None) -> bool:
    """Chequea si el endpoint CDP responde en /json/version.

    Usa httpx GET síncrono con timeout corto (2s). Retorna True si
    status 200, False en cualquier excepción/timeout.

    Args:
        url: URL base CDP (default: CHROME_CDP_URL por env).

    Returns:
        bool: True si CDP disponible.
    """
    target = (url or os.getenv("CHROME_CDP_URL", "http://localhost:9222")).rstrip("/")
    endpoint = f"{target}/json/version"
    try:
        resp = httpx.get(endpoint, timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


async def is_cdp_available_async(url: str | None = None) -> bool:
    """Variante async del check CDP (útil dentro de flujo async)."""
    target = (url or os.getenv("CHROME_CDP_URL", "http://localhost:9222")).rstrip("/")
    endpoint = f"{target}/json/version"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(endpoint)
            return resp.status_code == 200
    except Exception:
        return False


async def get_browser(playwright: Playwright):
    """Obtiene un Browser.

    Intenta connect_over_cdp(CHROME_CDP_URL, timeout=2s).
    Si falla o MODO=cloud, hace playwright.chromium.launch(headless=True).

    Args:
        playwright: instancia de Playwright (de async_playwright()).

    Returns:
        Browser: instancia conectada o lanzada.
    """
    # Re-leer env en cada llamada por si cambió entre imports
    modo = os.getenv("MODO", "local").lower()
    cdp_url = os.getenv("CHROME_CDP_URL", "http://localhost:9222")

    # En nube siempre headless, sin intentar CDP
    if modo == "cloud":
        return await playwright.chromium.launch(headless=True)

    # Local: intentar CDP con timeout 2s
    # Chequeo previo opcional para evitar excepción ruidosa
    if is_cdp_available(cdp_url):
        try:
            # timeout en ms para connect_over_cdp
            browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=2000)
            return browser
        except Exception:
            # Fallthrough a launch headless
            pass
    else:
        # Intento directo igual con timeout corto por si el GET falló por falso negativo
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=2000)
            return browser
        except Exception:
            pass

    return await playwright.chromium.launch(headless=True)


async def get_context_and_page(playwright: Playwright):
    """Crea browser + context + page usando get_browser().

    Returns:
        tuple[Browser, BrowserContext, Page]: (browser, context, page)
    """
    browser = await get_browser(playwright)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )
    page = await context.new_page()
    return browser, context, page


async def close_browser(browser) -> None:
    """Cierra el browser de forma segura (tolera ya cerrado)."""
    if browser is None:
        return
    try:
        await browser.close()
    except Exception:
        pass
