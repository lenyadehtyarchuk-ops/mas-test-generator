FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.0 uvicorn==0.30.6 pydantic==2.9.2 httpx==0.27.2 \
    && groupadd --gid 10001 mas && useradd --uid 10001 --gid mas --no-create-home mas
COPY common/ /app/common/
COPY orchestrator/ /app/orchestrator/
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
