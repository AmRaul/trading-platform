FROM python:3.13-alpine

# клиент той же версии, что и сервер (postgres:16-alpine): дамп 17-го клиента не восстанавливается в 16 без ошибок
RUN apk add --no-cache postgresql16-client openssl
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backup.py .

ENV PYTHONUNBUFFERED=1
RUN mkdir /backups && chown nobody /backups
USER nobody
CMD ["python", "backup.py"]
