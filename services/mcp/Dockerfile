FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY kandle_mcp.py .

# Удалённый режим для claude.ai / мобильного приложения; локально — stdio (см. README)
ENV KANDLE_MCP_TRANSPORT=http \
    KANDLE_MCP_PORT=8030 \
    PYTHONUNBUFFERED=1
EXPOSE 8030
USER nobody

CMD ["python", "kandle_mcp.py"]
