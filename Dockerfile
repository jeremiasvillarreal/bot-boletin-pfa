FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODO=cloud PYTHONPATH=/app

WORKDIR /app

# System deps para Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-bot.txt ./
RUN pip install --no-cache-dir -r requirements-bot.txt

# Instalar Chromium de Playwright + dependencias del sistema
RUN playwright install --with-deps chromium

COPY . .
EXPOSE 8000
CMD ["python", "-m", "bot.main"]
