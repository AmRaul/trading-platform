FROM python:3.11-slim

WORKDIR /app

# Системные зависимости для сборки Python-пакетов и curl (для healthcheck)
RUN apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        curl \
        build-essential \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Устанавливаем зависимости Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем исходный код приложения
COPY . .

# Создаём необходимые директории (до монтирования volume'ов)
RUN mkdir -p data reports logs templates static db

# Создаём непривилегированного пользователя
RUN useradd -m -u 1000 backtester && \
    chown -R backtester:backtester /app

USER backtester

# Порт, который слушает gunicorn
EXPOSE 8000

# Переменные окружения
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=web_app.py \
    FLASK_ENV=production

# Точка входа: gunicorn с Flask-приложением web_app:app
CMD ["gunicorn", "web_app:app", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "300", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "--capture-output"]