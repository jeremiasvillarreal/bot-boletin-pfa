FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODO=cloud PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libdbus-1-3 libxkbcommon0 libatspi2.0-0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libwayland-client0 libwayland-cursor0 libwayland-egl1 \
    fonts-liberation xdg-utils wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-bot.txt ./
RUN pip install --no-cache-dir -r requirements-bot.txt \
    && playwright install chromium

COPY . .
EXPOSE 8000
CMD ["python", "-m", "bot.main"]
