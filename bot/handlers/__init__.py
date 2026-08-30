"""
bot.handlers — Registro centralizado de handlers.

Cada submódulo expone register_*_handlers(application).
register_handlers(application) los agrega todos.

Para agregar un nuevo bot/feature:
  1. Crear bot/handlers/mi_feature.py con def register_mi_feature_handlers(app)
  2. Importar y llamar aquí dentro de register_handlers.
"""

from telegram.ext import Application

from bot.handlers.boletin import register_boletin_handlers
from bot.handlers.info import register_info_handlers
from bot.handlers.scraper import register_scraper_handlers
from bot.handlers.start import register_start_handlers
from bot.handlers.utilidades import register_utilidades_handlers


def register_handlers(application: Application) -> None:
    """Registra todos los handlers modulares en la Application de PTB."""
    register_start_handlers(application)
    register_scraper_handlers(application)
    register_utilidades_handlers(application)
    register_info_handlers(application)
    register_boletin_handlers(application)
