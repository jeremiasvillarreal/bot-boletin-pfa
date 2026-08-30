FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODO=cloud PYTHONPATH=/app

WORKDIR /app

# System deps para Playwright chromium (ANTES de pip para que install-deps funcione)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2t64 libatspi2.0-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-bot.txt ./
RUN pip install --no-cache-dir -r requirements-bot.txt

# Instalar browser chromium de Playwright (necesario para scraping)
RUN playwright install chromium

COPY . .
EXPOSE 8000
CMD ["python", "-m", "bot.main"]
