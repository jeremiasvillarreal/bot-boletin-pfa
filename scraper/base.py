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
    Si Playwright/Chromium no está instalado, se omite el fallback silenciosamente.

Env vars:
    CHROME_CDP_URL  default http://localhost:9222
    MODO            local | cloud   (default: local)

Asumido: Chrome debug puerto 9222
"""

import os
import logging

import httpx

# Playwright es OPCIONAL — si no está instalado, el fallback de scraping se omite
try:
    from playwright.async_api import Playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    Playwright = None  # type: ignore[misc,assignment]
    PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger(__name__)

CHROME_CDP_URL: str = os.getenv("CHROME_CDP_URL", "http://localhost:9222")
MODO: str = os.getenv("MODO", "local").lower()

# Cache de disponibilidad de Chromium browser (evita re-check en cada uso)
_chromium_available: bool | None = None


def check_playwright_browser() -> bool:
    """Verifica si Playwright + Chromium están disponibles. Cachea resultado.

    No lanza browser — solo verifica que el paquete esté importable y que
    el ejecutable de Chromium exista en la ubicación esperada.
    """
    global _chromium_available
    if _chromium_available is not None:
        return _chromium_available
    if not PLAYWRIGHT_AVAILABLE:
        _chromium_available = False
        return False
    try:
        from playwright._impl._driver import compute_driver_executable
        driver_executable = compute_driver_executable()
        if driver_executable and os.path.exists(str(driver_executable)):
            _chromium_available = True
        else:
            _chromium_available = False
    except Exception:
        # Si no podemos verificar, intentamos inferir por la existencia
        # del directorio de navegadores de Playwright
        _chromium_available = False
    return _chromium_available


def is_cdp_available(url: str | None = None) -> bool:
    """Chequea si el endpoint CDP responde en /json/version.

    Usa httpx GET síncrono con timeout corto (2s). Retorna True si
    status 200, False en cualquier excepción/timeout.
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


async def get_browser(playwright: "Playwright"):
    """Obtiene un Browser.

    Intenta connect_over_cdp(CHROME_CDP_URL, timeout=2s).
    Si falla o MODO=cloud, hace playwright.chromium.launch(headless=True).

    Args:
        playwright: instancia de Playwright (de async_playwright()).

    Returns:
        Browser: instancia conectada o lanzada.
    """
    modo = os.getenv("MODO", "local").lower()
    cdp_url = os.getenv("CHROME_CDP_URL", "http://localhost:9222")

    # En nube siempre headless, sin intentar CDP
    if modo == "cloud":
        return await playwright.chromium.launch(headless=True)

    # Local: intentar CDP con timeout 2s
    if is_cdp_available(cdp_url):
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=2000)
            return browser
        except Exception:
            pass
    else:
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=2000)
            return browser
        except Exception:
            pass

    return await playwright.chromium.launch(headless=True)


async def get_context_and_page(playwright: "Playwright"):
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
