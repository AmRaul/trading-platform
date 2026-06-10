# Deployment Notes - Optimizer Feature

## Что происходит автоматически при push в main:

### 1. Build (GitHub Actions)
- ✅ Тесты запускаются
- ✅ Линтинг кода
- ✅ Сборка Docker образов (web, analytics, bot)
- ✅ Push в GitHub Container Registry
- ✅ Security scan

### 2. Deploy (Автоматический)
- ✅ Pull свежих образов с новыми зависимостями (optuna, python-telegram-bot)
- ✅ Пересоздание контейнеров (`--force-recreate`)
- ✅ **Автоматическое применение миграций БД** ⬅️ ВАЖНО!
  - Создание таблицы `optimization_results`
  - Добавление колонки `is_optimizer_admin` в `bot_subscribers`
  - Создание индексов
- ✅ Проверка health статуса
- ✅ Показ логов

## Что НЕ происходит автоматически:

❌ Установка вашего Telegram ID как admin (уже в коде)
❌ Настройка .env секретов (уже настроены в GitHub Secrets)

## После деплоя нужно только:

### Проверить что всё работает:

```bash
# SSH на сервер
ssh user@your-server

# Проверить логи
docker logs backtester_web_prod | tail -50

# Проверить что optimizer работает
curl https://your-domain.com/optimize

# Проверить health
curl https://your-domain.com/health
```

### Тестовый запуск (опционально):

```bash
# На сервере
docker exec -it backtester_web_prod python main.py \
  --optimize \
  --optimization-config optimization_config_no_indicators.json \
  --user-id 297936848 \
  --n-trials 10
```

Вы получите Telegram уведомление через ~2 минуты.

## Секреты GitHub (уже настроены)

В Settings → Secrets → Actions должны быть:
- `HOST` - IP или домен сервера
- `USER` - SSH пользователь
- `SSH_KEY` - Приватный SSH ключ
- `GHCR_TOKEN` - GitHub token для Container Registry
- `DOMAIN` - Ваш домен
- `LETSENCRYPT_EMAIL` - Email для SSL
- `DB_USER` - postgres user
- `DB_PASSWORD` - postgres password
- `REDIS_PASSWORD` - redis password
- `TELEGRAM_BOT_TOKEN` - токен бота
- `WEB_PORT` - порт (8000)

## Что делать если что-то пошло не так:

### Миграция не применилась

```bash
# SSH на сервер
ssh user@your-server
cd /opt/backtester

# Применить вручную
docker exec -i backtester_postgres_prod psql -U backtester -d backtester < migrations/001_add_optimizer_tables.sql
```

### Зависимости не установились

```bash
# Пересобрать образы на сервере
cd /opt/backtester
docker compose -f docker-compose.prod.yml build --no-cache backtester-web telegram-bot
docker compose -f docker-compose.prod.yml up -d --force-recreate
```

### Проверить миграции

```bash
docker exec -it backtester_postgres_prod psql -U backtester -d backtester -c \
  "SELECT COUNT(*) FROM backtester.optimization_results;"

# Должно вернуть 0 (таблица существует но пустая)

docker exec -it backtester_postgres_prod psql -U backtester -d backtester -c \
  "SELECT column_name FROM information_schema.columns
   WHERE table_schema='market_data' AND table_name='bot_subscribers'
   AND column_name='is_optimizer_admin';"

# Должно вернуть: is_optimizer_admin
```

## Итого: Что вам нужно сделать

1. ✅ **Git push** - всё остальное автоматически!
2. ✅ **Проверить логи** через 2-3 минуты после деплоя
3. ✅ **Запустить тест** (опционально)

**Вот и всё!** 🎉
