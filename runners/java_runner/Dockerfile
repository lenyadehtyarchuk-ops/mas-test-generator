FROM eclipse-temurin:17-jdk-jammy AS jdk

FROM python:3.11-slim
COPY --from=jdk /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="/opt/java/openjdk/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
# Download JUnit during image build; the running sandbox has no internet access.
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 zlib1g \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi==0.115.0 uvicorn==0.30.6 pydantic==2.9.2 \
    && groupadd --gid 10001 mas && useradd --uid 10001 --gid mas --no-create-home mas
ADD https://repo.maven.apache.org/maven2/org/junit/platform/junit-platform-console-standalone/1.11.4/junit-platform-console-standalone-1.11.4.jar /opt/junit/junit-platform-console-standalone.jar
RUN chmod 444 /opt/junit/junit-platform-console-standalone.jar
COPY common/ /app/common/
COPY runners/java_runner/ /app/runners/java_runner/
USER 10001:10001
EXPOSE 8005
CMD ["uvicorn", "runners.java_runner.main:app", "--host", "0.0.0.0", "--port", "8005"]
