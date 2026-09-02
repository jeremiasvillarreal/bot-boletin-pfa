"""
bot.config — Configuración centralizada del bot.

Carga variables desde .env (dotenv) y valida obligatorias.
Env vars:
  TELEGRAM_TOKEN  (obligatorio) — token de @BotFather
  CHROME_CDP_URL  (opcional, default http://localhost:9222)
  PORT            (opcional, default 8000) — puerto FastAPI /health
  MODO            (opcional, default local) — local | cloud
  HF_TOKEN        (opcional) — token HF Fine-grained para resumen IA
  GROQ_API_KEY    (opcional) — API key Groq (Llama 3.3 70B) para resumen IA
  CEREBRAS_API_KEY (opcional) — API key Cerebras (fallback LLM)
  BOLETIN_PALABRAS (opcional) — lista global comma-separated
  BOLETIN_NOTIFY_CHAT_ID (opcional) — chat_id destino alertas 07:00/08:00
  BOT_ADMIN_ID    (opcional) — admin para /boletin_add
"""

import os

from dotenv import load_dotenv

# Cargar .env desde raíz del workspace (y subdirectorios)
load_dotenv()
# También intentar cargar desde ubicación relativa al proyecto
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
    # No falla duro, solo normaliza; deja warning implícito
    MODO = "local"

# --- Boletín Oficial ---
HF_TOKEN: str = os.getenv("HF_TOKEN", "").strip()
# Reuso presentaciones/HF_TOKEN.txt si existe y HF_TOKEN vacío
if not HF_TOKEN:
    try:
        _hf_path = os.path.join(os.path.dirname(__file__), "..", "presentaciones", "HF_TOKEN.txt")
        if os.path.exists(_hf_path):
            with open(_hf_path, "r", encoding="utf-8") as f:
                HF_TOKEN = f.read().strip()
    except Exception:
        pass

# --- LLM APIs gratuitas (Groq + Cerebras) ---
def _load_key(filename: str) -> str:
    """Carga una API key desde variable de entorno o archivo .txt en la raíz."""
    env_name = filename.replace(".txt", "")
    key = os.getenv(env_name, "").strip()
    if not key:
        try:
            _path = os.path.join(os.path.dirname(__file__), "..", filename)
            if os.path.exists(_path):
                with open(_path, "r", encoding="utf-8") as f:
                    key = f.read().strip()
        except Exception:
            pass
    return key

GROQ_API_KEY: str = _load_key("GROQ_API_KEY.txt")
CEREBRAS_API_KEY: str = _load_key("CEREBRAS_API_KEY.txt")

BOLETIN_PALABRAS_DEFAULT: list[str] = ["Policia Federal Argentina", "Fuerzas de seguridad"]
BOLETIN_PALABRAS: str = os.getenv("BOLETIN_PALABRAS", "").strip()
BOLETIN_NOTIFY_CHAT_ID: str = os.getenv("BOLETIN_NOTIFY_CHAT_ID", "").strip()
BOT_ADMIN_ID: str = os.getenv("BOT_ADMIN_ID", "").strip()

def get_boletin_palabras() -> list[str]:
    """Lista global palabras, re-lee env cada vez para soportar /boletin_add en runtime.
    Siempre devuelve al menos las palabras por defecto (PFA + Fuerzas de seguridad).
    """
    raw = os.getenv("BOLETIN_PALABRAS", BOLETIN_PALABRAS)
    if raw and raw.strip():
        return [p.strip() for p in raw.split(",") if p.strip()]
    # intentar leer de archivo persistente data/boletin_palabras.json
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
