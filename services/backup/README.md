# kandle backup

Каждый день в 03:00 UTC `trading_backup` снимает `trading_db` (боты, позиции, сделки, журнал
разборов) и `signals_db`, шифрует (AES-256, ключ `BACKUP_PASSPHRASE`) и отправляет файлы в
Telegram-канал. Последние 7 копий лежат и на сервере в томе `backups_data`.
Если что-то не получилось, приходит сообщение «🔴 kandle: бэкап не удался» туда же, куда пишет alerter.

## Настройка (один раз)

1. Создать **приватный** канал в Telegram, добавить в него бота alerter'а администратором.
2. Узнать id канала: переслать любой пост канала боту @userinfobot или написать в канал и открыть
   `https://api.telegram.org/bot<токен>/getUpdates` → `channel_post.chat.id` (вида `-100…`).
3. Секреты GitHub (Settings → Secrets → Actions):
   - `TELEGRAM_BACKUP_CHAT_ID` — id канала (пусто → файлы уйдут в `TELEGRAM_CHAT_ID`);
   - `BACKUP_PASSPHRASE` — длинная случайная строка:
     `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.
     **Сохрани её и вне GitHub** (менеджер паролей): без неё бэкапы не расшифровать, а если умрёт
     сервер, достать секрет из GitHub обратно нельзя.
4. После деплоя проверить: `docker exec trading_backup python backup.py now` — в канале появятся файлы.

## Восстановление

Файлы из канала: `trading_2026-11-19_0300.dump.enc` (большие — кусками `.part01`, `.part02`…;
склеить: `cat trading_…dump.enc.part* > trading_…dump.enc`).

```bash
# на сервере, из /opt/trading-platform; бэкенд остановить, чтобы боты не писали в базу
set -a; . ./.env; set +a     # POSTGRES_USER
docker compose stop backend
docker exec -i trading_postgres psql -U "$POSTGRES_USER" -d postgres \
  -c "DROP DATABASE trading_db WITH (FORCE)" -c "CREATE DATABASE trading_db"
BACKUP_PASSPHRASE='…' openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE \
  < trading_2026-11-19_0300.dump.enc \
  | docker exec -i trading_postgres pg_restore --no-owner -U "$POSTGRES_USER" -d trading_db
docker compose start backend
```

Локальная копия с сервера: `docker run --rm -v trading-platform_backups_data:/b alpine ls -l /b`.

Проверить файл, ничего не восстанавливая:
`openssl enc -d … < файл | pg_restore -l | head` — выводит оглавление дампа.
