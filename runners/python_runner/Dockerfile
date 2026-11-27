FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.0 uvicorn==0.30.6 pydantic==2.9.2 pytest==8.3.5 \
    && groupadd --gid 10001 mas && useradd --uid 10001 --gid mas --no-create-home mas
COPY common/ /app/common/
COPY runners/python_runner/ /app/runners/python_runner/
USER 10001:10001
EXPOSE 8004
CMD ["uvicorn", "runners.python_runner.main:app", "--host", "0.0.0.0", "--port", "8004"]
