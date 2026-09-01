"""
bot.config — Configuración centralizada del bot.
"""

import os

from dotenv import load_dotenv

load_dotenv()
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

TELEGRAM_TOKEN: str | None = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN or not TELEGRAM_TOKEN.strip():
    raise RuntimeError(
        "TELEGRAM_TOKEN no definido. "
        "Definilo en .env (copiá .env.example -> .env) o como variable de entorno. "
        "Obtenelo de @BotFather en Telegram."
    )

TELEGRAM_TOKEN = TELEGRAM_TOKEN.strip()

CHROME_CDP_URL: str = os.getenv("CHROME_CDP_URL", "http://localhost:9222").strip()

try:
    PORT: int = int(os.getenv("PORT", "8000").strip())
except ValueError as exc:
    raise RuntimeError(f"PORT debe ser un entero válido, recibido: {os.getenv('PORT')!r}") from exc

MODO: str = os.getenv("MODO", "local").strip().lower()
if MODO not in ("local", "cloud"):
    MODO = "local"

HF_TOKEN: str = os.getenv("HF_TOKEN", "").strip()
if not HF_TOKEN:
    try:
        _hf_path = os.path.join(os.path.dirname(__file__), "..", "presentaciones", "HF_TOKEN.txt")
        if os.path.exists(_hf_path):
            with open(_hf_path, "r", encoding="utf-8") as f:
                HF_TOKEN = f.read().strip()
    except Exception:
        pass

BOLETIN_PALABRAS_DEFAULT: list[str] = ["Policia Federal Argentina", "Fuerzas de seguridad"]
BOLETIN_PALABRAS: str = os.getenv("BOLETIN_PALABRAS", "").strip()
BOLETIN_NOTIFY_CHAT_ID: str = os.getenv("BOLETIN_NOTIFY_CHAT_ID", "").strip()
BOT_ADMIN_ID: str = os.getenv("BOT_ADMIN_ID", "").strip()

def get_boletin_palabras() -> list[str]:
    raw = os.getenv("BOLETIN_PALABRAS", BOLETIN_PALABRAS)
    if raw and raw.strip():
        return [p.strip() for p in raw.split(",") if p.strip()]
    try:
        import json
        p = os.path.join(os.path.dirname(__file__), "..", "data", "boletin_palabras.json")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return [str(x).strip() for x in data if str(x).strip()]
                if isinstance(data, dict) and data.get("palabras"):
                    return [str(x).strip() for x in data["palabras"] if str(x).strip()]
    except Exception:
        pass
    return BOLETIN_PALABRAS_DEFAULT[:]
