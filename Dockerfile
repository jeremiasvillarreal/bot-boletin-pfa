FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODO=cloud PYTHONPATH=/app

WORKDIR /app

COPY requirements-bot.txt ./
RUN pip install --no-cache-dir -r requirements-bot.txt

# Playwright: solo instalar el browser (sin system deps pesados)
# El scraping playwright es fallback; httpx funciona sin él
RUN playwright install --with-deps chromium || echo "WARN: playwright install failed, httpx fallback only"

COPY . .
EXPOSE 8000
CMD ["python", "-m", "bot.main"]
