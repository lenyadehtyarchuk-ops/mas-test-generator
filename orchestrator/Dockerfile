FROM python:3.11-slim

WORKDIR /app

# Отключаем буферизацию вывода Python (чтобы логи сразу отображались в docker compose logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Устанавливаем минимально необходимые зависимости
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    pydantic==2.9.2 \
    httpx==0.27.2

# Копируем общие схемы и код сервиса
COPY common/ /app/common/
COPY orchestrator/ /app/orchestrator/

EXPOSE 8000

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]