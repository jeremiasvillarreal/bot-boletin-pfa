FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODO=cloud PYTHONPATH=/app

WORKDIR /app
COPY requirements-bot.txt ./
RUN pip install --no-cache-dir -r requirements-bot.txt \
    && playwright install --with-deps chromium

COPY . .
EXPOSE 8000
CMD ["python", "-m", "bot.main"]
